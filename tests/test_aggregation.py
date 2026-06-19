"""Bring-your-own-polygons aggregation: zonal-mean the per-cell sun grids over arbitrary polygons."""
from __future__ import annotations

import numpy as np
from pyproj import Transformer
from rasterio.crs import CRS
from rasterio.transform import from_origin

from sunscore.aggregation import AGGREGATION_SPEC, aggregate_to_polygons
from sunscore.cityrun import METRIC_DAYS, write_access_layers


def test_aggregate_to_polygons_zonal_mean(tmp_path):
    # A 2x2 grid at 18 m in UTM 16N; the SE cell is off-ground (excluded from the mean).
    crs = CRS.from_epsg(26916)
    ox, oy, res = 447000.0, 4636000.0, 18.0
    transform = from_origin(ox, oy, res, res)  # north-up: row 0 is the north row
    ground_mask = np.array([[True, True], [True, False]])
    # sun fractions: 0.5, 0.9, 0.1 on ground cells; the off-ground 0.0 is masked to NaN on write
    access = {metric: np.array([[0.5, 0.9], [0.1, 0.0]], dtype="float32") for metric in METRIC_DAYS}
    write_access_layers(tmp_path, access, ground_mask, transform, crs)

    # A polygon covering the whole 2x2 footprint, expressed in WGS84 (what a consumer would pass).
    to_wgs = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform
    corners = [(ox, oy - 2 * res), (ox + 2 * res, oy - 2 * res), (ox + 2 * res, oy), (ox, oy)]
    ring = [list(to_wgs(x, y)) for x, y in corners]
    ring.append(ring[0])
    target = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {"cid": "Z1"}, "geometry": {"type": "Polygon", "coordinates": [ring]}}],
    }

    result = aggregate_to_polygons(target, "cid", layers_dir=tmp_path)

    assert set(result) == {"Z1"}
    cell = result["Z1"]
    assert cell["ground_cell_count"] == 3  # the off-ground cell is excluded
    for metric in METRIC_DAYS:
        # mean of 0.5, 0.9, 0.1 = 0.5 -> 50.0 %
        assert cell[f"{metric}_sun_access_pct"] == 50.0


def test_aggregation_spec_declares_all_metrics_byop():
    expected = {f"{metric}_sun_access_pct" for metric in METRIC_DAYS}
    assert set(AGGREGATION_SPEC["byop_metrics"]) == expected
    assert AGGREGATION_SPEC["fixed_geography_metrics"] == {}
    assert all(spec["combine"] == "area_weighted_mean" for spec in AGGREGATION_SPEC["byop_metrics"].values())
