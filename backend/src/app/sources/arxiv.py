import math
import re
import time
import unicodedata
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Protocol
from urllib.parse import urljoin, urlsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

API_URL = "https://export.arxiv.org/api/query"
MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_SEARCH_RESULTS = 50
SearchSortBy = Literal["relevance", "submittedDate", "lastUpdatedDate"]
SearchSortOrder = Literal["ascending", "descending"]
SEARCH_SORT_FIELDS = ("relevance", "submittedDate", "lastUpdatedDate")
SEARCH_SORT_ORDERS = ("ascending", "descending")
ATOM = "{http://www.w3.org/2005/Atom}"
OPENSEARCH = "{http://a9.com/-/spec/opensearch/1.1/}"
ARXIV = "{http://arxiv.org/schemas/atom}"
ERROR_PHASES = frozenset({
    "unknown", "connect", "write", "pool", "response_headers", "response_body",
    "deadline", "source_gate", "provider_status", "response_validation",
})
IDENTIFIER = re.compile(
    r"(?:[0-9]{2}(?:0[1-9]|1[0-2])\.[0-9]{4,5}|"
    r"[a-z][a-z-]*(?:\.[A-Z]{2})?/[0-9]{2}(?:0[1-9]|1[0-2])[0-9]{3})v[1-9][0-9]*"
)


class ArxivError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False, retry_after: int | None = None, phase: str = "unknown"):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.retry_after = retry_after
        self.phase = phase


def invalid_response() -> ArxivError:
    return ArxivError("ARXIV_INVALID_RESPONSE", "arXiv 返回了不合法的响应", phase="response_validation")


def normalize_arxiv_id(value: str) -> str:
    if not isinstance(value, str) or len(value) > 80 or IDENTIFIER.fullmatch(value) is None:
        raise ValueError("A versioned arXiv identifier is required")
    return value


def safe_text(value: str, maximum: int, *, empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError("Text must be a string")
    value.encode("utf-8", errors="strict")
    if any(unicodedata.category(character) in {"Cc", "Cs"} and character not in "\r\n\t" for character in value):
        raise ValueError("Invalid text characters")
    value = " ".join(value.split())
    if len(value) > maximum or (not empty and not value):
        raise ValueError("Invalid text length")
    return value


def build_search_query(value: str) -> tuple[str, str]:
    if not isinstance(value, str) or any(unicodedata.category(character).startswith("C") for character in value):
        raise ValueError("Invalid search query")
    normalized = safe_text(value, 200)
    terms = normalized.split(" ")
    if len(terms) > 20:
        raise ValueError("Too many search terms")
    escaped = [term.replace("\\", "\\\\").replace('"', '\\"') for term in terms]
    return normalized, " AND ".join(f'all:"{term}"' for term in escaped)


def validate_pdf_url(value: str, external_id: str) -> str:
    normalize_arxiv_id(external_id)
    try:
        parsed = urlsplit(value)
        if (
            not isinstance(value, str) or any(character.isspace() or ord(character) < 32 for character in value)
            or parsed.scheme != "https" or parsed.hostname not in {"arxiv.org", "export.arxiv.org"}
            or parsed.port not in {None, 443} or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or "?" in value or "#" in value
            or parsed.path not in {f"/pdf/{external_id}", f"/pdf/{external_id}.pdf"}
        ):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ArxivError("UNSAFE_SOURCE_URL", "下载地址不符合允许的论文来源") from None
    return value


class ArxivPaper(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: Literal["arxiv"] = "arxiv"
    external_id: str
    title: str
    authors: list[str] = Field(max_length=200)
    abstract: str
    doi: str | None = None
    categories: list[str] = Field(max_length=50)
    published_at: AwareDatetime
    source_updated_at: AwareDatetime

    _identifier = field_validator("external_id")(normalize_arxiv_id)

    @field_validator("title")
    @classmethod
    def title_text(cls, value: str) -> str:
        return safe_text(value, 2000)

    @field_validator("abstract")
    @classmethod
    def abstract_text(cls, value: str) -> str:
        return safe_text(value, 20000, empty=True)

    @field_validator("doi")
    @classmethod
    def doi_text(cls, value: str | None) -> str | None:
        return None if value is None else safe_text(value, 512)

    @field_validator("authors", "categories")
    @classmethod
    def text_items(cls, value: list[str], info) -> list[str]:
        return [safe_text(item, 300 if info.field_name == "authors" else 64) for item in value]

    @field_validator("published_at", "source_updated_at")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def chronological(self):
        if self.source_updated_at < self.published_at:
            raise ValueError("Source update predates publication")
        return self

    @property
    def abstract_url(self) -> str:
        return f"https://arxiv.org/abs/{self.external_id}"

    @property
    def pdf_url(self) -> str:
        return f"https://arxiv.org/pdf/{self.external_id}"

    def source_view(self) -> dict:
        return {**self.model_dump(mode="json"), "abstract_url": self.abstract_url, "pdf_url": self.pdf_url}


@dataclass(frozen=True)
class ArxivPage:
    items: list[ArxivPaper]
    total: int
    offset: int
    limit: int


@dataclass(frozen=True)
class DownloadReceipt:
    size_bytes: int
    sha256: str

    def __post_init__(self):
        if type(self.size_bytes) is not int or not 1 <= self.size_bytes <= MAX_PDF_BYTES:
            raise ValueError("Invalid PDF byte count")
        if not isinstance(self.sha256, str) or re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None:
            raise ValueError("Invalid PDF digest")


@dataclass(frozen=True)
class ProviderReply:
    status_code: int
    headers: dict[str, str]
    body: bytes
    receipt: DownloadReceipt | None = None


class ProviderTransport(Protocol):
    def request(
        self, url: str, *, params: dict | None = None,
        destination: Path | None = None, deadline: float,
    ) -> ProviderReply: ...


def element_text(parent: ElementTree.Element, name: str, *, required: bool = True) -> str | None:
    matches = parent.findall(name)
    if len(matches) != 1:
        if not matches and not required:
            return None
        raise ValueError("Missing or duplicate metadata element")
    if len(matches[0]):
        raise ValueError("Nested metadata markup is unsupported")
    return matches[0].text or ""


def source_timestamp(value: str) -> datetime:
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})", value) is None:
        raise ValueError("Invalid source timestamp")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_arxiv_feed(payload: bytes, *, max_results: int = MAX_SEARCH_RESULTS) -> ArxivPage:
    try:
        if not isinstance(payload, bytes) or len(payload) > MAX_METADATA_BYTES:
            raise ValueError("Invalid metadata body")
        if type(max_results) is not int or not 1 <= max_results <= MAX_SEARCH_RESULTS:
            raise ValueError("Invalid result bound")
        document = payload.decode("utf-8-sig", errors="strict")
        if re.search(r"<!\s*(?:DOCTYPE|ENTITY)", document, flags=re.IGNORECASE):
            raise ValueError("XML declarations are unsupported")
        root = ElementTree.fromstring(document)
        if root.tag != ATOM + "feed":
            raise ValueError("Invalid feed namespace")
        numbers = []
        for name in ["totalResults", "startIndex", "itemsPerPage"]:
            value = element_text(root, OPENSEARCH + name)
            if re.fullmatch(r"[0-9]{1,12}", value) is None:
                raise ValueError("Invalid feed count")
            numbers.append(int(value))
        total, offset, limit = numbers
        entries = root.findall(ATOM + "entry")
        if len(entries) > max_results or (entries and (offset + len(entries) > total or len(entries) > limit)):
            raise ValueError("Inconsistent feed counts")
        items = []
        seen = set()
        for entry in entries:
            raw_id = element_text(entry, ATOM + "id")
            parsed = urlsplit(raw_id)
            if (
                parsed.scheme not in {"http", "https"} or parsed.netloc not in {"arxiv.org", "export.arxiv.org"}
                or parsed.query or parsed.fragment or not parsed.path.startswith("/abs/")
            ):
                raise ValueError("Invalid feed identity")
            external_id = normalize_arxiv_id(parsed.path[len("/abs/"):])
            if external_id in seen:
                raise ValueError("Repeated paper identity")
            seen.add(external_id)
            items.append(ArxivPaper(
                external_id=external_id, title=element_text(entry, ATOM + "title"),
                abstract=element_text(entry, ATOM + "summary"),
                authors=[element_text(author, ATOM + "name") for author in entry.findall(ATOM + "author")],
                categories=[category.attrib.get("term", "") for category in entry.findall(ATOM + "category")],
                doi=element_text(entry, ARXIV + "doi", required=False),
                published_at=source_timestamp(element_text(entry, ATOM + "published")),
                source_updated_at=source_timestamp(element_text(entry, ATOM + "updated")),
            ))
        return ArxivPage(items, total, offset, limit)
    except (ValueError, TypeError, AttributeError, ElementTree.ParseError):
        raise invalid_response() from None


def check_status(reply: ProviderReply) -> None:
    if reply.status_code == 200:
        return
    if reply.status_code == 429:
        from app.sources.arxiv_transport import retry_after_seconds

        raise ArxivError("ARXIV_RATE_LIMITED", "arXiv 请求过于频繁，请稍后再试", retryable=True,
                         retry_after=retry_after_seconds(reply.headers.get("retry-after")), phase="provider_status")
    if reply.status_code == 404:
        raise ArxivError("ARXIV_NOT_FOUND", "未找到指定版本的论文", phase="provider_status")
    if reply.status_code == 503 or reply.status_code >= 500:
        from app.sources.arxiv_transport import retry_after_seconds

        raise ArxivError("ARXIV_UNAVAILABLE", "arXiv 服务暂不可用", retryable=True,
                         retry_after=retry_after_seconds(reply.headers.get("retry-after")) if reply.status_code == 503 else None,
                         phase="provider_status")
    raise invalid_response()


class ArxivClient:
    def __init__(self, transport: ProviderTransport):
        self.transport = transport

    def search(self, q: str, limit: int = 10, offset: int = 0, *,
               sort_by: SearchSortBy = "relevance", sort_order: SearchSortOrder = "descending") -> ArxivPage:
        _, query = build_search_query(q)
        if type(limit) is not int or not 1 <= limit <= MAX_SEARCH_RESULTS or type(offset) is not int or not 0 <= offset <= 1000:
            raise ValueError("Invalid search pagination")
        if sort_by not in SEARCH_SORT_FIELDS or sort_order not in SEARCH_SORT_ORDERS:
            raise ValueError("Invalid search sorting")
        reply = self.transport.request(API_URL, params={
            "search_query": query, "start": offset, "max_results": limit,
            "sortBy": sort_by, "sortOrder": sort_order,
        }, deadline=time.monotonic() + 20)
        check_status(reply)
        page = parse_arxiv_feed(reply.body, max_results=limit)
        if page.offset != offset:
            raise invalid_response()
        return ArxivPage(page.items, page.total, offset, limit)

    def fetch_metadata(self, external_id: str) -> ArxivPaper:
        external_id = normalize_arxiv_id(external_id)
        reply = self.transport.request(API_URL, params={"id_list": external_id, "max_results": 1}, deadline=time.monotonic() + 20)
        check_status(reply)
        page = parse_arxiv_feed(reply.body, max_results=1)
        if not page.items:
            raise ArxivError("ARXIV_NOT_FOUND", "未找到指定版本的论文")
        if page.offset != 0 or page.items[0].external_id != external_id:
            raise ArxivError("ARXIV_VERSION_MISMATCH", "返回的论文版本与请求不一致")
        return page.items[0]

    def download_pdf(self, external_id: str, destination: Path, deadline: float | None = None) -> DownloadReceipt:
        external_id = normalize_arxiv_id(external_id)
        deadline = min(time.monotonic() + 90, deadline) if deadline is not None else time.monotonic() + 90
        if not math.isfinite(deadline) or time.monotonic() >= deadline:
            raise ArxivError("ARXIV_TIMEOUT", "arXiv 请求超时", retryable=True)
        url = f"https://arxiv.org/pdf/{external_id}"
        for redirect in range(3):
            validate_pdf_url(url, external_id)
            if time.monotonic() >= deadline:
                raise ArxivError("ARXIV_TIMEOUT", "arXiv 请求超时", retryable=True)
            reply = self.transport.request(url, destination=destination, deadline=deadline)
            if reply.status_code in {301, 302, 303, 307, 308}:
                location = reply.headers.get("location", "")
                if redirect == 2 or not location or len(location) > 2048 or any(part in location for part in ["..", "%", "\\"]):
                    raise ArxivError("UNSAFE_SOURCE_URL", "下载重定向不符合允许的论文来源")
                url = validate_pdf_url(urljoin(url, location), external_id)
                continue
            check_status(reply)
            if reply.receipt is None:
                raise invalid_response()
            return reply.receipt
        raise invalid_response()
