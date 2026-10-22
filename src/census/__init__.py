from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import folium
import geopandas as gpd
import pandas as pd
import yaml
from folium import LinearColormap

AGE_CODE_COLUMN = "Age (101 categories) Code"
AREA_CODE_COLUMN = "Middle layer Super Output Areas Code"
AREA_NAME_COLUMN = "Middle layer Super Output Areas"
OBSERVATION_COLUMN = "Observation"
MSOA_BOUNDARY_CODE_COLUMNS = ("MSOA11CD", "MSOA21CD")
MSOA_BOUNDARY_NAME_COLUMNS = ("MSOA11NM", "MSOA21NM")
SETTING_KEYS = {"transparency", "cutoff_age_hi", "cutoff_age_lo"}

DERIVED_COL_NAME = "age_range_population"


@dataclass(frozen=True)
class MapSettings:
    transparency: float
    cutoff_age_lo: int | None
    cutoff_age_hi: int | None


def load_settings(config_path: Path) -> MapSettings:
    """Load map settings from YAML and validate values before map generation."""
    try:
        with config_path.open(encoding="utf-8") as config_file:
            config = yaml.safe_load(config_file)
    except yaml.YAMLError as error:
        raise ValueError(f"Invalid YAML in {config_path}: {error}") from error

    if not isinstance(config, dict):
        raise ValueError("Configuration must be a YAML mapping")
    if not all(isinstance(key, str) for key in config):
        raise ValueError("Configuration keys must be strings")
    missing = SETTING_KEYS - config.keys()
    unexpected = config.keys() - SETTING_KEYS
    if missing or unexpected:
        details = []
        if missing:
            details.append(f"missing settings: {sorted(missing)}")
        if unexpected:
            details.append(f"unknown settings: {sorted(unexpected, key=str)}")
        raise ValueError("Invalid configuration (" + "; ".join(details) + ")")

    transparency = config["transparency"]
    if (
        isinstance(transparency, bool)
        or not isinstance(transparency, (int, float))
        or not math.isfinite(transparency)
        or not 0 <= transparency <= 1
    ):
        raise ValueError("transparency must be a number between 0 and 1")

    cutoff_age_lo = config["cutoff_age_lo"]
    cutoff_age_hi = config["cutoff_age_hi"]

    if isinstance(cutoff_age_lo, bool) or not isinstance(cutoff_age_lo, (int, type(None))):
        raise ValueError("cutoff_age must be a whole number between 0 and 99")
    if isinstance(cutoff_age_hi, bool) or not isinstance(cutoff_age_hi, (int, type(None))):
        raise ValueError("cutoff_age must be a whole number between 0 and 99")

    if cutoff_age_hi is not None and (not 0 <= cutoff_age_hi <= 99):
        raise ValueError("cutoff_age must be a whole number between 0 and 99")

    if cutoff_age_lo is not None and (not 0 <= cutoff_age_lo <= 99):
        raise ValueError("cutoff_age must be a whole number between 0 and 99")

    return MapSettings(
        transparency=float(transparency), 
        cutoff_age_hi=cutoff_age_hi, 
        cutoff_age_lo=cutoff_age_lo,
    )


def aggregate_older_population(
    age_data_path: Path, 
    cutoff_age_lo: int | None,
    cutoff_age_hi: int | None,

) -> pd.DataFrame:
    """Return counts strictly above cutoff_age by Oxford MSOA."""
    age_data = pd.read_csv(age_data_path, dtype={AREA_CODE_COLUMN: "string"})
    required_columns = {
        AGE_CODE_COLUMN,
        AREA_CODE_COLUMN,
        AREA_NAME_COLUMN,
        OBSERVATION_COLUMN,
    }
    missing_columns = required_columns - set(age_data.columns)
    if missing_columns:
        raise ValueError(f"Age data is missing required columns: {sorted(missing_columns)}")

    age_data = age_data.loc[
        age_data[AREA_NAME_COLUMN].astype("string").str.startswith("Oxford ", na=False)
    ].copy()
    if age_data.empty:
        raise ValueError("Age data contains no Oxford MSOAs")

    age_data[AGE_CODE_COLUMN] = pd.to_numeric(age_data[AGE_CODE_COLUMN], errors="coerce")
    age_data[OBSERVATION_COLUMN] = pd.to_numeric(
        age_data[OBSERVATION_COLUMN], errors="coerce"
    )
    if age_data[[AGE_CODE_COLUMN, OBSERVATION_COLUMN]].isna().any().any():
        raise ValueError("Age codes and observations must contain valid numeric values")
    if (age_data[OBSERVATION_COLUMN] < 0).any():
        raise ValueError("Observations cannot be negative")
    if (age_data[OBSERVATION_COLUMN] % 1 != 0).any():
        raise ValueError("Observations must be whole-number counts")
    if (age_data[AGE_CODE_COLUMN] % 1 != 0).any():
        raise ValueError("Age codes must be whole numbers")
    age_data[AGE_CODE_COLUMN] = age_data[AGE_CODE_COLUMN].astype(int)

    if age_data.duplicated([AREA_CODE_COLUMN, AGE_CODE_COLUMN]).any():
        raise ValueError("Age data contains duplicate MSOA and age-code rows")

    expected_age_codes = set(range(101))
    for code, rows in age_data.groupby(AREA_CODE_COLUMN):
        actual_age_codes = set(rows[AGE_CODE_COLUMN])
        if actual_age_codes != expected_age_codes:
            missing_ages = sorted(expected_age_codes - actual_age_codes)
            unexpected_ages = sorted(actual_age_codes - expected_age_codes)
            raise ValueError(
                f"{code} must have age codes 0-100; "
                f"missing={missing_ages}, unexpected={unexpected_ages}"
            )

    name_counts = age_data.groupby(AREA_CODE_COLUMN)[AREA_NAME_COLUMN].nunique()
    if (name_counts != 1).any():
        raise ValueError("Each MSOA code must have exactly one area name")

    if cutoff_age_hi is None:
        age_data_filt = age_data.loc[age_data[AGE_CODE_COLUMN] > cutoff_age_lo]
    elif cutoff_age_lo is None:
        age_data_filt = age_data.loc[age_data[AGE_CODE_COLUMN] < cutoff_age_hi]
    else:
        age_data_filt = age_data.loc[(age_data[AGE_CODE_COLUMN] < cutoff_age_hi) & (age_data[AGE_CODE_COLUMN] > cutoff_age_lo)]

    older_population = (
        age_data_filt
        .groupby(AREA_CODE_COLUMN, as_index=False)[OBSERVATION_COLUMN]
        .sum()
        .rename(columns={OBSERVATION_COLUMN: DERIVED_COL_NAME})
    )
    area_names = age_data[[AREA_CODE_COLUMN, AREA_NAME_COLUMN]].drop_duplicates()
    return older_population.merge(area_names, on=AREA_CODE_COLUMN, validate="one_to_one")


def match_oxford_boundaries(
    boundaries_path: Path, older_population: pd.DataFrame
) -> gpd.GeoDataFrame:
    """Select Oxford geometries and require a one-to-one MSOA code match."""
    boundaries = gpd.read_file(boundaries_path)
    code_column = next(
        (column for column in MSOA_BOUNDARY_CODE_COLUMNS if column in boundaries.columns),
        None,
    )
    if code_column is None:
        raise ValueError(
            "Boundary data must contain MSOA11CD or MSOA21CD to match MSOA codes"
        )
    if boundaries[code_column].duplicated().any():
        raise ValueError(f"Boundary data contains duplicate values in {code_column}")

    age_codes = set(older_population[AREA_CODE_COLUMN].astype(str))
    boundary_codes = set(boundaries[code_column].dropna().astype(str))
    missing_codes = sorted(age_codes - boundary_codes)
    if missing_codes:
        raise ValueError(f"No boundary geometry for Oxford MSOA codes: {missing_codes}")

    selected = boundaries.loc[boundaries[code_column].astype(str).isin(age_codes)].copy()
    name_column = next(
        (column for column in MSOA_BOUNDARY_NAME_COLUMNS if column in selected.columns),
        None,
    )
    if name_column:
        selected = selected.rename(columns={name_column: "boundary_name"})
    selected = selected.rename(columns={code_column: AREA_CODE_COLUMN})
    if selected.crs is None:
        raise ValueError("Boundary data has no CRS; cannot safely render the map")
    selected = selected.to_crs("EPSG:4326")

    matched = selected.merge(
        older_population,
        on=AREA_CODE_COLUMN,
        how="left",
        validate="one_to_one",
        indicator=True,
    )
    unmatched = matched.loc[matched["_merge"] != "both", AREA_CODE_COLUMN].tolist()
    if unmatched:
        raise ValueError(f"Oxford MSOAs have no age counts: {sorted(unmatched)}")
    return matched.drop(columns="_merge")


def _get_str(settings: MapSettings) -> str:
    if settings.cutoff_age_hi is None:
        return f"above {settings.cutoff_age_lo}"

    if settings.cutoff_age_lo is None:
        return f"below {settings.cutoff_age_hi}"

    return f"between {settings.cutoff_age_lo} and {settings.cutoff_age_hi}"


def create_map(
    age_data_path: Path,
    boundaries_path: Path,
    output_path: Path,
    settings: MapSettings,
    basemap_image_path: Path,
    basemap_metadata_path: Path,
) -> tuple[int, int]:
    """Create an interactive choropleth and return (MSOA count, population total)."""
    counts = aggregate_older_population(age_data_path, settings.cutoff_age_lo, settings.cutoff_age_hi)
    oxford = match_oxford_boundaries(boundaries_path, counts)
    if oxford.empty:
        raise ValueError("No Oxford MSOA boundaries matched the age data")

    with basemap_metadata_path.open(encoding="utf-8") as metadata_file:
        basemap_metadata = json.load(metadata_file)
    image_bounds = basemap_metadata.get("bounds")
    if (
        not isinstance(image_bounds, list)
        or len(image_bounds) != 2
        or any(not isinstance(corner, list) or len(corner) != 2 for corner in image_bounds)
    ):
        raise ValueError(f"Basemap metadata has invalid image bounds: {basemap_metadata_path}")
    if not basemap_image_path.is_file():
        raise ValueError(f"Basemap image does not exist: {basemap_image_path}")

    minimum = int(oxford[DERIVED_COL_NAME].min())
    maximum = int(oxford[DERIVED_COL_NAME].max())

    age_str = _get_str(settings)
    color_scale = LinearColormap(
        colors=["#ffffcc", "#c2e699", "#78c679", "#238443", "#006837"],
        vmin=minimum if minimum != maximum else minimum - 1,
        vmax=maximum if minimum != maximum else maximum + 1,
        caption=f"Residents aged {age_str} (people)",
    )

    def style_feature(feature: dict) -> dict[str, object]:
        count = int(feature["properties"][DERIVED_COL_NAME])
        return {
            "fillColor": color_scale(count),
            "color": "#ffffff",
            "weight": 1,
            "fillOpacity": 1 - settings.transparency,
        }

    min_x, min_y, max_x, max_y = oxford.total_bounds
    map_view = folium.Map(
        location=[(min_y + max_y) / 2, (min_x + max_x) / 2],
        zoom_start=12,
        tiles=None,
        control_scale=True,
    )
    folium.raster_layers.ImageOverlay(
        image=str(basemap_image_path),
        bounds=image_bounds,
        name="Local OpenStreetMap basemap",
        interactive=False,
        cross_origin=False,
        zindex=1,
    ).add_to(map_view)

    age_str = _get_str(settings)

    title = folium.Element(
        "<div style='position: fixed; top: 16px; left: 60px; z-index: 9999; "
        "background: white; padding: 10px 14px; border-radius: 4px; "
        "box-shadow: 0 1px 5px #888; font: 16px/1.4 sans-serif;'>"
        f"<strong>Oxford residents aged {age_str}</strong><br>"
        f"{int(oxford[DERIVED_COL_NAME].sum()):,} people across "
        f"{len(oxford)} MSOAs</div>"
    )
    map_view.get_root().html.add_child(title)
    map_view.get_root().html.add_child(
        folium.Element(
            "<div style='position: fixed; bottom: 24px; left: 10px; z-index: 9999; "
            "background: rgba(255,255,255,.9); padding: 4px 7px; "
            "font: 11px/1.4 sans-serif;'>"
            "Basemap data: &copy; "
            "<a href='https://www.openstreetmap.org/copyright'>"
            "OpenStreetMap contributors</a> ("
            "<a href='https://opendatacommons.org/licenses/odbl/1-0/'>"
            "ODbL 1.0</a>; locally rendered)</div>"
        )
    )

    folium.GeoJson(
        oxford.to_json(),
        name=f"Residents aged {age_str}",
        style_function=style_feature,
        highlight_function=lambda _: {"weight": 3, "color": "#333333"},
        tooltip=folium.GeoJsonTooltip(
            fields=[AREA_NAME_COLUMN, DERIVED_COL_NAME],
            aliases=["MSOA", f"Residents aged {age_str}"],
            localize=True,
            sticky=False,
        ),
    ).add_to(map_view)
    color_scale.add_to(map_view)
    map_view.fit_bounds(image_bounds)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    map_view.save(output_path)
    return len(oxford), int(oxford[DERIVED_COL_NAME].sum())


def main(argv: Sequence[str] | None = None) -> None:
    project_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description="Map Oxford MSOA population counts using the configured age cutoff."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=project_root / "config.yaml",
        help="Path to YAML map settings",
    )
    parser.add_argument(
        "--age-data",
        type=Path,
        default=project_root / "data" / "age_data_oxford.csv",
        help="Path to the Oxford single-year age CSV",
    )
    parser.add_argument(
        "--boundaries",
        type=Path,
        default=project_root / "data" / "msoa_boundaries_2021.geojson",
        help="Path to the MSOA boundary GeoJSON",
    )
    parser.add_argument(
        "--basemap-image",
        type=Path,
        default=project_root / "assets" / "oxford_basemap.png",
        help="Path to the locally rendered basemap PNG",
    )
    parser.add_argument(
        "--basemap-metadata",
        type=Path,
        default=project_root / "assets" / "oxford_basemap.json",
        help="Path to the basemap JSON containing geographic image bounds",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=project_root / "outputs" / "oxford_map.html",
        help="Path for the generated interactive HTML map",
    )
    args = parser.parse_args(argv)

    try:
        settings = load_settings(args.config)
        area_count, population_total = create_map(
            args.age_data,
            args.boundaries,
            args.output,
            settings,
            args.basemap_image,
            args.basemap_metadata,
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))

    age_str = _get_str(settings)

    print(
        f"Saved {args.output} with {area_count} Oxford MSOAs "
        f"and {population_total:,} residents aged {age_str}."
    )


__all__ = [
    "aggregate_older_population",
    "create_map",
    "load_settings",
    "main",
    "match_oxford_boundaries",
    "MapSettings",
]
