import hashlib
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path


def controlled(path: Path) -> Path:
    path = path.absolute()
    if path.resolve() != path or path.is_symlink():
        raise ValueError("Transport paths must not contain links")
    return path


@contextmanager
def dispatch_lock(directory: Path):
    directory = controlled(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with controlled(directory / ".operation.lock").open("a+b") as handle:
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b"0")
            handle.flush()
        deadline = time.monotonic() + 5
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Dispatch operation lock unavailable") from None
                time.sleep(0.02)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def atomic_write(path: Path, content: bytes) -> None:
    path = controlled(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=path.name + "-", suffix=".part", dir=path.parent
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        controlled(path)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_copy(source: Path, target: Path, max_bytes: int) -> None:
    source, target = controlled(source), controlled(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=target.name + "-", suffix=".part", dir=target.parent
    )
    temporary = Path(name)
    try:
        digest = hashlib.sha256()
        total = 0
        with source.open("rb") as original, os.fdopen(descriptor, "wb") as output:
            while chunk := original.read(65536):
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("Transport file exceeds size limit")
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if target.exists():
            previous = hashlib.sha256()
            with target.open("rb") as existing:
                while chunk := existing.read(65536):
                    previous.update(chunk)
            if target.stat().st_size != total or previous.digest() != digest.digest():
                raise ValueError("Existing transport file has changed")
            return
        controlled(target)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
