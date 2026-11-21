import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "release.py"
COMMIT = "a" * 40


class ReleaseTests(unittest.TestCase):
    def helper(self):
        specification = importlib.util.spec_from_file_location("release", SCRIPT)
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        return module

    def test_production_storage_requires_absolute_paths(self):
        helper = self.helper()
        for values in ({}, {"STORAGE_ROOT": "runtime/storage"},
                       {"STORAGE_ROOT": "/srv/data", "AGENT_EXCHANGE_ROOT": "exchange"}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                helper.check_storage_paths(values)

    def test_production_storage_accepts_absolute_or_default_exchange(self):
        helper = self.helper()
        helper.check_storage_paths({"STORAGE_ROOT": "/home/acs/acs-data/storage"})
        helper.check_storage_paths({"STORAGE_ROOT": "/srv/data", "AGENT_EXCHANGE_ROOT": "/srv/exchange"})

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def run_helper(self, *arguments):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *map(str, arguments)],
            capture_output=True,
            text=True,
        )

    def archive(self, name="assets/app.js", kind=tarfile.REGTYPE):
        archive = self.root / "frontend.tar.gz"
        with tarfile.open(archive, "w:gz") as output:
            member = tarfile.TarInfo(name)
            member.type = kind
            if kind == tarfile.REGTYPE:
                member.size = 4
                output.addfile(member, io.BytesIO(b"test"))
            else:
                member.linkname = "../../outside"
                output.addfile(member)
        return archive

    def test_valid_archive_is_extracted(self):
        destination = self.root / "site"
        result = self.run_helper("extract", self.archive(), destination)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((destination / "assets/app.js").read_bytes(), b"test")

    def test_unsafe_members_are_rejected_before_any_extraction(self):
        for name, kind in (
            ("../outside", tarfile.REGTYPE),
            ("/absolute", tarfile.REGTYPE),
            ("C:/outside", tarfile.REGTYPE),
            ("assets\\outside", tarfile.REGTYPE),
            ("backend/.env", tarfile.REGTYPE),
            (".git/config", tarfile.REGTYPE),
            ("assets/link", tarfile.SYMTYPE),
            ("assets/link", tarfile.LNKTYPE),
            ("assets/pipe", tarfile.FIFOTYPE),
        ):
            with self.subTest(name=name, kind=kind):
                destination = self.root / "rejected"
                result = self.run_helper("extract", self.archive(name, kind), destination)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Unsafe archive member", result.stderr)
                self.assertFalse(destination.exists())

    def test_nonempty_destination_is_not_overwritten(self):
        destination = self.root / "site"
        destination.mkdir()
        (destination / "keep").write_text("existing")
        result = self.run_helper("extract", self.archive(), destination)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Destination must not already exist", result.stderr)
        self.assertEqual((destination / "keep").read_text(), "existing")

    def package(self):
        for name in ("source.bundle", "frontend.tar.gz", "requirements.txt"):
            (self.root / name).write_bytes(name.encode())
        result = self.run_helper("manifest", self.root, COMMIT)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_manifest_verifies_the_exact_commit_and_files(self):
        self.package()
        result = self.run_helper("verify", self.root, COMMIT)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_manifest_rejects_changed_artifact(self):
        self.package()
        (self.root / "source.bundle").write_bytes(b"changed")
        result = self.run_helper("verify", self.root, COMMIT)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Artifact mismatch", result.stderr)

    def test_manifest_rejects_another_commit(self):
        self.package()
        result = self.run_helper("verify", self.root, "b" * 40)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Commit mismatch", result.stderr)

    def test_manifest_rejects_extra_file_paths(self):
        self.package()
        path = self.root / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["files"]["../outside"] = manifest["files"]["source.bundle"]
        path.write_text(json.dumps(manifest))
        result = self.run_helper("verify", self.root, COMMIT)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unexpected artifact list", result.stderr)

    def test_invalid_commit_is_rejected(self):
        result = self.run_helper("manifest", self.root, "../../outside")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid commit", result.stderr)


class DatabaseBackupTests(unittest.TestCase):
    def helper(self):
        path = ROOT / "backup_database.py"
        self.assertTrue(path.is_file(), "The database backup helper is missing")
        specification = importlib.util.spec_from_file_location("backup_database", path)
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        return module

    def container(self, identity="postgres", port="5432", address="127.0.0.1"):
        return {
            "Id": identity,
            "NetworkSettings": {"Ports": {"5432/tcp": [{"HostPort": port, "HostIp": address}]}},
        }

    def test_backup_selects_the_database_port(self):
        result = self.helper().find_container([self.container("wrong", "5433"), self.container()], 5432)
        self.assertEqual(result, "postgres")

    def test_backup_rejects_ambiguous_containers(self):
        with self.assertRaises(ValueError):
            self.helper().find_container([self.container("one"), self.container("two")], 5432)

    def test_backup_rejects_unrelated_network_binding(self):
        with self.assertRaises(ValueError):
            self.helper().find_container([self.container(address="192.0.2.1")], 5432)


if __name__ == "__main__":
    unittest.main()
