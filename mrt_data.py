"""
Taipei MRT station data with coordinates.
Focused on lines relevant to the commute requirements:
  - Bannan Line (板南線) east section: 忠孝新生 → 南港展覽館
  - Songshan-Xindian Line (松山新店線) partial: 松江南京 → 松山
  - Wenhu Line (文湖線): 南京復興 area
"""

from math import radians, cos, sin, asin, sqrt
from typing import Optional

# Each station: (name, line_group, latitude, longitude)
MRT_STATIONS = [
    # ── Bannan Line East (BL14-BL23) ─────────────────────────────
    ("忠孝新生",     "bannan_east", 25.042539, 121.532589),
    ("忠孝復興",     "bannan_east", 25.041730, 121.544273),
    ("忠孝敦化",     "bannan_east", 25.041413, 121.551194),
    ("國父紀念館",   "bannan_east", 25.040301, 121.557640),
    ("市政府",       "bannan_east", 25.040710, 121.564955),
    ("永春",         "bannan_east", 25.040528, 121.574067),
    ("後山埤",       "bannan_east", 25.040003, 121.579559),
    ("昆陽",         "bannan_east", 25.043957, 121.586889),
    ("南港",         "bannan_east", 25.047504, 121.607332),
    ("南港展覽館",   "bannan_east", 25.055358, 121.615178),

    # ── Songshan-Xindian Line partial (G14-G16) ──────────────────
    ("松江南京",     "songshan_partial", 25.052115, 121.532095),
    ("南京三民",     "songshan_partial", 25.051796, 121.550879),
    ("松山",         "songshan_partial", 25.050134, 121.577280),

    # ── Wenhu Line near Nanjing Fuxing (BR12) ────────────────────
    ("南京復興",     "wenhu_nanjing", 25.052046, 121.544300),
]


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in meters between two GPS coordinates."""
    R = 6_371_000  # Earth radius in meters
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return R * 2 * asin(sqrt(a))


def nearest_station(
    lat: float,
    lon: float,
    line_groups: Optional[list[str]] = None,
) -> tuple[str, str, float]:
    """
    Return (station_name, line_group, distance_meters) for the nearest
    relevant MRT station.  If line_groups is None, search all stations.
    """
    candidates = MRT_STATIONS
    if line_groups:
        candidates = [s for s in MRT_STATIONS if s[1] in line_groups]

    best_name, best_line, best_dist = "", "", float("inf")
    for name, line, slat, slon in candidates:
        d = haversine_meters(lat, lon, slat, slon)
        if d < best_dist:
            best_name, best_line, best_dist = name, line, d

    return best_name, best_line, best_dist


def is_within_mrt_distance(
    lat: float,
    lon: float,
    max_meters: int = 800,
    line_groups: Optional[list[str]] = None,
) -> tuple[bool, str, float]:
    """
    Returns (passes, nearest_station_name, distance_meters).
    `passes` is True when the property is within max_meters of a relevant station.
    """
    name, _, dist = nearest_station(lat, lon, line_groups)
    return dist <= max_meters, name, dist
