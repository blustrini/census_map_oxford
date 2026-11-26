"""Blend configuration compatibility, validation, and canvas gradient tests."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from census.foraging import load_foraging_settings
from census.foraging_blend import BLEND_GRADIENT_SCRIPT, load_blend_settings


class BlendTests(unittest.TestCase):
    def test_legacy_fallbacks_and_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.yaml"
            config = {
                "alpha": 0.7, "reveal_radius_meters": 900,
                "knowledge_scores": {"All": {"wild garlic": 0.5}},
            }
            path.write_text(json.dumps(config))
            settings = load_foraging_settings(path).blend
            self.assertEqual(settings.opacity, 0.7)
            self.assertEqual(settings.radius_meters, 900)
            config["blend"] = {"opacity": 0.2, "saturation": 1.5}
            path.write_text(json.dumps(config))
            settings = load_foraging_settings(path).blend
            self.assertEqual(settings.opacity, 0.2)
            self.assertEqual(settings.radius_meters, 900)
            self.assertEqual(settings.saturation, 1.5)

    def test_invalid_settings(self):
        for config in (None, [], {"typo": 1}, {"radius_meters": 0},
                       {"opacity": True}, {"opacity": 1.1},
                       {"fade_steepness": 0}, {"solid_core": 1},
                       {"saturation": -1}, {"brightness": float("inf")},
                       {"contrast": "high"}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                load_blend_settings(config, 0.45, 1400)

    @unittest.skipUnless(shutil.which("node"), "Node.js required")
    def test_gradient_shape_and_core(self):
        script = """
const assert = require('assert');
const x = 10, y = 20, radius = 300, opacity = 0.4;
const blendStyle = {solid_core: 0.25, fade_steepness: 2};
const stops = [];
const mask = {createRadialGradient(...args) {
    assert.deepStrictEqual(args, [10, 20, 0, 10, 20, 300]);
    return {addColorStop: (p, c) => stops.push([p, c])};
}};
""" + BLEND_GRADIENT_SCRIPT + """
assert.deepStrictEqual(stops[0], [0, 'rgba(255,255,255,0.4)']);
assert.deepStrictEqual(stops[1], [0.25, 'rgba(255,255,255,0.4)']);
assert.deepStrictEqual(stops[33], [0.625, 'rgba(255,255,255,0.1)']);
assert.deepStrictEqual(stops[65], [1, 'rgba(255,255,255,0)']);
"""
        subprocess.run(["node", "-e", script], check=True)
