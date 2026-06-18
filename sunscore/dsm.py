"""Fetch and load Chicago LiDAR surface-model (DSM) tiles.

The ISGS ArcGIS ImageServer exposes the 2022 Cook County DSM (1 m, buildings +
trees) with an `exportImage` REST operation, so we can pull a GeoTIFF for any
bounding box directly — no interactive map, no per-tile manual download.

Two unit gotchas, handled in `load_dsm`:
- The DSM elevation values are in FEET, but we export the grid into a metric
  projection (UTM 16N, metres), so we convert elevation ft -> m for consistent
  shadow geometry.
- Rasterio rows run north -> south (top row = north); the shadow engine wants row
  index increasing northward, so we flip vertically on load.
"""

from __future__ import annotations

import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import rasterio

DSM_IMAGE_SERVER = (
    "https://data.isgs.illinois.edu/arcgis/rest/services/Elevation/"
    "IL_Cook_DSM_2022/ImageServer"
)
UTM16N = 26916  # metres
FEET_TO_M = 0.3048


def export_dsm(
    bbox_wgs84: tuple[float, float, float, float],
    out_path: Path | str,
    *,
    image_server: str = DSM_IMAGE_SERVER,
    image_sr: int = UTM16N,
    cell_m: float = 1.0,
    timeout_seconds: float = 240.0,
) -> Path:
    """Download a DSM GeoTIFF for (min_lng, min_lat, max_lng, max_lat).

    Pixel count is derived from the bbox size and `cell_m` (≈ metres per pixel).
    """
    out_path = Path(out_path)
    if out_path.exists():
        return out_path
    min_lng, min_lat, max_lng, max_lat = bbox_wgs84
    # Rough metre span to size the raster (good enough for the pixel grid request).
    lat_mid = (min_lat + max_lat) / 2.0
    width_m = (max_lng - min_lng) * 111_320 * np.cos(np.radians(lat_mid))
    height_m = (max_lat - min_lat) * 110_540
    cols = max(1, min(4096, round(width_m / cell_m)))
    rows = max(1, min(4096, round(height_m / cell_m)))
    params = urllib.parse.urlencode({
        "bbox": ",".join(str(v) for v in bbox_wgs84),
        "bboxSR": 4326,
        "imageSR": image_sr,
        "size": f"{cols},{rows}",
        "format": "tiff",
        "pixelType": "F32",
        "interpolation": "RSP_BilinearInterpolation",
        "f": "image",
    })
    url = f"{image_server}/exportImage?{params}"
    request = urllib.request.Request(url, headers={"User-Agent": "sunscore/0.1"})
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        out_path.write_bytes(response.read())
    return out_path


def load_dsm(path: Path | str) -> tuple[np.ndarray, float]:
    """Return (dsm_metres_north_up, cell_size_m), cleaned of nodata."""
    with rasterio.open(path) as dataset:
        values = dataset.read(1).astype(np.float64)
        cell = float(dataset.res[0])
        nodata = dataset.nodata
    usable = np.isfinite(values) & (values > -1000)
    if nodata is not None:
        usable &= values != nodata
    ground = np.median(values[usable]) if usable.any() else 0.0
    values = np.where(usable, values, ground) * FEET_TO_M
    return np.flipud(values), cell
