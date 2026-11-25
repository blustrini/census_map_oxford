from __future__ import annotations

import json
import math
from pathlib import Path
from typing import TYPE_CHECKING

import folium
from branca.element import Figure
from folium.raster_layers import ImageOverlay

if TYPE_CHECKING:
    from collections.abc import Sequence


def get_map_figure(map_view: folium.Map) -> Figure:
    """Return the containing HTML figure, narrowing Branca's generic root type."""
    root = map_view.get_root()
    if not isinstance(root, Figure):
        raise TypeError("Map must be attached to a Branca Figure")
    return root


def load_basemap_bounds(metadata_path: Path, image_path: Path) -> list[list[float]]:
    """Load and validate the geographic bounds for the shared Oxford basemap."""
    with metadata_path.open(encoding="utf-8") as metadata_file:
        metadata = json.load(metadata_file)
    bounds = metadata.get("bounds") if isinstance(metadata, dict) else None
    error_message = f"Basemap metadata has invalid image bounds: {metadata_path}"
    if not isinstance(bounds, list) or len(bounds) != 2:
        raise ValueError(error_message)

    validated_bounds: list[list[float]] = []
    for corner in bounds:
        if not isinstance(corner, list) or len(corner) != 2:
            raise ValueError(error_message)
        validated_corner: list[float] = []
        for value in corner:
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
            ):
                raise ValueError(error_message)
            validated_corner.append(float(value))
        validated_bounds.append(validated_corner)

    if not image_path.is_file():
        raise ValueError(f"Basemap image does not exist: {image_path}")
    return validated_bounds


def add_basemap(
    map_view: folium.Map,
    image_path: Path,
    bounds: Sequence[Sequence[float]],
    *,
    class_name: str = "",
) -> None:
    """Add the local Oxford basemap and its OpenStreetMap attribution."""
    ImageOverlay(
        image=str(image_path),
        bounds=bounds,
        name="Local OpenStreetMap basemap",
        interactive=False,
        cross_origin=False,
        zIndex=1,
        className=class_name,
    ).add_to(map_view)
    get_map_figure(map_view).html.add_child(
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
