import hashlib
import json
import os
import stat
import tempfile
import zipfile
from pathlib import Path
from uuid import UUID

from app.agent_bridge.contracts import DispatchManifest, ResultEnvelope
from app.papers.storage import controlled_path


def canonical_json(value: dict | list) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def manifest_digest(manifest: DispatchManifest) -> str:
    return hashlib.sha256(canonical_json(manifest.model_dump(mode="json"))).hexdigest()


def exchange_directory(root: Path, area: str, dispatch_id: UUID) -> Path:
    if area not in {"outbox", "inbox", "jobs"}:
        raise ValueError("Invalid exchange area")
    root = root.absolute()
    directory = root / area / str(dispatch_id)
    if root.resolve() != root or directory.resolve() != directory:
        raise ValueError("Exchange path must not contain links")
    return directory


def export_bundle(manifest: DispatchManifest, storage_root: Path, exchange_root: Path) -> Path:
    directory = exchange_directory(exchange_root, "outbox", manifest.dispatch_id)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "input.zip"
    if target.is_symlink():
        raise ValueError("Input bundle must not be a link")
    descriptor, temporary_name = tempfile.mkstemp(prefix="input-", suffix=".part", dir=directory)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w+b") as output:
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
                archive.writestr(zipfile.ZipInfo("manifest.json"), canonical_json(manifest.model_dump(mode="json")))
                archive.writestr(zipfile.ZipInfo("task.json"), canonical_json(manifest.task.model_dump(mode="json")))
                archive.writestr(zipfile.ZipInfo("sources.json"), canonical_json([source.model_dump(mode="json") for source in manifest.sources]))
                for source in manifest.sources:
                    path = controlled_path(storage_root, source.paper_id, f"uploads/{source.paper_id}.pdf")
                    digest = hashlib.sha256()
                    size = 0
                    with path.open("rb") as pdf, archive.open(source.path, "w") as destination:
                        while chunk := pdf.read(65536):
                            size += len(chunk)
                            if size > source.size_bytes:
                                raise ValueError("Selected PDF size changed")
                            digest.update(chunk)
                            destination.write(chunk)
                    if size != source.size_bytes or digest.hexdigest() != source.sha256:
                        raise ValueError("Selected PDF digest changed")
            output.flush()
            os.fsync(output.fileno())
        if target.exists():
            with zipfile.ZipFile(target) as previous:
                expected = {"manifest.json", "task.json", "sources.json", *(source.path for source in manifest.sources)}
                if len(previous.namelist()) != len(expected) or set(previous.namelist()) != expected:
                    raise ValueError("Existing input bundle contains unexpected entries")
                if previous.read("manifest.json") != canonical_json(manifest.model_dump(mode="json")):
                    raise ValueError("Dispatch input already exists with different content")
                if previous.read("task.json") != canonical_json(manifest.task.model_dump(mode="json")):
                    raise ValueError("Existing task input has changed")
                if previous.read("sources.json") != canonical_json([source.model_dump(mode="json") for source in manifest.sources]):
                    raise ValueError("Existing source manifest has changed")
                for source in manifest.sources:
                    if previous.getinfo(source.path).file_size != source.size_bytes:
                        raise ValueError("Existing input PDF size has changed")
                    digest = hashlib.sha256()
                    with previous.open(source.path) as pdf:
                        while chunk := pdf.read(65536):
                            digest.update(chunk)
                    if digest.hexdigest() != source.sha256:
                        raise ValueError("Existing input PDF digest has changed")
            return target
        os.replace(temporary, target)
        return target
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path: Path, max_bytes: int):
    if path.is_symlink() or path.resolve() != path.absolute():
        raise ValueError("Result must be a regular controlled file")
    with path.open("rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("Expected a regular unlinked file")
        payload = source.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise ValueError("Agent result exceeds configured size limit")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError("Non-finite JSON number")

    value = json.loads(payload, object_pairs_hook=unique_object, parse_constant=reject_constant)
    canonical_json(value)
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str) and "\x00" in item:
            raise ValueError("NUL characters cannot be stored in Agent results")
        if isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return value


def read_result(path: Path, max_bytes: int) -> ResultEnvelope:
    return ResultEnvelope.model_validate(read_json(path, max_bytes))
