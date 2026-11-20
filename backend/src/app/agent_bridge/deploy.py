import argparse
import os
import tarfile
import tempfile
from pathlib import Path

from app.agent_bridge.files import controlled

RUNTIME_FILES = (
    "baseline.py",
    "config.py",
    "context.py",
    "schemas.py",
    "run_dispatch.py",
    "tacc_bridge.py",
    "pyproject.toml",
    "uv.lock",
    ".python-version",
    ".env.example",
    "tacc.example.json",
)


def build_runtime_archive(agent_root: Path, output: Path) -> Path:
    agent_root, output = controlled(agent_root), controlled(output)
    files = [agent_root / name for name in RUNTIME_FILES]
    for name in ("apis", "agent_io"):
        directory = controlled(agent_root / name)
        files.extend(sorted(directory.rglob("*.py")))
    for path in files:
        if not controlled(path).is_file():
            raise ValueError("Required Agent runtime file is missing")
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=output.name + "-", suffix=".part", dir=output.parent
    )
    os.close(descriptor)
    temporary = Path(name)
    try:
        with tarfile.open(temporary, "w:gz") as archive:
            for path in files:
                if "__pycache__" not in path.parts:
                    archive.add(
                        path,
                        arcname=path.relative_to(agent_root).as_posix(),
                        recursive=False,
                    )
        os.replace(temporary, controlled(output))
    finally:
        temporary.unlink(missing_ok=True)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Package only Agent runtime source, excluding secrets and user PDFs"
    )
    parser.add_argument(
        "--agent-root", type=Path, default=Path(__file__).resolve().parents[4] / "agent"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(build_runtime_archive(args.agent_root, args.output))


if __name__ == "__main__":
    main()
