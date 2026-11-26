"""Offline tests for data-loading, validation, and aggregation helpers."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import shutil
from types import SimpleNamespace

import pandas as pd
import geopandas as gpd
import yaml
from shapely.geometry import box
from PIL import Image

from census import age, foraging
from census.config import load_config
from census.map_utils import load_basemap_bounds


class MapTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.image = self.root / "basemap.png"
        self.color_image = self.root / "basemap_color.png"
        for path in (self.image, self.color_image):
            Image.new("RGB", (8, 8), "white").save(path)
        self.metadata = self.root / "basemap.json"
        self.metadata.write_text(json.dumps({
            "bounds": [[51.7, -1.3], [51.8, -1.2]],
            "color_image": self.color_image.name,
        }))
        self.age_csv = self.root / "ages.csv"
        pd.DataFrame([
            {
                age.AREA_CODE_COLUMN: "E02000001",
                age.AREA_NAME_COLUMN: "Oxford 001",
                age.AGE_CODE_COLUMN: code,
                age.OBSERVATION_COLUMN: 1,
            }
            for code in range(101)
        ]).to_csv(self.age_csv, index=False)

    def test_package_import_is_lightweight(self):
        subprocess.run([
            sys.executable, "-c",
            "import sys; import census; "
            "assert not {'folium', 'geopandas', 'pandas', 'yaml'} & sys.modules.keys(); "
            "assert not hasattr(census, 'main')",
        ], check=True)

    def test_config_requires_exact_string_keys(self):
        path = self.root / "settings.yaml"
        for text in ("[]", "1: value", "unexpected: 1", "key: ["):
            with self.subTest(text=text):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    load_config(path, {"key"})
        path.write_text("key: 1")
        self.assertEqual(load_config(path, {"key"}), {"key": 1})

    def test_age_cutoffs_are_exclusive_and_optional(self):
        for lower, upper, expected in (
            (65, None, 35), (None, 20, 20), (65, 80, 14),
            (None, None, 101), (65, 66, 0),
        ):
            with self.subTest(lower=lower, upper=upper):
                counts = age.aggregate_older_population(self.age_csv, lower, upper)
                self.assertEqual(len(counts), 1)
                self.assertEqual(counts[age.DERIVED_COL_NAME].iloc[0], expected)

    def test_incomplete_age_data_is_rejected(self):
        data = pd.read_csv(self.age_csv).iloc[:-1]
        data.to_csv(self.age_csv, index=False)
        with self.assertRaisesRegex(ValueError, "age codes 0-100"):
            age.aggregate_older_population(self.age_csv, 65, None)

    def test_age_map_embeds_all_ages_and_browser_controls(self):
        boundaries = self.root / "boundaries.geojson"
        gpd.GeoDataFrame(
            {"MSOA21CD": ["E02000001"]},
            geometry=[box(-1.3, 51.7, -1.2, 51.8)], crs="EPSG:4326",
        ).to_file(boundaries, driver="GeoJSON")
        output = self.root / "map.html"
        result = age.create_map(
            self.age_csv, boundaries, output, age.MapSettings(0.32, 65, 80),
            self.image, self.metadata,
        )
        self.assertEqual(result, (1, 14))
        html = output.read_text()
        self.assertIn('"age_counts": [1, 1, 1', html)
        self.assertIn('aria-label="Minimum age"', html)
        self.assertIn('form.elements.minimum.value = 66', html)
        self.assertIn('form.elements.maximum.value = 79', html)
        self.assertIn("form.addEventListener('submit', update)", html)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for browser-logic test")
    def test_browser_age_controls_recalculate_counts_and_styles(self):
        script = age.Template(age.AGE_CONTROLS_TEMPLATE).module.script(
            SimpleNamespace(
                _parent=SimpleNamespace(get_name=lambda: "testMap"),
                layer_name="testPolygons", lower=66, upper=79,
            ), {},
        )
        harness = """
const assert = require('assert');
const elements = {};
const form = {
    elements: {minimum: {}, maximum: {}},
    checkValidity: () => true,
    addEventListener: (event, callback) => { form.submit = callback; }
};
for (const input of Object.values(form.elements)) {
    Object.defineProperty(input, 'valueAsNumber', {get() {return Number(this.value);}});
}
const panel = {style: {}, querySelector(selector) {
    if (selector === 'form') return form;
    return elements[selector] || (elements[selector] = {appendChild() {}});
}};
const document = {createElement: () => ({})};
const map = {};
const L = {
    control: () => ({addTo() {this.onAdd();}, getContainer: () => panel}),
    DomUtil: {create: () => panel},
    DomEvent: {disableClickPropagation() {}, disableScrollPropagation() {}}
};
const layers = [1, 2].map(multiplier => ({
    feature: {properties: {age_counts: Array(101).fill(multiplier),
        'Middle layer Super Output Areas': 'Oxford test'}},
    options: {}, setStyle(style) {this.style = style;},
    unbindTooltip() {}, bindTooltip(tooltip) {this.tooltip = tooltip;}
}));
const polygons = {options: {style: () => ({fillOpacity: 0.68})}, getLayers: () => layers};
const testMap = map;
const testPolygons = polygons;
"""
        assertions = """
assert.strictEqual(layers[0].feature.properties.age_range_population, 14);
assert.strictEqual(layers[1].feature.properties.age_range_population, 28);
form.elements.minimum.value = 0;
form.elements.maximum.value = 100;
form.submit({preventDefault() {}});
assert.strictEqual(layers[0].feature.properties.age_range_population, 101);
assert.strictEqual(layers[1].feature.properties.age_range_population, 202);
assert(elements['[data-summary]'].textContent.includes('303 people'));
assert(layers[0].tooltip.textContent.includes('101 residents'));
assert.strictEqual(polygons.options.style(layers[0].feature).fillColor, layers[0].style.fillColor);
assert.strictEqual(layers[0].style.fillOpacity, 0.68);
form.elements.minimum.value = 90;
form.elements.maximum.value = 20;
form.submit({preventDefault() {}});
assert(elements['[data-error]'].textContent.includes('From no greater than To'));
assert.strictEqual(layers[0].feature.properties.age_range_population, 101);
"""
        subprocess.run(["node", "-e", harness + str(script) + assertions], check=True)

    def test_invalid_basemap_bounds_are_rejected(self):
        self.metadata.write_text('{"bounds": [[true, 0], [1, 1]]}')
        with self.assertRaisesRegex(ValueError, "invalid image bounds"):
            load_basemap_bounds(self.metadata, self.image)

    def test_foraging_locations_load_numeric_coordinates(self):
        locations = self.root / "locations.csv"
        pd.DataFrame({
            "layer": ["Blackberries", "Blackberries"],
            "latitude": [51.75, 52.0], "longitude": [-1.25, -1.25],
        }).to_csv(locations, index=False)
        loaded = foraging.load_foraging_locations(locations)
        self.assertEqual(loaded["latitude"].tolist(), [51.75, 52.0])
        self.assertEqual(loaded["longitude"].tolist(), [-1.25, -1.25])
        self.assertEqual(loaded["layer"].tolist(), ["Blackberries", "Blackberries"])

    def test_foraging_settings_load_knowledge_scores(self):
        config = self.root / "foraging.yaml"
        config.write_text(json.dumps({
            "alpha": 0.75, "reveal_radius_meters": 900,
            "knowledge_scores": {
                "Young": {"new plant": 2.5},
                "Older": {"new plant": 5.5},
            },
        }))
        settings = foraging.load_foraging_settings(config)
        self.assertEqual(settings.alpha, 0.75)
        self.assertEqual(settings.reveal_radius_meters, 900)
        self.assertEqual(
            settings.knowledge_scores,
            {
                "Young": {"new plant": 0.25},
                "Older": {"new plant": 0.75},
            },
        )

    def test_foraging_score_range_and_normalization(self):
        path = self.root / "scores.yaml"
        for score in (1, 2, 3, 4, 5, 6, 7, 3.5):
            with self.subTest(score=score):
                path.write_text(json.dumps({
                    "alpha": 0.45, "reveal_radius_meters": 1400,
                    "knowledge_scores": {"All": {"plant": score}},
                }))
                settings = foraging.load_foraging_settings(path)
                self.assertEqual(settings.knowledge_scores["All"]["plant"],
                                 (score - 1) / 6)

    def test_invalid_foraging_scores_are_rejected(self):
        path = self.root / "scores.yaml"
        for score in (0, 0.5, -1, 0.999, 7.001, 8, True, False,
                      "4", None, [], {}, float("nan"), float("inf"), -float("inf")):
            with self.subTest(score=score):
                path.write_text(json.dumps({
                    "alpha": 0.45, "reveal_radius_meters": 1400,
                    "knowledge_scores": {"All": {"valid": 4, "plant": score}},
                }))
                with self.assertRaisesRegex(ValueError, "between 1 and 7"):
                    foraging.load_foraging_settings(path)

    def test_checked_in_foraging_scores_are_between_one_and_seven(self):
        path = Path(__file__).resolve().parents[1] / "foraging_config.yaml"
        config = yaml.safe_load(path.read_text())
        settings = foraging.load_foraging_settings(path)
        for bracket, scores in config["knowledge_scores"].items():
            for category, score in scores.items():
                with self.subTest(bracket=bracket, category=category):
                    self.assertNotIsInstance(score, bool)
                    self.assertIsInstance(score, (int, float))
                    self.assertTrue(1 <= score <= 7)
                    self.assertAlmostEqual(settings.knowledge_scores[bracket][category],
                                           (score - 1) / 6)

    def test_foraging_modes_lighten_only_the_background(self):
        locations = self.root / "locations.csv"
        pd.DataFrame({
            "layer": ["Blackberries"],
            "latitude": [51.75], "longitude": [-1.25],
        }).to_csv(locations, index=False)
        for mode in foraging.RENDER_MODES:
            with self.subTest(mode=mode):
                output = self.root / f"{mode}.html"
                foraging.create_foraging_map(
                    locations, output, self.image, self.metadata, mode=mode,
                )
                html = output.read_text()
                self.assertIn(
                    ".foraging-basemap { filter: brightness(1.12); }", html,
                )
                self.assertEqual(html.count('"className": "foraging-basemap"'), 1)

    def test_custom_layers_render_in_both_modes(self):
        config = self.root / "custom.yaml"
        config.write_text(json.dumps({
            "alpha": 0.5, "reveal_radius_meters": 900,
            "knowledge_scores": {"All": {"future plant": 5.2, "absent plant": 2.2}},
            "circles": {"category_colors": {"future plant": "#123456"}},
        }))
        settings = foraging.load_foraging_settings(config)
        locations = self.root / "custom.csv"
        pd.DataFrame({
            "layer": ["future plant"], "latitude": [51.75], "longitude": [-1.25],
        }).to_csv(locations, index=False)
        for mode in foraging.RENDER_MODES:
            with self.subTest(mode=mode):
                output = self.root / f"custom-{mode}.html"
                self.assertEqual(foraging.create_foraging_map(
                    locations, output, self.image, self.metadata, settings, mode=mode,
                ), (1, 0))
                html = output.read_text()
                self.assertIn("future plant", html)
                self.assertIn("absent plant", html)
                self.assertIn("#123456", html)
        with self.assertRaisesRegex(ValueError, "unknown layers"):
            foraging.load_foraging_locations(locations, ["different plant"])

    def test_age_brackets_must_have_matching_layers(self):
        config = self.root / "mismatched.yaml"
        for scores in ({"new plant": 4}, {"future plant": 4, "new plant": 2}):
            config.write_text(json.dumps({
                "alpha": 0.5, "reveal_radius_meters": 900,
                "knowledge_scores": {"Young": {"future plant": 2}, "Older": scores},
            }))
            with self.assertRaisesRegex(ValueError, "Invalid categories") as error:
                foraging.load_foraging_settings(config)
            message = str(error.exception)
            self.assertIn("'Older'", message)
            self.assertIn("first age bracket 'Young'", message)
            self.assertIn("new plant", message)
            self.assertIn("update every age bracket", message)

    def test_global_blend_includes_unconfigured_locations(self):
        config = self.root / "global.yaml"
        config.write_text(json.dumps({
            "alpha": 0.5, "reveal_radius_meters": 900,
            "knowledge_scores": {"All": {"global": 4, "plant": 1}},
        }))
        settings = foraging.load_foraging_settings(config)
        self.assertEqual(settings.categories, ["plant"])
        self.assertNotIn("global", settings.colors)
        self.assertEqual(settings.knowledge_scores["All"]["global"], 0.5)
        locations = self.root / "global.csv"
        pd.DataFrame({
            "layer": ["plant", "Uncategorised", "unknown"],
            "latitude": [51.75] * 3, "longitude": [-1.25] * 3,
        }).to_csv(locations, index=False)
        for mode, count in (("blend", 3), ("circles", 1)):
            with self.subTest(mode=mode):
                output = self.root / f"global-{mode}.html"
                self.assertEqual(foraging.create_foraging_map(
                    locations, output, self.image, self.metadata, settings, mode=mode,
                ), (count, 0))
                html = output.read_text()
                self.assertNotIn("<option value='global'>", html)
                if mode == "blend":
                    self.assertIn('"Uncategorised":[[51.75,-1.25]]', html)
                    self.assertIn('"unknown":[[51.75,-1.25]]', html)

    def test_invalid_global_scores_are_rejected(self):
        config = self.root / "invalid-global.yaml"
        for score in (0, 8, True, "4", None):
            with self.subTest(score=score):
                config.write_text(json.dumps({
                    "alpha": 0.5, "reveal_radius_meters": 900,
                    "knowledge_scores": {"All": {"global": score, "plant": 4}},
                }))
                with self.assertRaisesRegex(ValueError, "between 1 and 7"):
                    foraging.load_foraging_settings(config)

    def test_stale_palette_entry_explains_how_to_fix_it(self):
        config = self.root / "stale-colour.yaml"
        config.write_text(json.dumps({
            "alpha": 0.5, "reveal_radius_meters": 900,
            "knowledge_scores": {"All": {"elder trees": 4}},
            "circles": {"category_colors": {"edler trees": "#123456"}},
        }))
        with self.assertRaises(ValueError) as error:
            foraging.load_foraging_settings(config)
        message = str(error.exception)
        for detail in ("circles.category_colors", "edler trees", "elder trees",
                       "Rename/remove", "every knowledge_scores age bracket"):
            self.assertIn(detail, message)


if __name__ == "__main__":
    unittest.main()
