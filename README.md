# Oxford MSOA Age Map

Generate an interactive map of the **number** of Oxford residents in an age range
in each Middle layer Super Output Area (MSOA). The map uses an absolute-count
choropleth, not percentages. It shows MSOA-level aggregates, not individual
addresses or a smoothed point heatmap.

## Generate the map

From the project root, run:

```bash
uv run census
```

This reads `data/age_data_oxford.csv` and `data/msoa_boundaries_2021.geojson`
and writes `outputs/oxford_map.html`. Open that HTML file in a browser.
Type the minimum and maximum ages into the map's **From** and **to** boxes,
then click **Apply** (or press Enter). Both ages are included; 100 represents
the 100-and-over category. Counts, colours, tooltips, and the legend update in
the browser without rerunning the command. The YAML cutoffs below select the
initial range only; all ages are embedded in the page.
The map uses a locally rendered grayscale basemap image under the data polygons;
it does not request background tiles from OpenStreetMap's tile servers.
The map settings are loaded and validated from `config.yaml` every run. For
example, to select residents aged over 65, use:

```yaml
transparency: 0.32
cutoff_age_lo: 65
cutoff_age_hi: null
```

`transparency` must be between `0` (opaque) and `1` (invisible).
`cutoff_age_lo` and `cutoff_age_hi` must each be a whole age from 0 through 99,
or `null` for no bound. Both cutoffs are strict: a lower cutoff of 65 includes
ages 66 and above, and an upper cutoff of 80 excludes age 80. Both may be
`null` to include all ages. Use `--config` to load a different YAML file.

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
uv run foraging --mode blend
uv run foraging --mode circles --output outputs/oxford_foraging_circles.html
```

This reads `data/oxford_foraging.csv` and writes
`outputs/oxford_foraging_map.html`. It layers matching grayscale and colour
versions of the basemap. The colour version is revealed around locations in
the selected age bracket and category, fading back to grayscale with distance;
overlapping areas reveal more colour. A location outside the shared basemap
bounds is omitted and reported (the source currently contains one such
coordinate).

`--mode blend` is the default and preserves the grayscale/colour blend.
`--mode circles` instead draws category-coloured circles on the grayscale map,
fading to transparent at the edge. Their radius is `min_radius_meters + score ×
(max_radius_meters - min_radius_meters)`: zero knowledge hides a circle and a
score of one gives the maximum radius. Both
modes retain the age-bracket and category selectors; circle mode does not need
the colour basemap image.

The default styling uses muted orchard green, blackberry mauve, dusty rose,
slate teal, elder gold and sage. Low circle opacity (`0.45`) and a
maximum radius of `840` metres let nearby locations merge into soft washes,
rather than bright discs. Both modes use a quiet, warm basemap and start at the
first configured age bracket; selecting a more knowledgeable bracket brings
more of the city to life. Knowledge scores are left independent of styling.

Reveal settings are loaded from `foraging_config.yaml`. `knowledge_scores`
contains a 0-to-1 value for every age-bracket/category pair; `alpha` sets the
maximum reveal strength, and `reveal_radius_meters` controls how far colour
spreads from each location. The checked-in scores are illustrative
placeholders, deliberately set so older brackets score higher across all
categories. They are not survey findings and should be replaced with collected
results. Pass `--config` to use another YAML file. Input and output paths can
be changed with `--foraging-data`, `--output`, and `--color-basemap-image`;
the grayscale image and metadata options are shared with the age map.

### Changing foraging layers

Layer names come from `knowledge_scores` in `foraging_config.yaml`, not a
hard-coded Python list. To rename, add or remove a layer, update its entry in
every age bracket and use the same name in the CSV's `layer` column. Update
any matching `circles.category_colors` entry too; colours are optional and
omitted entries receive a default palette colour. No Python changes are needed.
All age brackets must contain the same layers; CSV layers missing from the
configuration produce an error. Configured layers with no locations are allowed.

The configuration is prepared for `edible apples`, `edible stone fruits`,
`blackberries`, `elder trees`, `nettles`, `wild garlic`, `edible mushrooms`, and
`uncategorised`. The CSV is intentionally
unchanged here: use the relayered CSV from the data branch before running the
default command.

### Styling the blend without code

Edit the commented `blend` section in `foraging_config.yaml`, then regenerate:

```bash
uv run foraging --mode blend --config foraging_config.yaml --output outputs/oxford_foraging_map.html
```

Refresh the HTML to see changes; no basemap rebuild is needed.

| Setting under `blend` | What to tweak |
| --- | --- |
| `radius_meters` | Reveal radius in metres (1–10000), default 1400. Knowledge affects opacity, not radius. |
| `opacity` | Maximum centre reveal strength (0–1), multiplied by the knowledge score. Default 0.45; overlapping locations build up colour. |
| `fade_steepness` | 0.1–20, default 2. Higher values fade faster; 1 is linear; below 1 gives fuller patches with more defined edges. |
| `solid_core` | Fraction of radius held at the centre reveal strength before fading (0–0.99). Default 0; try 0.25 for a broader centre. |
| `saturation` | Revealed colour intensity (0–3): 0 is grayscale, 1 unchanged, above 1 more vivid. Default 0.75. |
| `brightness` | Revealed brightness (0–3): below 1 darker, above 1 lighter. Default 1.03. |
| `contrast` | Revealed contrast (0–3): below 1 gentler, above 1 stronger. Default 0.92. |

Try opacity 0.25 and steepness 3 for subtle washes, or opacity 0.7,
steepness 1 and saturation 1.2 for stronger colour. These adjustments affect
the revealed image, not the underlying grayscale map. Colours come from the
basemap itself; category colours apply only to circles.

All `blend` settings are optional. `blend.opacity` and `blend.radius_meters`
override top-level `alpha` and `reveal_radius_meters` respectively; omitted
values fall back to those legacy settings. Keep the top-level settings for
backward compatibility. Invalid values and unknown settings produce errors.
The default fade is now a smooth power curve approximating the original fade.

### Styling circles without code

Edit the commented `circles` section in `foraging_config.yaml`, then run:

```bash
uv run foraging --mode circles --config foraging_config.yaml --output outputs/oxford_foraging_circles.html
```

Open or refresh the output HTML to see your changes. No basemap rebuild is needed.

| Setting under `circles` | What to tweak |
| --- | --- |
| `category_colors` | Map category names to quoted six-digit hex colours, e.g. `Blackberries: "#80718c"`. Use a colour picker; omitted categories keep their defaults. |
| `min_radius_meters`, `max_radius_meters` | Smallest and largest radii, in metres (0–10000; maximum must be positive). Equal values give uniform circle sizes. |
| `opacity` | Centre opacity from 0 (invisible) to 1 (opaque). Try 0.2 for lighter overlapping washes. |
| `fade_steepness` | 0.1–20, default 3. Higher values fade faster, giving softer, smaller-looking washes; 1 fades linearly; below 1 gives fuller discs. |
| `solid_core` | Fraction of radius held at full configured opacity before fading, from 0 to 0.99. Try 0.25 for a more defined centre. |

All circle settings are optional; existing YAML files still work. The legend
uses your chosen palette and radius range. `alpha` and `reveal_radius_meters`
affect **blend mode only**; knowledge scores affect both modes. Invalid values,
misspelled settings and unknown categories produce a configuration error.

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
uv run python -m unittest discover -s tests
```

## Code layout

The two map commands are peers. Neither is implemented in the package's
`__init__.py`, and neither imports the other:

```text
scripts/build_basemap.py   Standalone download/clip/render pipeline
src/census/
    __init__.py           Package description only; no entrypoint or re-exports
    age.py                Age settings, census aggregation, choropleth, and main()
    foraging.py           Foraging settings, locations, colour reveal, and main()
    cli.py                Shared basemap arguments and checkout-relative defaults
    config.py             Shared YAML loading and configuration-key validation
    map_utils.py          Shared basemap bounds, image overlay, and attribution
tests/                    Unit tests and small map-generation integration tests
```

`pyproject.toml` connects `census` to `census.age:main` and
`census-foraging` to `census.foraging:main`. You can also run them as
`uv run python -m census.age` and `uv run python -m census.foraging`.
The existing `census` command name is kept for convenience, not because the
age map is the default implementation of the package.

Within each map module, configuration and data validation come first, rendering
comes next, and the thin `main(argv=None)` at the bottom handles command-line
arguments and reporting. Python callers can import the rendering functions
directly from `census.age` or `census.foraging`, without running a command.
Old imports from the package root should instead use `census.age`.

Keep map-specific logic in its own module; extract helpers only when they are
actually shared. For a third map, add a sibling module and a script entry in
`pyproject.toml`, reusing the shared helpers where appropriate. The commands
default to the assets and data in this source checkout; all input/output paths
can be overridden. The basemap build remains standalone because it prepares
assets rather than generating one of the interactive maps.
