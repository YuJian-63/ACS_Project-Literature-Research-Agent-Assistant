import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tarfile


ARTIFACTS = {"source.bundle", "frontend.tar.gz", "requirements.txt"}


def check_commit(commit):
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Invalid commit: expected a full lowercase SHA-1")


def digest(path):
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("Artifact must be a regular file: " + path.name)
    with path.open("rb") as source:
        value = hashlib.file_digest(source, "sha256").hexdigest()
    return {"sha256": value, "size": path.stat().st_size}


def make_manifest(directory, commit):
    check_commit(commit)
    manifest = {
        "version": 1,
        "commit": commit,
        "files": {name: digest(directory / name) for name in sorted(ARTIFACTS)},
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def verify_manifest(directory, commit):
    check_commit(commit)
    path = directory / "manifest.json"
    if not stat.S_ISREG(path.lstat().st_mode) or path.stat().st_size > 65536:
        raise ValueError("Invalid manifest file")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("version") != 1 or manifest.get("commit") != commit:
        raise ValueError("Commit mismatch or unsupported manifest")
    if set(manifest.get("files", {})) != ARTIFACTS:
        raise ValueError("Unexpected artifact list")
    for name in sorted(ARTIFACTS):
        if digest(directory / name) != manifest["files"][name]:
            raise ValueError("Artifact mismatch: " + name)
    print("Release manifest: OK")


def extract_archive(archive, destination):
    if destination.exists() or destination.is_symlink():
        raise ValueError("Destination must not already exist")
    with tarfile.open(archive, "r:*") as source:
        members = source.getmembers()
        names = set()
        total = 0
        if len(members) > 100000:
            raise ValueError("Too many archive members")
        for member in members:
            path = PurePosixPath(member.name)
            invalid = (
                path.is_absolute() or ".." in path.parts
                or "\\" in member.name or ":" in member.name
                or any(ord(character) < 32 for character in member.name)
                or any(part in {".env", ".git"} for part in path.parts)
                or not (member.isfile() or member.isdir())
                or str(path) in names
            )
            if invalid:
                raise ValueError("Unsafe archive member: " + repr(member.name))
            names.add(str(path))
            total += member.size
            if member.size < 0 or member.size > 256 * 1024 * 1024 or total > 1024 * 1024 * 1024:
                raise ValueError("Archive exceeds release size limit")
        destination.mkdir(parents=True, mode=0o755)
        destination.chmod(0o755)
        for member in members:
            path = destination.joinpath(*PurePosixPath(member.name).parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            if member.isdir():
                path.mkdir(exist_ok=True)
                path.chmod(0o755)
            else:
                with source.extractfile(member) as incoming, path.open("xb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing)
                path.chmod(0o755 if member.mode & 0o111 else 0o644)
        for directory in destination.rglob("*"):
            if directory.is_dir():
                directory.chmod(0o755)
    print("Archive extracted safely")


def check_storage_paths(values):
    root = values.get("STORAGE_ROOT")
    exchange = values.get("AGENT_EXCHANGE_ROOT")
    if not root or not PurePosixPath(root).is_absolute():
        raise ValueError("Production STORAGE_ROOT must be explicitly configured as an absolute persistent path")
    if exchange and not PurePosixPath(exchange).is_absolute():
        raise ValueError("Production AGENT_EXCHANGE_ROOT must be empty or an absolute persistent path")


def snapshot():
    from app.config import Settings
    from dotenv import dotenv_values
    from sqlalchemy.engine import make_url

    values = {key.upper(): value for key, value in dotenv_values(Settings.model_config["env_file"]).items()}
    values.update({key.upper(): value for key, value in os.environ.items()})
    check_storage_paths(values)
    settings = Settings()
    database = make_url(settings.database_url.get_secret_value())
    print(json.dumps({
        "database": {
            "host": database.host,
            "port": database.port or 5432,
            "username": database.username,
            "database": database.database,
        },
        "storage_root": str(settings.storage_root),
        "exchange_root": str(settings.resolved_agent_exchange_root),
        "frontend_public_url": settings.frontend_public_url,
        "agent_transport": settings.agent_transport,
        "agent_dispatch_enabled": settings.agent_dispatch_enabled,
        "agent_library_public_url": settings.agent_library_public_url,
    }, sort_keys=True))


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("manifest", "verify"):
        subparser = commands.add_parser(command)
        subparser.add_argument("directory", type=Path)
        subparser.add_argument("commit")
    extract = commands.add_parser("extract")
    extract.add_argument("archive", type=Path)
    extract.add_argument("destination", type=Path)
    commands.add_parser("snapshot")
    arguments = parser.parse_args()
    try:
        if arguments.command == "manifest":
            make_manifest(arguments.directory, arguments.commit)
        elif arguments.command == "verify":
            verify_manifest(arguments.directory, arguments.commit)
        elif arguments.command == "extract":
            extract_archive(arguments.archive, arguments.destination)
        else:
            snapshot()
    except (ValueError, OSError, tarfile.TarError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
