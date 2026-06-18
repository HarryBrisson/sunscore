import numpy as np

from sunscore import solar
from sunscore.shadow import lit_mask, sun_access_fraction


def _block_dsm():
    dsm = np.zeros((100, 100))
    dsm[48:52, 48:52] = 20.0  # a 20 m block on flat ground, 1 m cells
    return dsm


def test_shadow_length_matches_geometry():
    # Sun due south at 45°: shadow falls north, length = height / tan(45°) = 20 m.
    lit = lit_mask(_block_dsm(), 1.0, azimuth_deg=180, altitude_deg=45)
    shadow = ~lit
    col = 50
    assert shadow[52:60, col].all()        # just north of block: shadowed
    assert lit[75:80, col].all()           # far north: lit
    assert lit[40:47, col].all()           # south (toward sun): lit
    assert lit[49, 49]                      # block top: lit
    north_rows = [r for r in range(52, 100) if shadow[r, col]]
    assert (max(north_rows) - 51) * 1.0 == 20.0


def test_low_sun_casts_longer_shadow_than_high_sun():
    dsm = _block_dsm()
    high = (~lit_mask(dsm, 1.0, 180, 60)).sum()
    low = (~lit_mask(dsm, 1.0, 180, 20)).sum()
    assert low > high


def test_sun_access_open_ground_beats_shadowed_spot():
    dsm = _block_dsm()
    acc = sun_access_fraction(dsm, 1.0, solar.positions_for_metric("summer_solstice"))
    assert acc[5, 5] > 0.95            # open ground: nearly always sunny
    assert acc[53, 50] < acc[5, 5]     # just north of block: less sun
