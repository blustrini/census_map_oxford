from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Mapping, Sequence

import folium
import pandas as pd
import yaml

from census.map_utils import add_basemap, load_basemap_bounds

LAYER_COLUMN = "layer"
LABEL_COLUMN = "label"
DESCRIPTION_COLUMN = "description"
LATITUDE_COLUMN = "latitude"
LONGITUDE_COLUMN = "longitude"
REQUIRED_COLUMNS = {LAYER_COLUMN, LABEL_COLUMN, LATITUDE_COLUMN, LONGITUDE_COLUMN}

LAYER_COLORS = {
    "Apples and Pears": "#e41a1c",
    "Blackberries": "#377eb8",
    "Cherries, plums, damsons": "#4daf4a",
    "Sloes, blackthorn and hawthorn": "#984ea3",
    "Elder": "#ff7f00",
    "Additions in 2017": "#a65628",
    "Uncategorised": "#666666",
}
FORAGING_SETTING_KEYS = {"alpha", "dot_sizes"}
DEFAULT_ALPHA = 0.75
DEFAULT_DOT_SIZE = 5


@dataclass(frozen=True)
class ForagingMapSettings:
    alpha: float
    dot_sizes: Mapping[str, float]


def load_foraging_settings(config_path: Path) -> ForagingMapSettings:
    """Load foraging marker sizes and shared alpha from YAML."""
    try:
        with config_path.open(encoding="utf-8") as config_file:
            config = yaml.safe_load(config_file)
    except yaml.YAMLError as error:
        raise ValueError(f"Invalid YAML in {config_path}: {error}") from error

    if not isinstance(config, dict):
        raise ValueError("Foraging configuration must be a YAML mapping")
    if not all(isinstance(key, str) for key in config):
        raise ValueError("Foraging configuration keys must be strings")
    missing = FORAGING_SETTING_KEYS - config.keys()
    unexpected = config.keys() - FORAGING_SETTING_KEYS
    if missing or unexpected:
        details = []
        if missing:
            details.append(f"missing settings: {sorted(missing)}")
        if unexpected:
            details.append(f"unknown settings: {sorted(unexpected, key=str)}")
        raise ValueError("Invalid foraging configuration (" + "; ".join(details) + ")")

    alpha = config["alpha"]
    if (
        isinstance(alpha, bool)
        or not isinstance(alpha, (int, float))
        or not math.isfinite(alpha)
        or not 0 <= alpha <= 1
    ):
        raise ValueError("alpha must be a number between 0 and 1")

    dot_sizes = config["dot_sizes"]
    if not isinstance(dot_sizes, dict) or not all(
        isinstance(layer, str) for layer in dot_sizes
    ):
        raise ValueError("dot_sizes must be a mapping of category names to radii")
    missing_layers = LAYER_COLORS.keys() - dot_sizes.keys()
    unexpected_layers = dot_sizes.keys() - LAYER_COLORS.keys()
    if missing_layers or unexpected_layers:
        details = []
        if missing_layers:
            details.append(f"missing categories: {sorted(missing_layers)}")
        if unexpected_layers:
            details.append(f"unknown categories: {sorted(unexpected_layers)}")
        raise ValueError("Invalid dot_sizes (" + "; ".join(details) + ")")

    validated_sizes: dict[str, float] = {}
    for layer, size in dot_sizes.items():
        if (
            isinstance(size, bool)
            or not isinstance(size, (int, float))
            or not math.isfinite(size)
            or not 0 < size <= 50
        ):
            raise ValueError(f"dot_sizes[{layer!r}] must be greater than 0 and at most 50")
        validated_sizes[layer] = float(size)

    return ForagingMapSettings(alpha=float(alpha), dot_sizes=validated_sizes)


def load_foraging_locations(csv_path: Path) -> pd.DataFrame:
    """Read foraging locations and validate the fields used to render markers."""
    locations = pd.read_csv(csv_path)
    missing_columns = REQUIRED_COLUMNS - set(locations.columns)
    if missing_columns:
        raise ValueError(
            f"Foraging data is missing required columns: {sorted(missing_columns)}"
        )
    if locations.empty:
        raise ValueError("Foraging data contains no locations")

    for column in (LAYER_COLUMN, LABEL_COLUMN):
        locations[column] = locations[column].astype("string").str.strip()
        if locations[column].isna().any() or locations[column].eq("").any():
            raise ValueError(f"Foraging data contains empty {column} values")

    for column in (LATITUDE_COLUMN, LONGITUDE_COLUMN):
        locations[column] = pd.to_numeric(locations[column], errors="coerce")
        if locations[column].isna().any() or not locations[column].map(math.isfinite).all():
            raise ValueError(f"Foraging data contains invalid {column} values")

    if not locations[LATITUDE_COLUMN].between(-90, 90).all():
        raise ValueError("Foraging latitudes must be between -90 and 90")
    if not locations[LONGITUDE_COLUMN].between(-180, 180).all():
        raise ValueError("Foraging longitudes must be between -180 and 180")

    unknown_layers = sorted(set(locations[LAYER_COLUMN]) - LAYER_COLORS.keys())
    if unknown_layers:
        raise ValueError(f"Foraging data contains unknown layers: {unknown_layers}")
    if DESCRIPTION_COLUMN not in locations.columns:
        locations[DESCRIPTION_COLUMN] = ""
    return locations


def _add_legend(map_view: folium.Map, layers: list[str]) -> None:
    entries = "".join(
        "<div style='margin: 3px 0;'>"
        f"<span style='display:inline-block;width:10px;height:10px;"
        f"border-radius:50%;background:{LAYER_COLORS[layer]};margin-right:7px;'></span>"
        f"{escape(layer)}</div>"
        for layer in layers
    )
    map_view.get_root().html.add_child(
        folium.Element(
            "<div style='position: fixed; bottom: 24px; right: 10px; z-index: 9999; "
            "background: rgba(255,255,255,.95); padding: 8px 10px; "
            "border-radius: 4px; box-shadow: 0 1px 5px #888; "
            "font: 12px/1.4 sans-serif;'><strong>Foraging categories</strong>"
            f"{entries}</div>"
        )
    )


def create_foraging_map(
    foraging_data_path: Path,
    output_path: Path,
    basemap_image_path: Path,
    basemap_metadata_path: Path,
    settings: ForagingMapSettings | None = None,
) -> tuple[int, int]:
    """Create a category-coloured foraging map; return (plotted, out of bounds)."""
    if settings is None:
        settings = ForagingMapSettings(
            alpha=DEFAULT_ALPHA,
            dot_sizes={layer: DEFAULT_DOT_SIZE for layer in LAYER_COLORS},
        )
    locations = load_foraging_locations(foraging_data_path)
    image_bounds = load_basemap_bounds(basemap_metadata_path, basemap_image_path)
    (min_lat, min_lon), (max_lat, max_lon) = image_bounds

    in_bounds = locations[
        locations[LATITUDE_COLUMN].between(min_lat, max_lat)
        & locations[LONGITUDE_COLUMN].between(min_lon, max_lon)
    ].copy()
    excluded_count = len(locations) - len(in_bounds)
    if in_bounds.empty:
        raise ValueError("No foraging locations fall within the Oxford basemap bounds")

    center = [(min_lat + max_lat) / 2, (min_lon + max_lon) / 2]
    map_view = folium.Map(
        location=center,
        zoom_start=12,
        tiles=None,
        control_scale=True,
    )
    add_basemap(map_view, basemap_image_path, image_bounds)

    present_layers = sorted(in_bounds[LAYER_COLUMN].unique())
    for layer in present_layers:
        layer_locations = in_bounds.loc[in_bounds[LAYER_COLUMN] == layer]
        feature_group = folium.FeatureGroup(
            name=f"{layer} ({len(layer_locations)})",
            show=True,
        )
        color = LAYER_COLORS[layer]
        for _, location in layer_locations.iterrows():
            label = escape(str(location[LABEL_COLUMN]))
            description = location[DESCRIPTION_COLUMN]
            tooltip_text = f"<strong>{label}</strong><br>{escape(layer)}"
            if pd.notna(description) and str(description).strip():
                tooltip_text += f"<br>{escape(str(description).strip())}"
            folium.CircleMarker(
                location=(location[LATITUDE_COLUMN], location[LONGITUDE_COLUMN]),
                radius=settings.dot_sizes[layer],
                color=color,
                opacity=settings.alpha,
                weight=1,
                fill=True,
                fill_color=color,
                fill_opacity=settings.alpha,
                tooltip=folium.Tooltip(tooltip_text, sticky=False),
            ).add_to(feature_group)
        feature_group.add_to(map_view)

    folium.LayerControl(collapsed=False).add_to(map_view)
    _add_legend(map_view, present_layers)
    title = folium.Element(
        "<div style='position: fixed; top: 16px; left: 60px; z-index: 9999; "
        "background: white; padding: 10px 14px; border-radius: 4px; "
        "box-shadow: 0 1px 5px #888; font: 16px/1.4 sans-serif;'>"
        f"<strong>Oxford foraging locations</strong><br>{len(in_bounds)} locations</div>"
    )
    map_view.get_root().html.add_child(title)
    map_view.fit_bounds(image_bounds)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    map_view.save(output_path)
    return len(in_bounds), excluded_count


def main(argv: Sequence[str] | None = None) -> None:
    project_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description="Map Oxford foraging locations on the local Oxford basemap."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=project_root / "foraging_config.yaml",
        help="Path to YAML foraging-map settings",
    )
    parser.add_argument(
        "--foraging-data",
        type=Path,
        default=project_root / "data" / "oxford_foraging.csv",
        help="Path to the foraging locations CSV",
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
        default=project_root / "outputs" / "oxford_foraging_map.html",
        help="Path for the generated interactive HTML map",
    )
    args = parser.parse_args(argv)

    try:
        settings = load_foraging_settings(args.config)
        plotted_count, excluded_count = create_foraging_map(
            args.foraging_data,
            args.output,
            args.basemap_image,
            args.basemap_metadata,
            settings,
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))

    message = f"Saved {args.output} with {plotted_count} foraging locations"
    if excluded_count:
        message += f" ({excluded_count} outside the basemap bounds omitted)"
    print(message + ".")


if __name__ == "__main__":
    main()
