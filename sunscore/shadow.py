"""Shadow casting on a DSM raster — the heart of sunscore.

Given a digital surface model (ground + buildings + trees as a height grid) and a
sun position, decide which cells are lit and which are in shadow. A cell is shadowed
if, looking toward the sun, any upwind terrain rises above the sun ray leaving that
cell. Average "lit" over many sun positions → a sun-access fraction per cell.

This is pure geometry (line-of-sight to the sun), not a radiometric model — which is
exactly what "how much direct sun does this spot get" needs, and keeps the repo to a
portable numpy stack instead of a GRASS install.

Grid convention: `dsm[row, col]`, row increases NORTH, col increases EAST, square
cells of `cellsize` metres. (Real rasters are north-DOWN; the loader flips them.)
"""

from __future__ import annotations

import math

import numpy as np


def _shift_filled(array: np.ndarray, drow: int, dcol: int, fill: float) -> np.ndarray:
    """array sampled at (row+drow, col+dcol); out-of-bounds -> fill."""
    out = np.full_like(array, fill)
    r0_src, r1_src = max(0, drow), min(array.shape[0], array.shape[0] + drow)
    c0_src, c1_src = max(0, dcol), min(array.shape[1], array.shape[1] + dcol)
    r0_dst, r1_dst = max(0, -drow), min(array.shape[0], array.shape[0] - drow)
    c0_dst, c1_dst = max(0, -dcol), min(array.shape[1], array.shape[1] - dcol)
    if r0_src < r1_src and c0_src < c1_src:
        out[r0_dst:r1_dst, c0_dst:c1_dst] = array[r0_src:r1_src, c0_src:c1_src]
    return out


def lit_mask(
    dsm: np.ndarray,
    cellsize: float,
    azimuth_deg: float,
    altitude_deg: float,
    *,
    max_shadow_m: float | None = None,
) -> np.ndarray:
    """Boolean grid: True where the cell sees the sun at (azimuth, altitude).

    `max_shadow_m` caps how far upwind we look for shadow-casters — bounds compute
    on large rasters at the cost of truncating the longest low-sun shadows from the
    very tallest structures (a small fraction of cells).
    """
    if altitude_deg <= 0:
        return np.zeros(dsm.shape, dtype=bool)

    az = math.radians(azimuth_deg)
    # Unit horizontal step toward the sun: east = sin(az), north = cos(az).
    # +north means +row, so drow uses cos, dcol uses sin.
    east, north = math.sin(az), math.cos(az)
    tan_alt = math.tan(math.radians(altitude_deg))

    # March outward toward the sun, tracking the tallest height any upwind terrain
    # projects back down to this cell along the ray. If that exceeds the cell, shadow.
    max_height = dsm.shape[0] * cellsize  # a building can't shadow farther than the grid
    if max_shadow_m is not None:
        max_height = min(max_height, max_shadow_m)
    max_steps = int(min(max(dsm.shape), max_height / (tan_alt + 1e-9) / cellsize)) + 1

    projected = np.full(dsm.shape, -np.inf)
    for k in range(1, max_steps + 1):
        drow = int(round(k * north))
        dcol = int(round(k * east))
        if abs(drow) >= dsm.shape[0] and abs(dcol) >= dsm.shape[1]:
            break
        upwind = _shift_filled(dsm, drow, dcol, -np.inf)
        # Height that upwind terrain casts back to the origin cell along the sun ray.
        cast = upwind - (k * cellsize) * tan_alt
        projected = np.maximum(projected, cast)

    return dsm >= projected


def sun_access_fraction(
    dsm: np.ndarray,
    cellsize: float,
    positions: list[tuple[float, float]],
    *,
    max_shadow_m: float | None = None,
) -> np.ndarray:
    """Fraction of sun positions (in [0,1]) where each cell is lit."""
    if not positions:
        return np.zeros(dsm.shape)
    lit_total = np.zeros(dsm.shape, dtype=np.float64)
    for azimuth_deg, altitude_deg in positions:
        lit_total += lit_mask(dsm, cellsize, azimuth_deg, altitude_deg, max_shadow_m=max_shadow_m)
    return lit_total / len(positions)
