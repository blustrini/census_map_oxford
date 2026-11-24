# Oxford MSOA Age Map

Generate an interactive map of the **number** of Oxford residents aged over 65
in each Middle layer Super Output Area (MSOA). The map uses an absolute-count
choropleth, not percentages. It shows MSOA-level aggregates, not individual
addresses or a smoothed point heatmap.

## Generate the map

From the project root, run:

```bash
uv run census
```

This reads `data/age_data_oxford.csv` and `data/msoa_boundaries_2021.geojson`
and writes `outputs/oxford_over_65_map.html`. Open that HTML file in a browser.
The map uses a locally rendered grayscale basemap image under the data polygons;
it does not request background tiles from OpenStreetMap's tile servers.
The map settings are loaded and validated from `config.yaml` every run.

```yaml
transparency: 0.32
cutoff_age_lo: 65
cutoff_age_hi: null
```

`transparency` must be between `0` (opaque) and `1` (invisible). `cutoff_age`
must be a whole age from 0 through 99; it is a strict cutoff, so a value of 65
includes ages 66 and above. Use `--config` to load a different YAML file.

Input and output locations can be overridden:

```bash
uv run census \
  --config config.yaml \
  --age-data data/age_data_oxford.csv \
  --boundaries data/msoa_boundaries_2021.geojson \
  --output outputs/oxford_over_65_map.html
```

The command checks that age data covers codes 0-100 for each Oxford MSOA and
that every MSOA has one matching boundary. It stops with an error if the data
and boundaries do not match rather than drawing an incomplete map.

## Generate the foraging map

Run the separate foraging-map entrypoint:

```bash
uv run census-foraging
```

This reads `data/oxford_foraging.csv` and writes
`outputs/oxford_foraging_map.html`. It layers matching grayscale and colour
versions of the basemap. The colour version is revealed around locations in
the selected age bracket and category, fading back to grayscale with distance;
overlapping areas reveal more colour. A location outside the shared basemap
bounds is omitted and reported (the source currently contains one such
coordinate).

Reveal settings are loaded from `foraging_config.yaml`. `knowledge_scores`
contains a 0-to-1 value for every age-bracket/category pair; `alpha` sets the
maximum reveal strength, and `reveal_radius_meters` controls how far colour
spreads from each location. The checked-in scores are illustrative
placeholders, deliberately set so older brackets score higher across all
categories. They are not survey findings and should be replaced with collected
results. Pass `--config` to use another YAML file. Input and output paths can
be changed with `--foraging-data`, `--output`, and `--color-basemap-image`;
the grayscale image and metadata options are shared with the age map.

## Local basemap

The local background assets are in `assets/oxford_basemap.png` (grayscale),
`assets/oxford_basemap_color.png` (colour), and
`assets/oxford_basemap.json`. They cover Oxford's MSOA footprint plus a 5 km
buffer. To refresh them from Geofabrik's Oxfordshire OpenStreetMap extract, run
(this downloads the latest 49 MB regional extract before clipping):

```bash
uv run python scripts/build_basemap.py
```

The build writes clipped vector features to `assets/oxford_osm.gpkg` for
re-rendering and inspection; that larger intermediate is ignored by Git. The
PNGs and bounds metadata are used by the generated HTML; both images are
embedded in the page. The map credits OpenStreetMap contributors; source data is licensed
under ODbL 1.0. No background tiles are requested externally. Folium still
loads Leaflet and supporting libraries from CDNs, so interactive map controls
require internet access.

## Tests

```bash
uv run --no-sync --locked python -m unittest discover -s tests
```
# census_map_oxford
