"""Sun positions over Chicago for the dates sunscore cares about.

We need, for a given day, the sun's azimuth/altitude through the daylight hours,
so the shadow engine can ask "is this spot lit at each of these sun positions?"
and average to a sun-access fraction.

Azimuth convention (from pvlib): degrees clockwise from north — 90=E, 180=S, 270=W.
Altitude here = 90 - apparent_zenith (degrees above the horizon).
"""

from __future__ import annotations

import pandas as pd
import pvlib

CHICAGO_LAT = 41.8781
CHICAGO_LNG = -87.6298
CHICAGO_TZ = "America/Chicago"

# Representative dates. Solstices are the extremes; the annual set samples the
# 21st of each month so the yearly average isn't biased by one season.
SUMMER_SOLSTICE = "2026-06-21"
WINTER_SOLSTICE = "2026-12-21"
ANNUAL_SAMPLE_DATES = tuple(f"2026-{month:02d}-21" for month in range(1, 13))


def sun_positions(
    date: str,
    *,
    lat: float = CHICAGO_LAT,
    lng: float = CHICAGO_LNG,
    tz: str = CHICAGO_TZ,
    step_minutes: int = 30,
    min_altitude_deg: float = 1.0,
) -> list[tuple[float, float]]:
    """Return [(azimuth_deg, altitude_deg)] for daylight moments on `date`."""
    times = pd.date_range(f"{date} 00:00", f"{date} 23:59", freq=f"{step_minutes}min", tz=tz)
    solpos = pvlib.solarposition.get_solarposition(times, lat, lng)
    altitude = 90.0 - solpos["apparent_zenith"]
    lit = altitude > min_altitude_deg
    return list(zip(solpos.loc[lit, "azimuth"].tolist(), altitude[lit].tolist()))


def positions_for_metric(metric: str) -> list[tuple[float, float]]:
    """Sun positions backing each sunscore metric."""
    if metric == "summer_solstice":
        return sun_positions(SUMMER_SOLSTICE)
    if metric == "winter_solstice":
        return sun_positions(WINTER_SOLSTICE)
    if metric == "annual":
        positions: list[tuple[float, float]] = []
        for date in ANNUAL_SAMPLE_DATES:
            positions.extend(sun_positions(date))
        return positions
    raise ValueError(f"Unknown metric: {metric}")
