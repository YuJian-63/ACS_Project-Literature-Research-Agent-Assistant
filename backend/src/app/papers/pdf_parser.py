import hashlib
import io
import json
import logging
import math
import re
import sys
import unicodedata
from pathlib import Path
from typing import Literal

import pypdf
from pydantic import BaseModel, ConfigDict, Field
from pypdf import PdfReader
from app.papers.limits import MAX_PDF_BYTES as MAX_FILE_BYTES

MAX_PAGES = 500
MAX_RESULT_BYTES = 16 * 1024
MAX_STREAM_BYTES = 16 * 1024 * 1024
PARSER_VERSION = f"pypdf-{pypdf.__version__}-metadata-v2"


class ParseFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(code)


class ParseResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    page_count: int = Field(ge=1, le=MAX_PAGES)
    parser_version: Literal[PARSER_VERSION] = PARSER_VERSION


def normalize_title(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = ''.join(' ' if unicodedata.category(character).startswith('C') else character for character in value)
    title = ' '.join(value.split())
    if not title or title.casefold() in {'untitled', 'untitled document', 'main document', 'document',
            'title', 'paper', 'manuscript', 'article', 'unknown', 'no title', 'abstract', 'introduction',
            'contents', 'references', '摘要', '引言', '目录'}:
        return None
    if re.fullmatch(r'(?:\d{4}\.\d{4,5}(?:v\d+)?|[a-z.-]+/\d{7}(?:v\d+)?)', title, re.IGNORECASE):
        return None
    if title.lower().endswith(('.pdf', '.doc', '.docx', '.tex')) or re.match(
            r'^(?:microsoft (?:word|powerpoint)|arxiv\s*:?\s*\d|preprint\b)', title, re.IGNORECASE):
        return None
    return title[:255].rstrip()


def first_page_title(fragments: list[tuple[str, float]]) -> str | None:
    candidates = [(text, size) for text, size in fragments if normalize_title(text) is not None]
    body_sizes = [size for text, size in candidates if len(text) >= 20]
    if not candidates or not body_sizes:
        return None
    largest = max(size for _, size in candidates)
    if largest < min(body_sizes) * 1.35:
        return None
    lines = []
    for text, size in candidates:
        if size >= largest * .9:
            lines.append(text)
        elif lines:
            break
    return normalize_title(' '.join(lines))


def parse_pdf(
    source: bytes, *, max_pages: int = MAX_PAGES, max_stream_bytes: int = MAX_STREAM_BYTES,
) -> ParseResult:
    try:
        if not source.startswith(b"%PDF-") or len(source) > MAX_FILE_BYTES:
            raise ParseFailure("PDF_INVALID", "PDF 文件无效或超出上传大小限制")
        reader = PdfReader(io.BytesIO(source), strict=False)
        if reader.is_encrypted:
            raise ParseFailure("PDF_ENCRYPTED", "暂不支持加密 PDF，请上传未加密文件")
        page_count = len(reader.pages)
        if page_count == 0:
            raise ParseFailure("PDF_NO_PAGES", "PDF 没有可读取的页面")
        if page_count > max_pages:
            raise ParseFailure("PDF_LIMIT_EXCEEDED", "PDF 超出解析页数限制")
        try:
            title = normalize_title(reader.metadata.title) if reader.metadata else None
        except Exception:
            title = None
        if title is None:
            fragments = []

            def collect_title(text, matrix, text_matrix, font, size):
                if not isinstance(size, (int, float)) or not math.isfinite(size) or size <= 0:
                    return
                if abs(matrix[1]) > abs(matrix[0]):
                    return
                for line in text.splitlines():
                    line = line.strip()
                    if line and len(fragments) < 128:
                        fragments.append((line, float(size)))

            try:
                page = reader.pages[0]
                stream = page.get_contents()
                if stream is None or len(stream.get_data()) <= max_stream_bytes:
                    page.extract_text(visitor_text=collect_title)
                    title = first_page_title(fragments)
            except Exception:
                title = None
        return ParseResult(title=title, page_count=page_count)
    except ParseFailure:
        raise
    except Exception:
        raise ParseFailure("PDF_INVALID", "PDF 损坏或无法读取元信息") from None


def main() -> None:
    logging.disable(logging.CRITICAL)
    source_path, result_path, expected_hash, expected_size = sys.argv[1:]
    try:
        with Path(source_path).open("rb") as source:
            content = source.read(MAX_FILE_BYTES + 1)
        if len(content) != int(expected_size) or hashlib.sha256(content).hexdigest() != expected_hash:
            raise ParseFailure("PDF_SOURCE_CHANGED", "原 PDF 文件与上传记录不一致，请重新上传")
        output = parse_pdf(content).model_dump_json()
    except OSError:
        output = ParseFailure("FILE_UNAVAILABLE", "原 PDF 文件暂时不可读取")
    except ParseFailure as failure:
        output = failure
    if isinstance(output, ParseFailure):
        output = json.dumps({"error": {"code": output.code, "message": output.message}}, ensure_ascii=False)
    Path(result_path).write_text(output, encoding="utf-8")


if __name__ == "__main__":
    main()
