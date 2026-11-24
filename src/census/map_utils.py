from __future__ import annotations

import json
import math
from pathlib import Path
from typing import TYPE_CHECKING

import folium

if TYPE_CHECKING:
    from collections.abc import Sequence


def load_basemap_bounds(metadata_path: Path, image_path: Path) -> list[list[float]]:
    """Load and validate the geographic bounds for the shared Oxford basemap."""
    with metadata_path.open(encoding="utf-8") as metadata_file:
        metadata = json.load(metadata_file)
    bounds = metadata.get("bounds") if isinstance(metadata, dict) else None
    valid_bounds = (
        isinstance(bounds, list)
        and len(bounds) == 2
        and all(
            isinstance(corner, list)
            and len(corner) == 2
            and all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                for value in corner
            )
            for corner in bounds
        )
    )
    if not valid_bounds:
        raise ValueError(f"Basemap metadata has invalid image bounds: {metadata_path}")
    if not image_path.is_file():
        raise ValueError(f"Basemap image does not exist: {image_path}")
    return bounds


def add_basemap(
    map_view: folium.Map,
    image_path: Path,
    bounds: Sequence[Sequence[float]],
) -> None:
    """Add the local Oxford basemap and its OpenStreetMap attribution."""
    folium.raster_layers.ImageOverlay(
        image=str(image_path),
        bounds=bounds,
        name="Local OpenStreetMap basemap",
        interactive=False,
        cross_origin=False,
        zIndex=1,
    ).add_to(map_view)
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
