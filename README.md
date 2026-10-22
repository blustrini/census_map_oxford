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

## Local basemap

The local background assets are in `assets/oxford_basemap.png` and
`assets/oxford_basemap.json`. They cover Oxford's MSOA footprint plus a 5 km
buffer. To refresh them from Geofabrik's Oxfordshire OpenStreetMap extract, run
(this downloads the latest 49 MB regional extract before clipping):

```bash
uv run python scripts/build_basemap.py
```

The build writes clipped vector features to `assets/oxford_osm.gpkg` for
re-rendering and inspection; that larger intermediate is ignored by Git. The
PNG and bounds metadata are used by the generated HTML; the PNG is embedded in
the page. The map credits OpenStreetMap contributors; source data is licensed
under ODbL 1.0. No background tiles are requested externally. Folium still
loads Leaflet and supporting libraries from CDNs, so interactive map controls
require internet access.

## Tests

```bash
uv run --no-sync --locked python -m unittest discover -s tests
```
# census_map_oxford
