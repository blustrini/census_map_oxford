"""Blend configuration compatibility, validation, and canvas gradient tests."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import folium

from census.foraging import _add_reveal_controls, load_foraging_settings
from census.foraging_blend import BLEND_GRADIENT_SCRIPT, load_blend_settings


class BlendTests(unittest.TestCase):
    def test_legacy_fallbacks_and_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.yaml"
            config = {
                "alpha": 0.7, "reveal_radius_meters": 900,
                "knowledge_scores": {"All": {"wild garlic": 4}},
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
    def test_score_scales_radius_not_opacity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.yaml"
            path.write_text(json.dumps({
                "alpha": 0.4, "reveal_radius_meters": 1000,
                "knowledge_scores": {"All": {"Elder": 4}},
            }))
            settings = load_foraging_settings(path)
        map_view = folium.Map()
        _add_reveal_controls(
            map_view, None, [[0, 0], [1, 1]],
            {"Elder": [[0, 0]]}, settings, "All",
        )
        script = map_view.get_root().script.render()
        loop = script[script.index("        for (const [latitude, longitude, score]"):
                      script.index("        ctx.globalCompositeOperation = 'destination-in'")]
        harness = """
const assert = require('assert');
const blendStyle = {radius_meters: 1000, opacity: 0.4, solid_core: 0, fade_steepness: 2};
const foragingMap = {latLngToLayerPoint: () => ({x: 0, y: 0}), getZoom: () => 0};
const origin = {x: 0, y: 0};
let radius, stops, count = 0;
const mask = {createRadialGradient(...args) {
    radius = args[5]; stops = []; return {addColorStop: (p, c) => stops.push([p, c])};
}, fillRect() {count++;}};
function draw(score) {
    const points = [[0, 0, score]];
"""
        assertions = """
}
const metresPerPixel = 2 * Math.PI * 6378137 / 256;
for (const score of [0.25, 0.5, 1]) {
    draw(score);
    assert(Math.abs(radius * metresPerPixel - 1000 * score) < 1e-9);
    assert.deepStrictEqual(stops[0], [0, 'rgba(255,255,255,0.4)']);
}
draw(0);
assert.strictEqual(count, 3);
blendStyle.opacity = 0;
draw(1);
assert.strictEqual(count, 3);
"""
        subprocess.run(["node", "-e", harness + loop + assertions], check=True)

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
