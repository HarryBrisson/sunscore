"""Citywide sunscore run: fetch DSM+DTM, simulate sun-access, zonal stats.

Pulls a whole-city DSM (surface) and DTM (bare earth) from the ISGS ImageServer at
a coarse resolution that fits one request, simulates summer/winter/annual sun-access
on the surface, keeps only ground/street-level cells (DSM − DTM small), and averages
to ward / community area / zip via a rasterized label grid.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.features import rasterize
from shapely.geometry import shape
from shapely.ops import transform as shapely_transform

from . import solar
from .dsm import DSM_IMAGE_SERVER, FEET_TO_M, UTM16N, export_dsm
from .shadow import sun_access_fraction

REPO_ROOT = Path(__file__).resolve().parent.parent
REFERENCE = REPO_ROOT / "data" / "reference"
RAW = REPO_ROOT / "data" / "raw"
PROCESSED = REPO_ROOT / "data" / "processed"
DTM_IMAGE_SERVER = DSM_IMAGE_SERVER.replace("IL_Cook_DSM_2022", "IL_Cook_DTM_2022")

# Metric -> representative day(s); each day sampled hourly through daylight.
METRIC_DAYS = {
    "summer_solstice": [solar.SUMMER_SOLSTICE],
    "winter_solstice": [solar.WINTER_SOLSTICE],
    "annual": ["2026-01-21", "2026-04-21", "2026-07-21", "2026-10-21"],
}
GROUND_MAX_M = 2.5       # DSM - DTM below this = ground / street level
MAX_SHADOW_M = 600.0     # cap shadow search distance (bounds compute)
MIN_ALTITUDE = 5.0
STEP_MINUTES = 60

GEOGRAPHIES = {
    "ward": ("ward_boundaries.geojson", ("ward_id",), ("display_name",)),
    "community_area": ("community_areas.geojson", ("community_area_id",), ("display_name", "name")),
    "zip": ("zip_boundaries.geojson", ("zip",), ("zip",)),
}


def _first(props, keys):
    for key in keys:
        if props.get(key) not in (None, ""):
            return str(props[key])
    return None


def metric_positions(metric: str) -> list[tuple[float, float]]:
    positions: list[tuple[float, float]] = []
    for day in METRIC_DAYS[metric]:
        positions.extend(
            solar.sun_positions(day, step_minutes=STEP_MINUTES, min_altitude_deg=MIN_ALTITUDE)
        )
    return positions


def fetch_city(cell_m: float) -> tuple[Path, Path]:
    bbox = _city_bbox()
    dsm = export_dsm(bbox, RAW / "city_dsm.tif", image_server=DSM_IMAGE_SERVER, cell_m=cell_m)
    dtm = export_dsm(bbox, RAW / "city_dtm.tif", image_server=DTM_IMAGE_SERVER, cell_m=cell_m)
    return dsm, dtm


def _city_bbox() -> tuple[float, float, float, float]:
    geo = json.loads((REFERENCE / "ward_boundaries.geojson").read_text())
    xs: list[float] = []
    ys: list[float] = []

    def walk(coords):
        if isinstance(coords[0], (int, float)):
            xs.append(coords[0])
            ys.append(coords[1])
        else:
            for child in coords:
                walk(child)

    for feature in geo["features"]:
        walk(feature["geometry"]["coordinates"])
    return min(xs), min(ys), max(xs), max(ys)


def _clean_surface(path: Path) -> np.ndarray:
    with rasterio.open(path) as dataset:
        values = dataset.read(1).astype(np.float64)
        nodata = dataset.nodata
    usable = np.isfinite(values) & (values > -1000)
    if nodata is not None:
        usable &= values != nodata
    ground = np.median(values[usable]) if usable.any() else 0.0
    return np.where(usable, values, ground) * FEET_TO_M


def _label_grid(geojson_path: Path, id_keys, transform, crs, shape_hw) -> tuple[np.ndarray, list[tuple[str, str]]]:
    to_grid = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform
    geo = json.loads(geojson_path.read_text())
    shapes = []
    areas: list[tuple[str, str]] = []
    for index, feature in enumerate(geo["features"], start=1):
        area_id = _first(feature["properties"], id_keys[0])
        if area_id is None:
            continue
        geom = shapely_transform(to_grid, shape(feature["geometry"]))
        shapes.append((geom, index))
        areas.append((area_id, _first(feature["properties"], id_keys[1]) or area_id))
    label = rasterize(shapes, out_shape=shape_hw, transform=transform, fill=0, dtype="int32")
    return label, areas


def write_access_layers(output_dir: Path, access: dict, ground_mask, transform, crs) -> Path:
    """Persist the per-cell sun-access grids as GeoTIFFs (one per metric, NaN off the ground mask) so a
    consumer can re-aggregate them to its OWN polygons without re-running the LiDAR simulation. This is
    sunscore's "fine layer" — the equivalent of the point layers parkability publishes."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    height, width = ground_mask.shape
    for metric, grid in access.items():
        masked = np.where(ground_mask, grid.astype("float32"), np.float32("nan"))
        with rasterio.open(
            output_dir / f"sun_access_{metric}.tif", "w", driver="GTiff",
            height=height, width=width, count=1, dtype="float32",
            crs=crs, transform=transform, nodata=float("nan"), compress="deflate",
        ) as dst:
            dst.write(masked, 1)
    # publish the byop/v1 contract alongside the grids (lazy import avoids a cityrun<->aggregation cycle)
    from .aggregation import AGGREGATION_SPEC
    (output_dir / "aggregation_spec.json").write_text(json.dumps(AGGREGATION_SPEC, indent=2))
    return output_dir


def run(*, cell_m: float = 12.0, output_dir: Path | str = PROCESSED) -> dict:
    dsm_path, dtm_path = fetch_city(cell_m)
    with rasterio.open(dsm_path) as dataset:
        transform = dataset.transform
        crs = dataset.crs
        cell = float(dataset.res[0])
        shape_hw = (dataset.height, dataset.width)
    dsm = _clean_surface(dsm_path)
    dtm = _clean_surface(dtm_path)
    ground_mask = (dsm - dtm) < GROUND_MAX_M

    # Sun-access per metric (engine wants row increasing north -> flip in and out).
    dsm_north_up = np.flipud(dsm)
    access = {}
    for metric in METRIC_DAYS:
        acc = sun_access_fraction(dsm_north_up, cell, metric_positions(metric), max_shadow_m=MAX_SHADOW_M)
        access[metric] = np.flipud(acc)  # back to native (transform) orientation

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    # Publish the per-cell grids so consumers can bring their own polygons (see sunscore/aggregation.py).
    write_access_layers(output_dir / "layers", access, ground_mask, transform, crs)
    summaries = {}
    for geo_key, (filename, id_keys, name_keys) in GEOGRAPHIES.items():
        label, areas = _label_grid(REFERENCE / filename, (id_keys, name_keys), transform, crs, shape_hw)
        rows = []
        for index, (area_id, display_name) in enumerate(areas, start=1):
            cells = (label == index) & ground_mask
            count = int(cells.sum())
            row = {"area_type": geo_key, "area_id": area_id, "display_name": display_name,
                   "ground_cell_count": count}
            for metric in METRIC_DAYS:
                row[f"{metric}_sun_access_pct"] = (
                    round(float(access[metric][cells].mean()) * 100, 2) if count else None
                )
            rows.append(row)
        summaries[geo_key] = rows
        (output_dir / f"{geo_key}_sun_summary.json").write_text(json.dumps(rows, indent=2))

    metadata = {
        "source": "ISGS ArcGIS ImageServer IL_Cook_DSM_2022 / IL_Cook_DTM_2022 (2022 LiDAR)",
        "resolution_m": round(cell, 2),
        "ground_threshold_m": GROUND_MAX_M,
        "max_shadow_m": MAX_SHADOW_M,
        "sun_sampling": {"step_minutes": STEP_MINUTES, "metric_days": METRIC_DAYS,
                          "min_altitude_deg": MIN_ALTITUDE},
        "grid": {"shape": list(shape_hw), "crs": str(crs)},
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))
    return {"summaries": summaries, "metadata": metadata, "access": access, "ground_mask": ground_mask}
