from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts import build_submission


class SubmissionBuilderTests(unittest.TestCase):
    def test_build_contains_only_reviewable_runtime_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = build_submission.build(Path(directory) / "agentik")
            top_level = {path.name for path in output.iterdir()}

            self.assertEqual(
                top_level,
                set(build_submission.FILES) | set(build_submission.DIRECTORIES),
            )
            self.assertTrue((output / "build_orbs.py").is_file())
            self.assertFalse((output / "orbs").exists())
            self.assertTrue((output / "translations/en.json").is_file())
            for excluded in (
                "CONTRIBUTING.md",
                "ROADMAP.md",
                "SECURITY.md",
                "TROUBLESHOOTING.md",
                "docs",
                "contracts",
                "scripts",
                "tests",
                "core_client.py",
                "assets",
            ):
                self.assertFalse((output / excluded).exists(), excluded)


if __name__ == "__main__":
    unittest.main()
