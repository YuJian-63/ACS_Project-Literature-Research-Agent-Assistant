import json
from pathlib import Path
import subprocess
import sys


def find_container(containers, port):
    matches = []
    for container in containers:
        bindings = (container.get("NetworkSettings", {}).get("Ports") or {}).get("5432/tcp") or []
        if any(binding.get("HostPort") == str(port)
               and binding.get("HostIp") in ("127.0.0.1", "0.0.0.0", "::", "")
               for binding in bindings):
            matches.append(container["Id"])
    if len(matches) != 1:
        raise ValueError("Cannot uniquely identify the local PostgreSQL container")
    return matches[0]


def backup(snapshot, output):
    database = json.loads(Path(snapshot).read_text())["database"]
    if database["host"] not in ("127.0.0.1", "localhost"):
        raise ValueError("Only the existing local PostgreSQL deployment is supported")
    if not database["username"] or not database["database"]:
        raise ValueError("Missing PostgreSQL database identity")
    running = subprocess.check_output(["docker", "ps", "--quiet"], universal_newlines=True, timeout=15).split()
    if not running:
        raise ValueError("No running database container")
    inspected = json.loads(subprocess.check_output(["docker", "inspect", *running], timeout=15))
    container = find_container(inspected, database["port"])
    with Path(output).open("xb") as destination:
        subprocess.run([
            "docker", "exec", container, "pg_dump",
            "--username=" + database["username"], "--dbname=" + database["database"],
            "--no-password", "--format=custom",
        ], stdout=destination, check=True, timeout=300)
    if not Path(output).stat().st_size:
        raise ValueError("Database backup is empty")
    with Path(output).open("rb") as source:
        subprocess.run(["docker", "exec", "-i", container, "pg_restore", "--list"],
                       stdin=source, stdout=subprocess.DEVNULL, check=True, timeout=30)
    print("Database backup: OK")


if __name__ == "__main__":
    backup(*sys.argv[1:])
