from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZipFile

import geopandas as gpd
import matplotlib
import pyogrio
from matplotlib import patheffects

matplotlib.use("Agg")
import matplotlib.pyplot as plt

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_URL = (
    "https://download.geofabrik.de/europe/united-kingdom/england/"
    "oxfordshire-latest-free.gpkg.zip"
)
BUFFER_METRES = 5_000
RASTER_DPI = 360
TARGET_CRS = "EPSG:27700"
IMAGE_CRS = "EPSG:3857"
LAYERS = (
    "gis_osm_landuse_a_free",
    "gis_osm_natural_a_free",
    "gis_osm_water_a_free",
    "gis_osm_buildings_a_free",
    "gis_osm_roads_free",
    "gis_osm_waterways_free",
    "gis_osm_places_free",
)
GREEN_LANDUSE = {"park", "recreation_ground", "forest", "grass", "meadow", "allotments"}
WATER_CLASSES = {"water", "riverbank", "reservoir", "wetland_marsh"}


def download_extract(destination: Path, source_archive: Path | None) -> tuple[Path, str]:
    if source_archive:
        archive_path = source_archive
    else:
        archive_path = destination / "oxfordshire.gpkg.zip"
        with urlopen(SOURCE_URL, timeout=60) as response, archive_path.open("wb") as archive:
            shutil.copyfileobj(response, archive)

    with ZipFile(archive_path) as archive:
        member = next(
            (name for name in archive.namelist() if name.endswith("oxfordshire.gpkg")),
            None,
        )
        readme = next((name for name in archive.namelist() if name.endswith("README")), None)
        if member is None:
            raise ValueError("Geofabrik archive does not contain oxfordshire.gpkg")
        with archive.open(member) as source, (destination / "source.gpkg").open("wb") as target:
            shutil.copyfileobj(source, target)
        source_date = "unknown"
        if readme:
            with archive.open(readme) as source:
                contents = source.read().decode("utf-8", errors="replace")
            match = re.search(r"as of\s+([0-9T:-]+Z)", contents, flags=re.IGNORECASE)
            if match:
                source_date = match.group(1)
    return destination / "source.gpkg", source_date


def clip_layers(
    source_path: Path, boundary_path: Path, output_path: Path
) -> tuple[
    dict[str, gpd.GeoDataFrame], list[str], list[list[float]], tuple[float, float, float, float]
]:
    boundaries = gpd.read_file(boundary_path)
    name_column = next(
        (column for column in ("MSOA21NM", "MSOA11NM") if column in boundaries), None
    )
    if name_column is None or boundaries.crs is None:
        raise ValueError("Oxford boundary data needs an MSOA name field and a CRS")
    oxford = boundaries.loc[
        boundaries[name_column].astype("string").str.startswith("Oxford ", na=False)
    ].to_crs(TARGET_CRS)
    if oxford.empty:
        raise ValueError("No Oxford MSOA boundaries found")

    buffer_geometry = oxford.geometry.union_all().buffer(BUFFER_METRES)
    mask = gpd.GeoDataFrame(geometry=[buffer_geometry], crs=TARGET_CRS)
    read_bbox = tuple(mask.to_crs("EPSG:4326").total_bounds)
    buffered_3857 = mask.to_crs(IMAGE_CRS)
    min_x, min_y, max_x, max_y = buffered_3857.total_bounds
    image_corners = gpd.GeoSeries(
        gpd.points_from_xy([min_x, max_x], [min_y, max_y]), crs=IMAGE_CRS
    ).to_crs("EPSG:4326")
    west, south = image_corners.iloc[0].x, image_corners.iloc[0].y
    east, north = image_corners.iloc[1].x, image_corners.iloc[1].y
    image_bounds = [[south, west], [north, east]]

    clipped_layers = {}
    written_layers = []
    output_path.unlink(missing_ok=True)
    for layer in LAYERS:
        features = gpd.read_file(source_path, layer=layer, bbox=read_bbox)
        if features.empty:
            continue
        if features.crs is None:
            raise ValueError(f"OSM layer {layer} has no CRS")
        features = features.to_crs(TARGET_CRS)
        features = gpd.clip(features, buffer_geometry, keep_geom_type=True)
        if features.empty:
            continue
        pyogrio.write_dataframe(
            features,
            output_path,
            layer=layer,
            driver="GPKG",
            append=bool(written_layers),
        )
        clipped_layers[layer] = features.to_crs(IMAGE_CRS)
        written_layers.append(layer)
    if not clipped_layers:
        raise ValueError("No OSM features intersect the Oxford buffer")
    return clipped_layers, written_layers, image_bounds, (min_x, min_y, max_x, max_y)


def render_basemap(
    layers: dict[str, gpd.GeoDataFrame],
    image_path: Path,
    image_extent: tuple[float, float, float, float],
) -> None:
    min_x, min_y, max_x, max_y = image_extent
    figure_width = 16
    figure_height = figure_width * (max_y - min_y) / (max_x - min_x)
    figure, axis = plt.subplots(figsize=(figure_width, figure_height), dpi=RASTER_DPI)
    axis.set_facecolor("#f4f3f0")
    figure.patch.set_facecolor("#f4f3f0")

    landuse = layers.get("gis_osm_landuse_a_free")
    if landuse is not None:
        classes = landuse["fclass"].fillna("")
        landuse.loc[classes.isin(GREEN_LANDUSE)].plot(
            ax=axis, color="#e2e7dc", edgecolor="none", zorder=1
        )
        landuse.loc[~classes.isin(GREEN_LANDUSE)].plot(
            ax=axis, color="#f0efec", edgecolor="none", zorder=1
        )
    natural = layers.get("gis_osm_natural_a_free")
    if natural is not None:
        natural.plot(ax=axis, color="#e8e9e4", edgecolor="none", zorder=2)
    buildings = layers.get("gis_osm_buildings_a_free")
    if buildings is not None:
        buildings.plot(ax=axis, color="#e5e3df", edgecolor="none", zorder=3)
    water = layers.get("gis_osm_water_a_free")
    if water is not None:
        water.loc[water["fclass"].isin(WATER_CLASSES)].plot(
            ax=axis, color="#dce5e8", edgecolor="#cad8dc", linewidth=0.2, zorder=4
        )
    roads = layers.get("gis_osm_roads_free")
    if roads is not None:
        for classes, color, width, zorder in (
            (
                {
                    "residential",
                    "unclassified",
                    "service",
                    "living_street",
                    "track",
                    "footway",
                    "cycleway",
                    "path",
                },
                "#ffffff",
                0.30,
                5,
            ),
            ({"tertiary", "tertiary_link", "secondary", "secondary_link"}, "#ffffff", 0.55, 6),
            (
                {
                    "primary",
                    "primary_link",
                    "trunk",
                    "trunk_link",
                    "motorway",
                    "motorway_link",
                },
                "#ffffff",
                0.9,
                7,
            ),
        ):
            roads.loc[roads["fclass"].isin(classes)].plot(
                ax=axis, color=color, linewidth=width, zorder=zorder
            )
    waterways = layers.get("gis_osm_waterways_free")
    if waterways is not None:
        waterways.plot(ax=axis, color="#b9cbd0", linewidth=0.65, zorder=8)
    places = layers.get("gis_osm_places_free")
    if places is not None:
        for _, place in places.loc[places["name"].notna()].iterrows():
            place_class = place.get("fclass", "")
            if place_class not in {"city", "town", "suburb", "village"}:
                continue
            size = 8 if place_class == "city" else 6 if place_class == "town" else 5
            text = axis.annotate(
                str(place["name"]),
                (place.geometry.x, place.geometry.y),
                xytext=(3, 3),
                textcoords="offset points",
                fontsize=size,
                color="#5e5d59",
                zorder=9,
            )
            text.set_path_effects(
                [patheffects.withStroke(linewidth=2, foreground="#f4f3f0")]
            )

    axis.set_xlim(min_x, max_x)
    axis.set_ylim(min_y, max_y)
    axis.set_aspect("equal")
    axis.axis("off")
    figure.subplots_adjust(left=0, right=1, bottom=0, top=1)
    figure.savefig(image_path, dpi=RASTER_DPI, facecolor=figure.get_facecolor())
    plt.close(figure)


def build_basemap(
    boundary_path: Path,
    vector_output: Path,
    image_output: Path,
    source_archive: Path | None = None,
) -> None:
    vector_output.parent.mkdir(parents=True, exist_ok=True)
    image_output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="oxford-basemap-") as temporary_directory:
        temporary_path = Path(temporary_directory)
        source_path, source_date = download_extract(temporary_path, source_archive)
        staged_vector = temporary_path / "oxford_osm.gpkg"
        staged_image = temporary_path / "oxford_basemap.png"
        metadata_path = temporary_path / "oxford_basemap.json"
        layers, layer_names, bounds, image_extent = clip_layers(
            source_path, boundary_path, staged_vector
        )
        render_basemap(layers, staged_image, image_extent)
        metadata_path.write_text(
            json.dumps(
                {
                    "bounds": bounds,
                    "buffer_metres": BUFFER_METRES,
                    "image_crs": IMAGE_CRS,
                    "source": SOURCE_URL,
                    "source_data_date": source_date,
                    "license": "Open Database License (ODbL) 1.0",
                    "attribution": "© OpenStreetMap contributors",
                    "layers": layer_names,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(staged_vector, vector_output)
        os.replace(staged_image, image_output)
        os.replace(metadata_path, image_output.with_suffix(".json"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download, clip, and render a local Oxford OpenStreetMap basemap."
    )
    parser.add_argument(
        "--boundaries",
        type=Path,
        default=PROJECT_ROOT / "data" / "msoa_boundaries_2021.geojson",
    )
    parser.add_argument(
        "--source-archive",
        type=Path,
        help="Use an existing Geofabrik archive instead of downloading the current extract",
    )
    parser.add_argument(
        "--vector-output",
        type=Path,
        default=PROJECT_ROOT / "assets" / "oxford_osm.gpkg",
    )
    parser.add_argument(
        "--image-output",
        type=Path,
        default=PROJECT_ROOT / "assets" / "oxford_basemap.png",
    )
    args = parser.parse_args()
    build_basemap(
        args.boundaries,
        args.vector_output,
        args.image_output,
        args.source_archive,
    )
    print(f"Saved clipped OSM vector layers to {args.vector_output}")
    print(f"Saved raster basemap to {args.image_output}")


if __name__ == "__main__":
    main()
