import unittest
import json
from tempfile import TemporaryDirectory
from pathlib import Path

from census import (
    MapSettings,
    aggregate_older_population,
    create_map,
    load_settings,
    match_oxford_boundaries,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGE_DATA = PROJECT_ROOT / "data" / "age_data_oxford.csv"
BOUNDARIES = PROJECT_ROOT / "data" / "msoa_boundaries_2021.geojson"
BASEMAP_IMAGE = PROJECT_ROOT / "assets" / "oxford_basemap.png"
BASEMAP_METADATA = PROJECT_ROOT / "assets" / "oxford_basemap.json"


class OxfordPopulationMapTests(unittest.TestCase):
    def test_aggregates_people_strictly_older_than_65(self) -> None:
        population = aggregate_older_population(AGE_DATA)

        self.assertEqual(len(population), 19)
        self.assertEqual(int(population["older_population"].sum()), 17_840)

    def test_cutoff_setting_controls_age_aggregation(self) -> None:
        population = aggregate_older_population(AGE_DATA, cutoff_age=64)

        self.assertEqual(int(population["older_population"].sum()), 18_973)

    def test_loads_and_validates_yaml_settings(self) -> None:
        with TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.yaml"
            config_path.write_text("transparency: 0.4\ncutoff_age: 70\n")

            self.assertEqual(
                load_settings(config_path), MapSettings(transparency=0.4, cutoff_age=70)
            )

    def test_rejects_invalid_yaml_setting_values(self) -> None:
        invalid_configs = [
            "transparency: 1.1\ncutoff_age: 65\n",
            "transparency: 0.4\ncutoff_age: 65.5\n",
            "transparency: 0.4\nunknown: true\n",
        ]
        with TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.yaml"
            for config in invalid_configs:
                with self.subTest(config=config):
                    config_path.write_text(config)
                    with self.assertRaises(ValueError):
                        load_settings(config_path)

    def test_all_oxford_age_areas_have_boundary_geometries(self) -> None:
        population = aggregate_older_population(AGE_DATA)

        mapped_areas = match_oxford_boundaries(BOUNDARIES, population)

        self.assertEqual(len(mapped_areas), 19)
        self.assertTrue(mapped_areas.geometry.notna().all())
        self.assertEqual(int(mapped_areas["older_population"].sum()), 17_840)

    def test_map_embeds_local_basemap_without_osm_tile_requests(self) -> None:
        with TemporaryDirectory() as directory:
            output_path = Path(directory) / "map.html"
            create_map(
                AGE_DATA,
                BOUNDARIES,
                output_path,
                MapSettings(transparency=0.32, cutoff_age=74),
                BASEMAP_IMAGE,
                BASEMAP_METADATA,
            )
            html = output_path.read_text()
            metadata = json.loads(BASEMAP_METADATA.read_text())

        self.assertIn("data:image/png;base64,", html)
        self.assertIn("OpenStreetMap contributors", html)
        self.assertNotIn("tile.openstreetmap.org", html)
        self.assertIn("aged over 74", html)
        self.assertEqual(metadata["buffer_metres"], 5_000)


if __name__ == "__main__":
    unittest.main()
