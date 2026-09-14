"""
The Moon's real limb, from the LRO LOLA digital elevation model.

The pages' contact times and limit lines use a mean limb (a 1737.4 km sphere). Grazes
live in the ±1-2 km of mountains and valleys around it: this module gives, for any
observer and any moment, the apparent limb radius as a function of position angle —
the silhouette of the terrain against the sky — so a contact or a graze line can be
computed against the terrain that is actually on the limb for that libration.

Data (ephemeris/lola/, gitignored, from NASA PDS + NAIF, all public domain):
  ldem_64.img (+.lbl)   LOLA GDR, 64 px/deg cylindrical, int16 * 0.5 m above 1737.4 km  (530 MB)
  ldem_16.img           the same at 16 px/deg, for quick work                            (33 MB)
  moon_pa_de421_1900-2050.bpc, pck00010.tpc, moon_080317.tf   lunar orientation (libration) frames

Silhouette: for position angle PA (celestial, N through E), sweep the terrain along the
line of sight within a few degrees of the mean-limb tangent point; the limb is the point
whose projected height (R + h) cos(theta) is largest. Resolution 0.05 deg of PA
(~1.5 km of limb), LDEM_64 gives ~0.5 km horizontally and metres vertically.
"""

import os

import numpy as np
from skyfield.api import PlanetaryConstants, load

HERE = os.path.dirname(os.path.abspath(__file__))
import sys  # noqa: E402
sys.path.insert(0, HERE)
from ephem_paths import DE431, EPHEM_DIR  # noqa: E402

LOLA = os.path.join(EPHEM_DIR, "lola")
R_MOON_KM = 1737.4


class LunarDEM:
    def __init__(self, res=64):
        path = os.path.join(LOLA, f"ldem_{res}.img")
        if not os.path.exists(path) or os.path.getsize(path) != 180 * res * 360 * res * 2:   # missing or still downloading
            res = 16
            path = os.path.join(LOLA, "ldem_16.img")
        self.res = res
        self.nl, self.ns = 180 * res, 360 * res
        self.dn = np.memmap(path, dtype="<i2", mode="r", shape=(self.nl, self.ns))

    def height_km(self, lat_deg, lon_deg):
        """Terrain height above the 1737.4 km sphere, km; nearest sample. lon in [0, 360)."""
        i = np.clip(((90.0 - lat_deg) * self.res).astype(int), 0, self.nl - 1)
        j = (np.mod(lon_deg, 360.0) * self.res).astype(int) % self.ns
        return self.dn[i, j] * 0.5 / 1000.0


class MoonOrientation:
    """Rotation ICRF -> Moon mean-Earth/polar-axis frame (the DEM's frame) at any time."""

    def __init__(self):
        pc = PlanetaryConstants()
        pc.read_text(load(os.path.join(LOLA, "moon_080317.tf")))
        pc.read_text(load(os.path.join(LOLA, "pck00010.tpc")))
        pc.read_binary(load(os.path.join(LOLA, "moon_pa_de421_1900-2050.bpc")))
        self.frame = pc.build_frame_named("MOON_ME_DE421")

    def rotation(self, t):
        return self.frame.rotation_at(t)          # (3,3): v_me = R @ v_icrf


def _unit(v):
    return v / np.linalg.norm(v)


def sky_basis(m_hat):
    """Celestial east and north unit vectors perpendicular to the line of sight m_hat."""
    z = np.array([0.0, 0.0, 1.0])
    east = _unit(np.cross(z, m_hat))
    north = _unit(np.cross(m_hat, east))
    return east, north


def position_angle(m_hat, s_hat):
    """PA of direction s_hat from direction m_hat, degrees N through E."""
    east, north = sky_basis(m_hat)
    d = s_hat - m_hat
    return float(np.degrees(np.arctan2(d @ east, d @ north)) % 360.0)


class Limb:
    def __init__(self, dem=None, orientation=None):
        self.dem = dem or LunarDEM()
        self.orient = orientation or MoonOrientation()

    def sub_observer(self, t, moon_vec_from_observer_km):
        """Selenographic (lat, lon) of the point under the observer, degrees."""
        R = self.orient.rotation(t)
        o = R @ _unit(-moon_vec_from_observer_km)
        return float(np.degrees(np.arcsin(o[2]))), float(np.degrees(np.arctan2(o[1], o[0])) % 360.0)

    def profile(self, t, moon_vec_from_observer_km, pa_deg, half_deg=4.0, step_deg=0.05):
        """Apparent limb radius excess over the mean sphere, km, for each PA (array)."""
        R = self.orient.rotation(t)
        m_hat = _unit(moon_vec_from_observer_km)
        east, north = sky_basis(m_hat)
        pa = np.radians(np.atleast_1d(pa_deg))
        d = np.outer(np.cos(pa), north) + np.outer(np.sin(pa), east)       # (n,3) limb directions
        th = np.radians(np.arange(-half_deg, half_deg + 1e-9, step_deg))     # (k,)
        # p(theta) = cos(theta) d + sin(theta) (-m_hat): toward the observer for theta > 0
        p = np.cos(th)[None, :, None] * d[:, None, :] - np.sin(th)[None, :, None] * m_hat[None, None, :]
        p_me = p @ R.T                                                        # (n,k,3) in the DEM frame
        lat = np.degrees(np.arcsin(np.clip(p_me[..., 2], -1, 1)))
        lon = np.degrees(np.arctan2(p_me[..., 1], p_me[..., 0]))
        h = self.dem.height_km(lat, lon)
        apparent = (R_MOON_KM + h) * np.cos(th)[None, :]
        return apparent.max(axis=1) - R_MOON_KM

    def radius_km(self, t, moon_vec_from_observer_km, pa_deg):
        """Mean radius + profile at one PA — what the contact solver wants."""
        return R_MOON_KM + float(self.profile(t, moon_vec_from_observer_km, [pa_deg])[0])


def face_samples(ts, earth, moon, t_center, half_min=180, step_min=30, orientation=None):
    """For drawing the Moon: geocentric sub-Earth selenographic lat / lon (MOON_ME, east-positive) and the
    sky position angle of the lunar north pole (ICRS north, through east), every step_min around t_center."""
    import math
    orient = orientation or MoonOrientation()
    out = []
    for k in range(-half_min // step_min, half_min // step_min + 1):
        t = ts.tt_jd(t_center.tt + k * step_min / 1440.0)
        R = orient.rotation(t)
        mh = _unit(earth.at(t).observe(moon).apparent().position.km)
        o = R @ (-mh)
        pole = R.T @ np.array([0.0, 0.0, 1.0])
        east = _unit(np.cross([0.0, 0.0, 1.0], mh))
        north = np.cross(mh, east)
        out.append([round(math.degrees(math.asin(o[2])), 3), round((math.degrees(math.atan2(o[1], o[0])) + 180) % 360 - 180, 3),
                    round(math.degrees(math.atan2(pole @ east, pole @ north)), 3)])
    return {"t0_offset_min": -half_min, "step_min": step_min, "samples": out}


if __name__ == "__main__":
    import sys
    from skyfield.api import load_file, wgs84
    ts = load.timescale()
    eph = load_file(DE431)
    earth, moon = eph["earth"], eph["moon"]
    t = ts.utc(2026, 9, 14, 12, 0)
    limb = Limb()
    print("DEM", limb.dem.res, "px/deg")
    m = earth.at(t).observe(moon).apparent().position.km
    lat, lon = limb.sub_observer(t, m)
    print(f"geocentric sub-Earth point: lat {lat:+.2f} lon {lon:.2f}  (libration)")
    pa = np.arange(0, 360, 0.05)
    prof = limb.profile(t, m, pa)
    print(f"profile: mean {prof.mean():+.3f} km, min {prof.min():+.2f} @PA {pa[prof.argmin()]:.1f}, max {prof.max():+.2f} @PA {pa[prof.argmax()]:.1f}")
    for p0 in (0, 45, 90, 135, 180, 225, 270, 315):
        k = int(p0 / 0.05)
        print(f"  PA {p0:3d}: {prof[k]:+.2f} km")
    o = (earth + wgs84.latlon(19.076, 72.8777)).at(t).observe(moon).apparent().position.km
    lat2, lon2 = limb.sub_observer(t, o)
    print(f"Mumbai sub-observer point: lat {lat2:+.2f} lon {lon2:.2f}  (topocentric libration shift {lat2-lat:+.2f}, {lon2-lon:+.2f} deg)")
