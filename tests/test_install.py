from __future__ import annotations

import hashlib
import io
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts/install.sh"


class InstallerSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.assets = self.root / "assets"
        self.bin = self.root / "bin"
        self.assets.mkdir()
        self.bin.mkdir()
        fake_curl = self.bin / "curl"
        fake_curl.write_text('#!/bin/sh\ncp "$ASSET_ROOT/$(basename "$5")" "$7"\n', encoding="utf-8")
        fake_curl.chmod(0o755)

    def write_release(self, members: dict[str, bytes]) -> None:
        archive_path = self.assets / "agentik-noctalia.tar.gz"
        with tarfile.open(archive_path, "w:gz") as archive:
            for name, content in members.items():
                info = tarfile.TarInfo(name)
                info.size = len(content)
                info.mode = 0o644
                archive.addfile(info, io.BytesIO(content))
        digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        (self.assets / "agentik-noctalia.tar.gz.sha256").write_text(
            f"{digest}  agentik-noctalia.tar.gz\n", encoding="ascii"
        )

    def run_installer(self) -> subprocess.CompletedProcess[str]:
        environment = {
            **os.environ,
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "ASSET_ROOT": str(self.assets),
            "AGENTIK_PLUGIN_DIR": str(self.root / "installed"),
        }
        return subprocess.run(
            [str(INSTALLER)], cwd=ROOT, env=environment, text=True,
            capture_output=True, check=False,
        )

    def test_installs_verified_safe_archive(self) -> None:
        self.write_release({"agentik-noctalia/plugin.toml": b'name = "Agentik"\n'})
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / "installed/plugin.toml").is_file())

    def test_rejects_archive_path_traversal(self) -> None:
        escaped = self.root / "escaped"
        self.write_release({
            "agentik-noctalia/plugin.toml": b'name = "Agentik"\n',
            "agentik-noctalia/../../escaped": b"private\n",
        })
        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsafe release archive path", result.stderr)
        self.assertFalse(escaped.exists())

    def test_rejects_checksum_for_another_filename(self) -> None:
        self.write_release({"agentik-noctalia/plugin.toml": b'name = "Agentik"\n'})
        checksum = self.assets / "agentik-noctalia.tar.gz.sha256"
        checksum.write_text(checksum.read_text().replace("agentik-noctalia.tar.gz", "other.tar.gz"))
        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid release checksum manifest", result.stderr)


if __name__ == "__main__":
    unittest.main()
