import hashlib
import io
import json
import sys
from pathlib import Path

from pypdf import PdfReader

from app.papers.limits import MAX_PDF_BYTES


def extract(specification: list[dict]) -> dict:
    pages, limitations = [], set()
    for source in specification:
        try:
            with Path(source["path"]).open("rb") as stream:
                data = stream.read(MAX_PDF_BYTES + 1)
            if len(data) > MAX_PDF_BYTES or hashlib.sha256(data).hexdigest() != source["sha256"]:
                limitations.add("source_hash_mismatch")
                continue
            reader = PdfReader(io.BytesIO(data), strict=False)
            for number in source["pages"]:
                if number < 1 or number > len(reader.pages):
                    limitations.add("original_page_unavailable")
                    continue
                page = reader.pages[number - 1]
                contents = page.get_contents()
                if contents is not None and len(contents.get_data()) > 16 * 1024 * 1024:
                    limitations.add("original_page_too_large")
                    continue
                text = page.extract_text() or ""
                if "\x00" in text:
                    text = text.replace("\x00", "")
                    limitations.add("original_text_sanitized")
                if not text.strip():
                    limitations.add("original_page_has_no_text")
                elif len(text.encode("utf-8")) > 16000:
                    limitations.add("original_page_too_large")
                else:
                    pages.append({"paper_id": source["paper_id"], "page": number, "text": text})
        except Exception:
            limitations.add("original_extraction_unavailable")
    return {"pages": pages, "limitations": sorted(limitations)}


def main():
    try:
        import resource
        # Darwin cannot reliably lower RLIMIT_AS; retain CPU, byte/page
        # budgets and the parent process timeout on that platform.
        if sys.platform != "darwin":
            resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    except ImportError:
        pass
    specification = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    Path(sys.argv[2]).write_text(json.dumps(extract(specification), ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
