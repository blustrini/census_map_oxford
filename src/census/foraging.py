from __future__ import annotations

import argparse
import json
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
LATITUDE_COLUMN = "latitude"
LONGITUDE_COLUMN = "longitude"
REQUIRED_COLUMNS = {LAYER_COLUMN, LATITUDE_COLUMN, LONGITUDE_COLUMN}

LAYER_COLORS = {
    "Apples and Pears": "#e41a1c",
    "Blackberries": "#377eb8",
    "Cherries, plums, damsons": "#4daf4a",
    "Sloes, blackthorn and hawthorn": "#984ea3",
    "Elder": "#ff7f00",
    "Additions in 2017": "#a65628",
    "Uncategorised": "#666666",
}
FORAGING_SETTING_KEYS = {"alpha", "reveal_radius_meters", "knowledge_scores"}
DEFAULT_ALPHA = 0.75
DEFAULT_REVEAL_RADIUS_METERS = 900


@dataclass(frozen=True)
class ForagingMapSettings:
    alpha: float
    reveal_radius_meters: int
    knowledge_scores: Mapping[str, Mapping[str, float]]


def load_foraging_settings(config_path: Path) -> ForagingMapSettings:
    """Load and validate age/category knowledge scores and reveal styling."""
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

    reveal_radius_meters = config["reveal_radius_meters"]
    if (
        isinstance(reveal_radius_meters, bool)
        or not isinstance(reveal_radius_meters, int)
        or not 100 <= reveal_radius_meters <= 10_000
    ):
        raise ValueError("reveal_radius_meters must be a whole number from 100 to 10000")

    knowledge_scores = config["knowledge_scores"]
    if not isinstance(knowledge_scores, dict) or not knowledge_scores:
        raise ValueError("knowledge_scores must map age brackets to category scores")

    validated_scores: dict[str, dict[str, float]] = {}
    for age_bracket, category_scores in knowledge_scores.items():
        if (
            not isinstance(age_bracket, str)
            or not age_bracket.strip()
            or not isinstance(category_scores, dict)
            or not all(isinstance(layer, str) for layer in category_scores)
        ):
            raise ValueError("Each knowledge_scores entry must be an age bracket mapping")
        missing_layers = LAYER_COLORS.keys() - category_scores.keys()
        unexpected_layers = category_scores.keys() - LAYER_COLORS.keys()
        if missing_layers or unexpected_layers:
            details = []
            if missing_layers:
                details.append(f"missing categories: {sorted(missing_layers)}")
            if unexpected_layers:
                details.append(f"unknown categories: {sorted(unexpected_layers)}")
            raise ValueError(
                f"Invalid categories for age bracket {age_bracket!r} ("
                + "; ".join(details)
                + ")"
            )

        validated_category_scores: dict[str, float] = {}
        for layer, score in category_scores.items():
            if (
                isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not math.isfinite(score)
                or not 0 <= score <= 1
            ):
                raise ValueError(
                    f"knowledge_scores[{age_bracket!r}][{layer!r}] "
                    "must be a number between 0 and 1"
                )
            validated_category_scores[layer] = float(score)
        if not any(validated_category_scores.values()):
            raise ValueError(f"Age bracket {age_bracket!r} needs at least one positive score")
        validated_scores[age_bracket] = validated_category_scores

    return ForagingMapSettings(
        alpha=float(alpha),
        reveal_radius_meters=reveal_radius_meters,
        knowledge_scores=validated_scores,
    )


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

    for column in (LAYER_COLUMN,):
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
    return locations


def _add_reveal_controls(
    map_view: folium.Map,
    color_overlay: folium.raster_layers.ImageOverlay,
    image_bounds: list[list[float]],
    locations_by_category: Mapping[str, list[list[float]]],
    settings: ForagingMapSettings,
    initial_age: str,
) -> None:
    age_brackets = list(settings.knowledge_scores)
    categories = sorted(LAYER_COLORS)
    first_option = "<option value='__all__'>All categories</option>"
    category_options = first_option + "".join(
        f"<option value='{escape(category, quote=True)}'>"
        f"{escape(category)}</option>"
        for category in categories
    )
    age_options = "".join(
        f"<option value='{escape(age, quote=True)}'>{escape(age)}</option>"
        for age in age_brackets
    )
    map_view.get_root().html.add_child(
        folium.Element(
            "<div style='position:fixed;top:16px;right:16px;z-index:9999;"
            "background:rgba(255,255,255,.96);padding:10px 12px;border-radius:4px;"
            "box-shadow:0 1px 5px #888;font:13px/1.6 sans-serif;'>"
            "<label>Age bracket<br><select id='foraging-age' style='width:190px;'>"
            f"{age_options}</select></label><br>"
            "<label>Plant category<br><select id='foraging-category' "
            f"style='width:190px;'>{category_options}</select></label></div>"
        )
    )
    map_view.get_root().html.add_child(
        folium.Element(
            "<div style='position:fixed;bottom:24px;right:10px;z-index:9999;"
            "background:rgba(255,255,255,.95);padding:8px 10px;border-radius:4px;"
            "box-shadow:0 1px 5px #888;font:12px/1.4 sans-serif;width:230px;'>"
            "<strong>Colour reveal</strong>"
            "<div style='height:14px;margin:6px 0 2px;background:linear-gradient("
            "to right,#bdbdbd 0%,#f2f2f2 45%,#dce9d3 55%,#438e55 100%);'></div>"
            "<div style='display:flex;justify-content:space-between;'>"
            "<span>Grayscale</span><span>Full colour</span></div>"
            "<div style='color:#555;margin-top:4px;'>Colour appears near foraging "
            "locations and fades with distance.</div>"
            "<div style='color:#555;'>Scores are illustrative placeholders.</div></div>"
        )
    )

    locations_json = json.dumps(
        locations_by_category,
        ensure_ascii=True,
        separators=(",", ":"),
    )
    scores_json = json.dumps(
        {age: dict(scores) for age, scores in settings.knowledge_scores.items()},
        ensure_ascii=True,
        separators=(",", ":"),
    )
    script = f"""
    window.addEventListener('load', function() {{
    const locationsByCategory = {locations_json};
    const knowledgeScores = {scores_json};
    const foragingMap = {map_view.get_name()};
    const colorOverlay = {color_overlay.get_name()};
    const imageBounds = {json.dumps(image_bounds)};
    const revealRadiusMeters = {settings.reveal_radius_meters};
    const revealAlpha = {settings.alpha};
    const foragingAgeSelect = document.getElementById('foraging-age');
    const foragingCategorySelect = document.getElementById('foraging-category');
    foragingAgeSelect.value = {json.dumps(initial_age)};
    const revealCanvas = document.createElement('canvas');
    const revealMask = document.createElement('canvas');
    revealCanvas.style.position = 'absolute';
    revealCanvas.style.pointerEvents = 'none';
    revealCanvas.style.zIndex = '3';
    foragingMap.getPanes().overlayPane.appendChild(revealCanvas);

    function drawReveal() {{
        const colorImage = colorOverlay._image;
        if (!colorImage || !colorImage.complete || !colorImage.naturalWidth) return;
        const size = foragingMap.getSize();
        const pixelRatio = window.devicePixelRatio || 1;
        for (const canvas of [revealCanvas, revealMask]) {{
            canvas.width = Math.round(size.x * pixelRatio);
            canvas.height = Math.round(size.y * pixelRatio);
            canvas.style.width = size.x + 'px';
            canvas.style.height = size.y + 'px';
        }}
        const origin = foragingMap.containerPointToLayerPoint([0, 0]);
        L.DomUtil.setPosition(revealCanvas, origin);
        const ctx = revealCanvas.getContext('2d');
        const mask = revealMask.getContext('2d');
        ctx.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
        mask.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
        ctx.clearRect(0, 0, size.x, size.y);
        mask.clearRect(0, 0, size.x, size.y);

        const [[south, west], [north, east]] = imageBounds;
        const upperLeft = foragingMap.latLngToLayerPoint([north, west]);
        const lowerRight = foragingMap.latLngToLayerPoint([south, east]);
        ctx.drawImage(
            colorImage,
            upperLeft.x - origin.x,
            upperLeft.y - origin.y,
            lowerRight.x - upperLeft.x,
            lowerRight.y - upperLeft.y
        );

        const age = foragingAgeSelect.value;
        const category = foragingCategorySelect.value;
        const selectedCategories = category === '__all__'
            ? Object.keys(locationsByCategory)
            : [category];
        const points = selectedCategories.flatMap((layer) =>
            locationsByCategory[layer].map(([latitude, longitude]) => [
                latitude,
                longitude,
                knowledgeScores[age][layer]
            ])
        );
        for (const [latitude, longitude, score] of points) {{
            const point = foragingMap.latLngToLayerPoint([latitude, longitude]);
            const x = point.x - origin.x;
            const y = point.y - origin.y;
            const metresPerPixel = Math.cos(latitude * Math.PI / 180)
                * 2 * Math.PI * 6378137 / (256 * Math.pow(2, foragingMap.getZoom()));
            const radius = revealRadiusMeters / metresPerPixel;
            const opacity = Math.min(1, revealAlpha * score);
            if (opacity <= 0 || radius <= 0) continue;
            const gradient = mask.createRadialGradient(x, y, 0, x, y, radius);
            gradient.addColorStop(0, 'rgba(255,255,255,' + opacity + ')');
            gradient.addColorStop(0.65, 'rgba(255,255,255,' + opacity * 0.55 + ')');
            gradient.addColorStop(1, 'rgba(255,255,255,0)');
            mask.fillStyle = gradient;
            mask.fillRect(x - radius, y - radius, radius * 2, radius * 2);
        }}
        ctx.globalCompositeOperation = 'destination-in';
        ctx.drawImage(
            revealMask,
            0, 0, revealMask.width, revealMask.height,
            0, 0, size.x, size.y
        );
        ctx.globalCompositeOperation = 'source-over';
    }}

    function updateReveal() {{
        drawReveal();
    }}
    foragingMap.on('movestart zoomstart', function() {{
        revealCanvas.style.opacity = '0';
    }});
    foragingMap.on('moveend zoomend', function() {{
        drawReveal();
        revealCanvas.style.opacity = '1';
    }});
    if (colorOverlay._image && colorOverlay._image.complete) {{
        updateReveal();
    }} else {{
        colorOverlay.once('load', updateReveal);
    }}
    foragingMap.on('resize', drawReveal);
    window.addEventListener('resize', drawReveal);
    foragingAgeSelect.addEventListener('change', updateReveal);
    foragingCategorySelect.addEventListener('change', updateReveal);
    }});
    """
    map_view.get_root().script.add_child(folium.Element(script))


def _load_color_basemap_path(
    metadata_path: Path,
    grayscale_path: Path,
    configured_path: Path | None,
) -> Path:
    if configured_path is not None:
        color_path = configured_path
    else:
        with metadata_path.open(encoding="utf-8") as metadata_file:
            metadata = json.load(metadata_file)
        color_name = metadata.get("color_image") if isinstance(metadata, dict) else None
        if color_name is not None and not isinstance(color_name, str):
            raise ValueError(f"Basemap metadata has invalid color_image: {metadata_path}")
        if color_name:
            color_path = metadata_path.parent / color_name
        else:
            color_path = grayscale_path.with_name(
                f"{grayscale_path.stem}_color{grayscale_path.suffix}"
            )
    if not color_path.is_file():
        raise ValueError(f"Colour basemap image does not exist: {color_path}")
    return color_path


def create_foraging_map(
    foraging_data_path: Path,
    output_path: Path,
    basemap_image_path: Path,
    basemap_metadata_path: Path,
    settings: ForagingMapSettings | None = None,
    color_basemap_image_path: Path | None = None,
) -> tuple[int, int]:
    """Reveal colour around configured foraging locations; return plotted/excluded counts."""
    if settings is None:
        settings = ForagingMapSettings(
            alpha=DEFAULT_ALPHA,
            reveal_radius_meters=DEFAULT_REVEAL_RADIUS_METERS,
            knowledge_scores={
                "All ages": {layer: 1.0 for layer in LAYER_COLORS}
            },
        )
    locations = load_foraging_locations(foraging_data_path)
    image_bounds = load_basemap_bounds(basemap_metadata_path, basemap_image_path)
    color_image_path = _load_color_basemap_path(
        basemap_metadata_path,
        basemap_image_path,
        color_basemap_image_path,
    )
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
    color_overlay = folium.raster_layers.ImageOverlay(
        image=str(color_image_path),
        bounds=image_bounds,
        name="Colour basemap revealed near foraging locations",
        interactive=False,
        cross_origin=False,
        opacity=0,
        zIndex=2,
    ).add_to(map_view)

    locations_by_category: dict[str, list[list[float]]] = {}
    for category in LAYER_COLORS:
        category_locations = in_bounds.loc[in_bounds[LAYER_COLUMN] == category]
        locations_by_category[category] = [
            [float(location[LATITUDE_COLUMN]), float(location[LONGITUDE_COLUMN])]
            for _, location in category_locations.iterrows()
        ]

    age_brackets = list(settings.knowledge_scores)
    _add_reveal_controls(
        map_view,
        color_overlay,
        image_bounds,
        locations_by_category,
        settings,
        age_brackets[-1],
    )
    title = folium.Element(
        "<div style='position: fixed; top: 16px; left: 60px; z-index: 9999; "
        "background: white; padding: 10px 14px; border-radius: 4px; "
        "box-shadow: 0 1px 5px #888; font: 16px/1.4 sans-serif;'>"
        f"<strong>Oxford comes alive</strong><br>{len(in_bounds)} foraging locations</div>"
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
        "--color-basemap-image",
        type=Path,
        help="Path to the full-colour basemap PNG (defaults to metadata/configured sibling)",
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
            args.color_basemap_image,
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))

    message = f"Saved {args.output} with {plotted_count} foraging locations"
    if excluded_count:
        message += f" ({excluded_count} outside the basemap bounds omitted)"
    print(message + ".")


if __name__ == "__main__":
    main()
