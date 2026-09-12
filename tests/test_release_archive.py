from __future__ import annotations

import io
import json
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts/check_release_archive.py"
REQUIRED = (
    "LICENSE",
    "THIRD_PARTY_LICENSES",
    "README.md",
    "chat_bridge.py",
    "orbs/manifest.json",
    "scripts/check_repository.py",
)

THINKING_ORBS_NOTICE = b"""Thinking Orbs
Copyright (c) 2026 Jakub Antalik
https://github.com/Jakubantalik/thinking-orbs
MIT License
"""
COMMUNITY_ORB_MANIFEST = json.dumps(
    {
        "copyright": "Copyright (c) 2026 Jakub Antalik",
        "fps": 30,
        "frame_count": 60,
        "license": "MIT",
        "source": "https://github.com/Jakubantalik/thinking-orbs",
    }
).encode()


class ReleaseArchiveTests(unittest.TestCase):
    def make_archive(self, extras: dict[str, bytes] | None = None) -> Path:
        temporary = tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False)
        temporary.close()
        path = Path(temporary.name)
        files = {name: b"public\n" for name in REQUIRED}
        files["orbs/manifest.json"] = COMMUNITY_ORB_MANIFEST
        files["THIRD_PARTY_LICENSES"] = THINKING_ORBS_NOTICE
        files.update(extras or {})
        with tarfile.open(path, "w:gz") as archive:
            for name, content in files.items():
                info = tarfile.TarInfo(f"agentik-noctalia/{name}")
                info.size = len(content)
                info.mode = 0o644
                archive.addfile(info, io.BytesIO(content))
        self.addCleanup(path.unlink, missing_ok=True)
        return path

    def run_checker(self, archive: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(CHECKER), str(archive)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_accepts_public_release_archive(self) -> None:
        result = self.run_checker(self.make_archive())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("check_release_archive: ok", result.stdout)

    def test_rejects_missing_orb_attribution(self) -> None:
        result = self.run_checker(self.make_archive({"THIRD_PARTY_LICENSES": b"MIT License\n"}))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not preserve the Thinking Orbs MIT attribution", result.stderr)

    def test_rejects_wrong_community_orb_frame_rate(self) -> None:
        manifest = json.loads(COMMUNITY_ORB_MANIFEST)
        manifest["fps"] = 60
        manifest["frame_count"] = 120
        result = self.run_checker(
            self.make_archive({"orbs/manifest.json": json.dumps(manifest).encode()})
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("attributed 30 FPS tier", result.stderr)

    def test_accepts_regular_python_source_path(self) -> None:
        result = self.run_checker(self.make_archive({"src/agentik/service.py": b"pass\n"}))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_accepts_optional_high_refresh_asset(self) -> None:
        result = self.run_checker(self.make_archive({"orbs/optional-60fps/frame.webp": b"image"}))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_private_implementation_marker(self) -> None:
        marker = b"class " + b"Entitlement" + b"Store:\n    pass\n"
        result = self.run_checker(self.make_archive({"accidental.py": marker}))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("obsolete or private marker", result.stderr)


if __name__ == "__main__":
    unittest.main()
