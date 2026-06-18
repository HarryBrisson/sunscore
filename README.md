# sunscore

**Access to sunlight, by Chicago ward / community area / zip — from LiDAR.**

A standalone civic-data metric (sibling to `chainshare` and `parkability`) for
ward-wise-civic-tech / Penlight. We take a LiDAR **digital surface model** (ground +
buildings + trees), **simulate the sun** across the day and seasons, cast shadows, and
measure the share of daylight each place actually receives.

## Metrics (planned)

| metric | meaning | toward "sunnier" |
| --- | --- | --- |
| `summer_solstice_sun_access_pct` | share of daylight in direct sun, Jun 21 | higher |
| `winter_solstice_sun_access_pct` | share of daylight in direct sun, Dec 21 (longest shadows) | higher |
| `annual_sun_access_pct` | yearly average (21st of each month) | higher |

Published per ward, community area, and zip (ward feeds Penlight).

## How it works

- `sunscore/solar.py` — sun azimuth/altitude through each day (via `pvlib`) for the
  solstices and a monthly annual sample.
- `sunscore/shadow.py` — pure-numpy shadow casting on a DSM raster. A cell is shadowed
  if, looking toward the sun, upwind terrain rises above the sun ray leaving it. Average
  "lit" over all sun positions → a sun-access fraction per cell. This is line-of-sight
  geometry (not a radiometric model), which is exactly what "how much direct sun does
  this spot get" needs — and keeps the stack to `numpy + rasterio + pvlib`, no GRASS.

**Validated** on synthetic geometry (`tests/`): a 20 m block under a 45° southern sun
casts an exactly 20 m shadow to the north; lower sun → longer shadow; open ground gets
far more sun than a spot tucked behind a building.

## Status

Proof-of-concept **engine complete and tested**. Next: feed it a real Chicago DSM tile,
then scale citywide (downsampled to ~5–10 m), mask to ground level, and run zonal stats
to the three geographies.

**Data:** 2017 USGS 3DEP Northeast-IL LiDAR (Cook County). DSM GeoTIFF derivatives are
available from the [Illinois ISGS Clearinghouse](https://clearinghouse.isgs.illinois.edu/data/elevation/illinois-height-modernization-ilhmp);
the raw point cloud (first returns → DSM) is on USGS 3DEP. Drop a tile in `data/raw/`.

## Run the tests

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt pytest
python -m pytest
```
