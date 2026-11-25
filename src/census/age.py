"""Age-population choropleth: settings, census data preparation, and command."""

from __future__ import annotations

import argparse
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import folium
import geopandas as gpd
import pandas as pd
from branca.element import MacroElement, Template
from folium import LinearColormap

from census.cli import PROJECT_ROOT, add_basemap_arguments
from census.config import load_config
from census.map_utils import add_basemap, load_basemap_bounds

AGE_CODE_COLUMN = "Age (101 categories) Code"
AREA_CODE_COLUMN = "Middle layer Super Output Areas Code"
AREA_NAME_COLUMN = "Middle layer Super Output Areas"
OBSERVATION_COLUMN = "Observation"
MSOA_BOUNDARY_CODE_COLUMNS = ("MSOA11CD", "MSOA21CD")
MSOA_BOUNDARY_NAME_COLUMNS = ("MSOA11NM", "MSOA21NM")
SETTING_KEYS = {"transparency", "cutoff_age_hi", "cutoff_age_lo"}

DERIVED_COL_NAME = "age_range_population"

AGE_CONTROLS_TEMPLATE = """
{% macro script(this, kwargs) %}
(function () {
    const map = {{ this._parent.get_name() }};
    const polygons = {{ this.layer_name }};
    const initialStyle = polygons.options.style;
    const control = L.control({position: 'topleft'});
    control.onAdd = function () {
        const panel = L.DomUtil.create('div');
        panel.style.cssText = 'background:white;padding:12px;border-radius:4px;' +
            'box-shadow:0 1px 5px #888;font:14px/1.5 sans-serif;max-width:270px';
        panel.innerHTML = `<strong>Oxford residents by age</strong>
            <form>
              <label>From <input name="minimum" aria-label="Minimum age" type="number"
                min="0" max="100" step="1" required style="width:65px"></label>
              <label>to <input name="maximum" aria-label="Maximum age" type="number"
                min="0" max="100" step="1" required style="width:65px"></label>
              <button type="submit">Apply</button>
            </form>
            <small>Both ages included. 100 means 100+.</small>
            <div data-error role="alert" style="color:#a00"></div>
            <div data-summary aria-live="polite"></div>
            <div data-legend></div>`;
        L.DomEvent.disableClickPropagation(panel);
        L.DomEvent.disableScrollPropagation(panel);
        return panel;
    };
    control.addTo(map);
    const panel = control.getContainer();
    const form = panel.querySelector('form');
    form.elements.minimum.value = {{ this.lower }};
    form.elements.maximum.value = {{ this.upper }};
    const colors = ['#ffffcc', '#c2e699', '#78c679', '#238443', '#006837'];
    function color(value, minimum, maximum) {
        const position = maximum === minimum ? 2 : 4 * (value - minimum) / (maximum - minimum);
        const index = Math.min(3, Math.floor(position));
        const fraction = position - index;
        const a = colors[index], b = colors[index + 1];
        return '#' + [1, 3, 5].map(offset => Math.round(
            parseInt(a.slice(offset, offset + 2), 16) * (1 - fraction) +
            parseInt(b.slice(offset, offset + 2), 16) * fraction
        ).toString(16).padStart(2, '0')).join('');
    }
    function update(event) {
        if (event) event.preventDefault();
        const lower = form.elements.minimum.valueAsNumber;
        const upper = form.elements.maximum.valueAsNumber;
        const error = panel.querySelector('[data-error]');
        if (!form.checkValidity() || lower > upper) {
            error.textContent = 'Enter whole ages from 0 to 100, with From no greater than To.';
            return;
        }
        error.textContent = '';
        const layers = polygons.getLayers();
        const counts = layers.map(layer => layer.feature.properties.age_counts
            .slice(lower, upper + 1).reduce((sum, count) => sum + count, 0));
        const minimum = Math.min(...counts), maximum = Math.max(...counts);
        const description = `${lower}–${upper === 100 ? '100+' : upper}`;
        layers.forEach((layer, index) => {
            layer.feature.properties.age_range_population = counts[index];
            // Update Folium's base style too, so mouseout preserves the new colour.
            const style = {...initialStyle(layer.feature),
                fillColor: color(counts[index], minimum, maximum)};
            layer.options = {...layer.options, ...style};
            layer.setStyle(style);
            const tooltip = document.createElement('div');
            tooltip.textContent = `${layer.feature.properties['Middle layer Super Output Areas']}: ` +
                `${counts[index].toLocaleString()} residents aged ${description}`;
            layer.unbindTooltip();
            layer.bindTooltip(tooltip, {sticky: false});
        });
        // Leaflet resetStyle uses this callback when the hover highlight ends.
        polygons.options.style = layer => ({...initialStyle(layer),
            fillColor: color(layer.properties.age_range_population, minimum, maximum)});
        panel.querySelector('[data-summary]').textContent =
            `${counts.reduce((sum, count) => sum + count, 0).toLocaleString()} people ` +
            `aged ${description} across ${layers.length} MSOAs`;
        const legend = panel.querySelector('[data-legend]');
        legend.innerHTML = '<div style="height:10px;margin-top:8px;background:linear-gradient(to right,' +
            colors.join(',') + ')"></div>';
        const labels = document.createElement('div');
        labels.textContent = `${minimum.toLocaleString()} – ${maximum.toLocaleString()} people per MSOA`;
        legend.appendChild(labels);
    }
    form.addEventListener('submit', update);
    update();
})();
{% endmacro %}
"""


@dataclass(frozen=True)
class MapSettings:
    transparency: float
    cutoff_age_lo: int | None
    cutoff_age_hi: int | None


def load_settings(config_path: Path) -> MapSettings:
    """Load map settings from YAML and validate values before map generation."""
    config = load_config(config_path, SETTING_KEYS)

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
        raise TypeError("cutoff_age must be a whole number between 0 and 99")
    if isinstance(cutoff_age_hi, bool) or not isinstance(cutoff_age_hi, (int, type(None))):
        raise TypeError("cutoff_age must be a whole number between 0 and 99")

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
    """Return Oxford MSOA counts strictly inside the optional age cutoffs."""
    age_data = load_age_data(age_data_path)
    return aggregate_age_data(age_data, cutoff_age_lo, cutoff_age_hi)


def load_age_data(age_data_path: Path) -> pd.DataFrame:
    """Load and validate all single-year counts for browser-side filtering."""
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

    return age_data


def aggregate_age_data(
    age_data: pd.DataFrame,
    cutoff_age_lo: int | None,
    cutoff_age_hi: int | None,
) -> pd.DataFrame:
    """Aggregate already validated data using the configured exclusive bounds."""

    if cutoff_age_hi is None and cutoff_age_lo is None:
        age_data_filt = age_data
    elif cutoff_age_hi is None:
        age_data_filt = age_data.loc[age_data[AGE_CODE_COLUMN] > cutoff_age_lo]
    elif cutoff_age_lo is None:
        age_data_filt = age_data.loc[age_data[AGE_CODE_COLUMN] < cutoff_age_hi]
    else:
        age_data_filt = age_data.loc[
            (age_data[AGE_CODE_COLUMN] < cutoff_age_hi)
            & (age_data[AGE_CODE_COLUMN] > cutoff_age_lo)
        ]

    older_population = (
        age_data_filt.groupby(AREA_CODE_COLUMN, as_index=False)[[OBSERVATION_COLUMN]]
        .sum()
        .rename(columns={OBSERVATION_COLUMN: DERIVED_COL_NAME})
    )
    area_names = age_data[[AREA_CODE_COLUMN, AREA_NAME_COLUMN]].drop_duplicates()
    result = area_names.merge(
        older_population, on=AREA_CODE_COLUMN, how="left", validate="one_to_one"
    )
    result[DERIVED_COL_NAME] = result[DERIVED_COL_NAME].fillna(0).astype(int)
    return result


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


def describe_age_range(settings: MapSettings) -> str:
    """Describe the exclusive age bounds for labels and command output."""
    if settings.cutoff_age_hi is None and settings.cutoff_age_lo is None:
        return "0 and above"
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
    age_data = load_age_data(age_data_path)
    counts = aggregate_age_data(
        age_data, settings.cutoff_age_lo, settings.cutoff_age_hi
    )
    oxford = match_oxford_boundaries(boundaries_path, counts)
    age_counts = age_data.sort_values(AGE_CODE_COLUMN).groupby(AREA_CODE_COLUMN)[
        OBSERVATION_COLUMN
    ].apply(lambda values: [int(value) for value in values])
    oxford["age_counts"] = oxford[AREA_CODE_COLUMN].map(age_counts)
    if oxford.empty:
        raise ValueError("No Oxford MSOA boundaries matched the age data")

    image_bounds = load_basemap_bounds(basemap_metadata_path, basemap_image_path)

    minimum = int(oxford[DERIVED_COL_NAME].min())
    maximum = int(oxford[DERIVED_COL_NAME].max())

    age_str = describe_age_range(settings)
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
    add_basemap(map_view, basemap_image_path, image_bounds)

    polygons = folium.GeoJson(
        oxford.to_json(),
        name=f"Residents aged {age_str}",
        style_function=style_feature,
        highlight_function=lambda _: {"weight": 3, "color": "#333333"},
    ).add_to(map_view)
    controls = MacroElement()
    controls.layer_name = polygons.get_name()
    controls.lower = 0 if settings.cutoff_age_lo is None else settings.cutoff_age_lo + 1
    controls.upper = 100 if settings.cutoff_age_hi is None else settings.cutoff_age_hi - 1
    controls._template = Template(AGE_CONTROLS_TEMPLATE)
    map_view.add_child(controls)
    map_view.fit_bounds(image_bounds)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    map_view.save(output_path)
    return len(oxford), int(oxford[DERIVED_COL_NAME].sum())


def main(argv: Sequence[str] | None = None) -> None:
    """Run the age-map command; accept explicit arguments for tests and callers."""
    project_root = PROJECT_ROOT
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
    add_basemap_arguments(parser)
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

    age_str = describe_age_range(settings)

    print(
        f"Saved {args.output} with {area_count} Oxford MSOAs "
        f"and {population_total:,} residents aged {age_str}."
    )


if __name__ == "__main__":
    main()
