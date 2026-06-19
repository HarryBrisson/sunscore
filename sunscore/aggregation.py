"""Bring-your-own-polygons aggregation.

sunscore publishes fixed ward / community-area / ZIP sun-access summaries, but the value behind them is
a per-cell grid (direct-sun fraction on every ~18 m ground cell), so it can be re-aggregated to ANY
polygons. A consumer (e.g. ward-wise / Penlight) passes its own cells and gets native per-polygon
sun-access instead of an areal estimate.

Unlike parkability (point counts ÷ area), sunscore's metrics are an **area-weighted mean** of a uniform
grid — every ground cell is equal area, so it's just the mean of the cells whose centroid falls in the
polygon. The fine layer is the set of ``sun_access_<metric>.tif`` rasters that ``cityrun.run()`` /
``write_access_layers`` persist under ``data/processed/layers``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.features import rasterize
from shapely.geometry import shape
from shapely.ops import transform as shapely_transform

from .cityrun import METRIC_DAYS, PROCESSED

LAYERS_DIR = PROCESSED / "layers"
METRICS: tuple[str, ...] = tuple(METRIC_DAYS)  # summer_solstice, winter_solstice, annual

AGGREGATION_SPEC: dict[str, Any] = {
    "contract": "byop/v1",
    "source": "sunscore",
    "source_url": "https://github.com/HarryBrisson/sunscore",
    "layers": {
        f"sun_{metric}": {
            "file": f"sun_access_{metric}.tif",
            "kind": "raster",
            "value": "per-cell direct-sun fraction, NaN off the ground/street-level mask",
        }
        for metric in METRICS
    },
    "metrics": {
        f"{metric}_sun_access_pct": {
            "layer": f"sun_{metric}",
            "combine": "mean",  # uniform grid -> area-weighted mean is the plain mean of in-polygon cells
            "scale": 100,
            "unit": "percent",
        }
        for metric in METRICS
    },
    "fixed_geography_metrics": {},
}


def aggregate_to_polygons(
    target_geojson: dict[str, Any],
    id_field: str,
    name_field: str | None = None,
    *,
    layers_dir: Path = LAYERS_DIR,
) -> dict[str, dict[str, Any]]:
    """Zonal-mean sunscore's per-cell grids over ``target_geojson``'s polygons.

    Returns ``{area_id: {"<metric>_sun_access_pct": value, ..., "ground_cell_count": n}}``. Areas with no
    ground cells are omitted. Requires the ``sun_access_*.tif`` layers to exist (run ``cityrun.run()``
    or ``write_access_layers`` first).
    """
    access: dict[str, np.ndarray] = {}
    transform = crs = shape_hw = None
    for metric in METRICS:
        with rasterio.open(Path(layers_dir) / f"sun_access_{metric}.tif") as dataset:
            access[metric] = dataset.read(1)
            transform, crs, shape_hw = dataset.transform, dataset.crs, dataset.shape
    ground_mask = ~np.isnan(access[METRICS[0]])

    to_grid = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform
    shapes = []
    areas: list[tuple[int, str]] = []
    for index, feature in enumerate(target_geojson.get("features", []), start=1):
        area_id = (feature.get("properties") or {}).get(id_field)
        if area_id is None or not feature.get("geometry"):
            continue
        shapes.append((shapely_transform(to_grid, shape(feature["geometry"])), index))
        areas.append((index, str(area_id)))
    if not shapes:
        return {}

    label = rasterize(shapes, out_shape=shape_hw, transform=transform, fill=0, dtype="int32")
    result: dict[str, dict[str, Any]] = {}
    for index, area_id in areas:
        cells = (label == index) & ground_mask
        count = int(cells.sum())
        if count == 0:
            continue
        row: dict[str, Any] = {
            f"{metric}_sun_access_pct": round(float(access[metric][cells].mean()) * 100, 2)
            for metric in METRICS
        }
        row["ground_cell_count"] = count
        result[area_id] = row
    return result


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Aggregate sunscore sun-access to your own polygons.")
    parser.add_argument("--polygons", type=Path, help="GeoJSON FeatureCollection of target areas")
    parser.add_argument("--id-field", default="area_id", help="property identifying each area")
    parser.add_argument("--name-field", default=None, help="optional display-name property")
    parser.add_argument("--output", type=Path, help="write the {area_id: metrics} JSON here (else stdout)")
    parser.add_argument("--layers-dir", type=Path, default=LAYERS_DIR, help="dir holding sun_access_*.tif")
    args = parser.parse_args(argv)

    if not args.polygons:
        parser.error("pass --polygons (the fine layers are published by `python scripts/run_city.py`)")
    target = json.loads(args.polygons.read_text(encoding="utf-8"))
    result = aggregate_to_polygons(target, args.id_field, args.name_field, layers_dir=args.layers_dir)
    payload = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(payload)
        print(f"wrote {len(result)} areas to {args.output}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
