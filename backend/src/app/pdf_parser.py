import hashlib
import io
import json
import logging
import sys
from pathlib import Path

import pypdf
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pypdf import PdfReader

MAX_PAGES = 500
MAX_TEXT_BYTES = 8 * 1024 * 1024
MAX_CHUNKS = 10000
MAX_STREAM_BYTES = 16 * 1024 * 1024
CHUNK_CHARACTERS = 2000
MAX_FILE_BYTES = 20 * 1024 * 1024
PARSER_VERSION = f"pypdf-{pypdf.__version__}-text-v1"


class ParseFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(code)


class ParsedChunk(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    chunk_index: int = Field(ge=0)
    page_number: int = Field(ge=1)
    content: str = Field(min_length=1, max_length=CHUNK_CHARACTERS)
    content_sha256: str


class ParseResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    page_count: int = Field(ge=1, le=MAX_PAGES)
    parser_version: str
    chunks: list[ParsedChunk] = Field(min_length=1, max_length=MAX_CHUNKS)

    @model_validator(mode="after")
    def validate_evidence(self):
        previous_page = 0
        size = 0
        if self.parser_version != PARSER_VERSION:
            raise ValueError("Unexpected parser version")
        for position, chunk in enumerate(self.chunks):
            encoded = chunk.content.encode("utf-8")
            size += len(encoded)
            if (
                chunk.chunk_index != position or not previous_page <= chunk.page_number <= self.page_count
                or not chunk.content.strip() or "\x00" in chunk.content
                or chunk.content_sha256 != hashlib.sha256(encoded).hexdigest()
            ):
                raise ValueError("Invalid evidence chunk")
            previous_page = chunk.page_number
        if size > MAX_TEXT_BYTES:
            raise ValueError("Evidence exceeds text limit")
        return self


def parse_pdf(
    source: bytes, *, max_pages: int = MAX_PAGES, max_text_bytes: int = MAX_TEXT_BYTES,
    max_chunks: int = MAX_CHUNKS, max_stream_bytes: int = MAX_STREAM_BYTES,
) -> ParseResult:
    try:
        if not source.startswith(b"%PDF-") or len(source) > MAX_FILE_BYTES:
            raise ParseFailure("PDF_INVALID", "PDF 文件无效或超出上传大小限制")
        reader = PdfReader(io.BytesIO(source), strict=False)
        if reader.is_encrypted:
            raise ParseFailure("PDF_ENCRYPTED", "暂不支持加密 PDF，请上传未加密文件")
        page_count = len(reader.pages)
        if page_count == 0:
            raise ParseFailure("PDF_NO_TEXT", "PDF 没有可提取的文本页面")
        if page_count > max_pages:
            raise ParseFailure("PDF_LIMIT_EXCEEDED", "PDF 超出解析页数限制")
        chunks = []
        total_bytes = 0
        for page_number, page in enumerate(reader.pages, start=1):
            stream = page.get_contents()
            if stream is not None and len(stream.get_data()) > max_stream_bytes:
                raise ParseFailure("PDF_LIMIT_EXCEEDED", "PDF 单页内容流超出解析限制")
            content = (page.extract_text() or "").replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "").strip()
            total_bytes += len(content.encode("utf-8"))
            if total_bytes > max_text_bytes:
                raise ParseFailure("PDF_LIMIT_EXCEEDED", "PDF 文本超出解析大小限制")
            for offset in range(0, len(content), CHUNK_CHARACTERS):
                piece = content[offset:offset + CHUNK_CHARACTERS]
                if not piece.strip():
                    continue
                if len(chunks) >= max_chunks:
                    raise ParseFailure("PDF_LIMIT_EXCEEDED", "PDF 超出解析片段数量限制")
                chunks.append(ParsedChunk(chunk_index=len(chunks), page_number=page_number, content=piece,
                                          content_sha256=hashlib.sha256(piece.encode("utf-8")).hexdigest()))
        if not chunks:
            raise ParseFailure("PDF_NO_TEXT", "PDF 没有可提取文本，扫描件需要 OCR，当前暂不支持")
        return ParseResult(page_count=page_count, parser_version=PARSER_VERSION, chunks=chunks)
    except ParseFailure:
        raise
    except Exception:
        raise ParseFailure("PDF_INVALID", "PDF 损坏或无法提取文本") from None


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
