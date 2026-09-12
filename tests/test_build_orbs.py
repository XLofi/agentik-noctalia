from __future__ import annotations

import json
import math
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_orbs


class GeneratorTests(unittest.TestCase):
    def test_community_defaults_to_30_fps(self) -> None:
        self.assertEqual(build_orbs.FPS, 30)
        self.assertEqual(build_orbs.FRAMES, 60)

    def test_generates_attributed_60_fps_pack(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            build_orbs.generate(output, 60)

            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            frames = list(output.glob("working-20-*.svg"))

            self.assertEqual(manifest["fps"], 60)
            self.assertEqual(manifest["frame_count"], 120)
            self.assertEqual(len(frames), 120)
            self.assertEqual(manifest["source"], "https://github.com/Jakubantalik/thinking-orbs")
            self.assertEqual(manifest["license"], "MIT")

    def test_rejects_unsupported_frame_rate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "30 or 60"):
                build_orbs.generate(Path(directory), 45)


class DoneOrbTests(unittest.TestCase):
    def test_done_orb_moves_at_native_size(self) -> None:
        initial: list[build_orbs.Dot] = []
        later: list[build_orbs.Dot] = []
        build_orbs.add_done(initial, 20, 0, 0.25, 2.2)
        build_orbs.add_done(later, 20, math.pi / 2, 0.25, 2.2)

        self.assertNotEqual(initial, later)

    def test_done_orb_moves_at_header_size(self) -> None:
        initial = build_orbs.render("done", 64, 0)
        later = build_orbs.render("done", 64, 45)

        self.assertNotEqual(initial, later)

    def test_header_orb_matches_compact_density_with_larger_points(self) -> None:
        compact = build_orbs.render("working", 20, 0)
        header = build_orbs.render("working", 64, 0)
        radii = lambda asset: [float(value) for value in re.findall(r' r="([0-9.]+)"', asset)]

        self.assertEqual(compact.count("<circle"), header.count("<circle"))
        self.assertGreater(max(radii(header)), max(radii(compact)))



class WidgetAssetTests(unittest.TestCase):
    def test_attention_orb_has_a_pulsing_semantic_ring(self) -> None:
        initial = build_orbs.render("working", 20, 0, "blocked")
        later = build_orbs.render("working", 20, build_orbs.FRAMES // 4, "blocked")

        self.assertIn('stroke="#ef5350"', initial)
        self.assertNotEqual(initial, later)

    def test_progress_ring_is_determinate(self) -> None:
        empty = build_orbs.render_progress(0)
        half = build_orbs.render_progress(4)

        self.assertIn('stroke-dasharray="0.000', empty)
        self.assertNotEqual(empty, half)

    def test_progress_ring_runs_counterclockwise(self) -> None:
        ring = build_orbs.render_progress(4)

        self.assertIn('matrix(-1 0 0 1 20 0) rotate(-90 10.0 10.0)', ring)

    def test_progress_ring_has_intermediate_transition_frames(self) -> None:
        self.assertNotEqual(build_orbs.render_progress(3), build_orbs.render_progress(3.5))

if __name__ == "__main__":
    unittest.main()
