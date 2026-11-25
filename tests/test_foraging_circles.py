"""Circle configuration and executable canvas rendering checks."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from census.foraging import LAYER_COLORS, load_foraging_settings
from census.foraging_circles import CIRCLE_DRAW_SCRIPT, circle_legend, load_circle_settings


class CircleTests(unittest.TestCase):
    def test_defaults_and_partial_palette(self):
        settings = load_circle_settings({"category_colors": {"Elder": "#123456"}}, LAYER_COLORS)
        self.assertEqual(settings.category_colors["Elder"], "#123456")
        self.assertEqual(settings.category_colors["Blackberries"], LAYER_COLORS["Blackberries"])
        self.assertEqual(settings.max_radius_meters, 840)
        self.assertIn("280–840 metres", circle_legend(settings.category_colors, settings))

    def test_invalid_values(self):
        for config in (
            None, [], {"typo": 1}, {"opacity": True}, {"opacity": 1.1},
            {"min_radius_meters": -1}, {"max_radius_meters": 0},
            {"min_radius_meters": 900, "max_radius_meters": 800},
            {"fade_steepness": 0}, {"fade_steepness": float("nan")},
            {"solid_core": 1}, {"category_colors": None},
            {"category_colors": {"Unknown": "#123456"}},
            {"category_colors": {"Elder": "red"}},
            {"category_colors": {"Elder": None}},
        ):
            with self.subTest(config=config), self.assertRaises(ValueError):
                load_circle_settings(config, LAYER_COLORS)

    def test_old_and_new_yaml(self):
        config = {
            "alpha": 0.45, "reveal_radius_meters": 1400,
            "knowledge_scores": {"All": dict.fromkeys(LAYER_COLORS, 0.5)},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text(json.dumps(config))
            self.assertEqual(load_foraging_settings(path).circles.opacity, 0.45)
            config["circles"] = {"opacity": 0.2, "min_radius_meters": 12.5}
            path.write_text(json.dumps(config))
            self.assertEqual(load_foraging_settings(path).circles.min_radius_meters, 12.5)
            self.assertEqual(load_foraging_settings(path).circles.opacity, 0.2)

    @unittest.skipUnless(shutil.which("node"), "Node.js required")
    def test_canvas_radius_opacity_and_fade(self):
        harness = """
const assert = require('assert');
const selectedCategories = ['Elder'];
let knowledgeScores = {All: {Elder: 0.5}};
const age = 'All';
const categoryColors = {Elder: '#123456'};
const locationsByCategory = {Elder: [[0, 0]]};
const foragingMap = {latLngToContainerPoint: () => ({x: 0, y: 0}), getZoom: () => 0};
const circleStyle = {min_radius_meters: 100, max_radius_meters: 500,
    opacity: 0.2, solid_core: 0.25, fade_steepness: 2};
let radius, alpha, stops, count = 0;
const ctx = {createRadialGradient(...args) {
    radius = args[5]; stops = []; return {addColorStop: (p, c) => stops.push([p, c])};
}, fillRect() {alpha = this.globalAlpha; count++;}};
function draw() {
"""
        assertions = """
}
draw();
const metresPerPixel = 2 * Math.PI * 6378137 / 256;
assert(Math.abs(radius * metresPerPixel - 300) < 1e-9);
assert.strictEqual(alpha, 0.2);
assert.deepStrictEqual(stops[1], [0.25, '#123456ff']);
assert.deepStrictEqual(stops[33], [0.625, '#12345640']);
assert.deepStrictEqual(stops[stops.length - 1], [1, '#12345600']);
knowledgeScores.All.Elder = 1; draw();
assert(Math.abs(radius * metresPerPixel - 500) < 1e-9);
knowledgeScores.All.Elder = 0; draw();
assert.strictEqual(count, 2);
assert.strictEqual(ctx.globalAlpha, 1);
"""
        subprocess.run(["node", "-e", harness + CIRCLE_DRAW_SCRIPT + assertions], check=True)
