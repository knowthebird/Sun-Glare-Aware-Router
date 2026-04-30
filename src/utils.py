from __future__ import annotations

import logging
import math
from datetime import datetime

from src.models import Coordinates

EARTH_RADIUS_M = 6_371_000.0


class ProviderError(RuntimeError):
    """Raised when a configured upstream provider cannot serve a request."""


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(value, upper))


def calculate_bearing(start: Coordinates, end: Coordinates) -> float:
    lat1 = math.radians(start.lat)
    lat2 = math.radians(end.lat)
    delta_lon = math.radians(end.lon - start.lon)

    y = math.sin(delta_lon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(
        delta_lon
    )
    bearing = (math.degrees(math.atan2(y, x)) + 360.0) % 360.0
    rounded = round(bearing, 6)
    return 0.0 if rounded == 360.0 else rounded


def angular_difference_degrees(angle_a: float, angle_b: float) -> float:
    return abs((angle_a - angle_b + 180.0) % 360.0 - 180.0)


def haversine_distance_m(start: Coordinates, end: Coordinates) -> float:
    lat1 = math.radians(start.lat)
    lat2 = math.radians(end.lat)
    delta_lat = lat2 - lat1
    delta_lon = math.radians(end.lon - start.lon)

    sin_half_lat = math.sin(delta_lat / 2.0)
    sin_half_lon = math.sin(delta_lon / 2.0)
    a = sin_half_lat**2 + math.cos(lat1) * math.cos(lat2) * sin_half_lon**2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_M * c


def midpoint_coordinates(start: Coordinates, end: Coordinates) -> Coordinates:
    return Coordinates(
        lat=(start.lat + end.lat) / 2.0,
        lon=(start.lon + end.lon) / 2.0,
    )


def compass_direction(angle_deg: float) -> str:
    directions = [
        "northbound",
        "northeastbound",
        "eastbound",
        "southeastbound",
        "southbound",
        "southwestbound",
        "westbound",
        "northwestbound",
    ]
    index = int(((angle_deg % 360.0) + 22.5) // 45) % len(directions)
    return directions[index]


def describe_sun_height(elevation_deg: float) -> str:
    if elevation_deg <= 0:
        return "below the horizon"
    if elevation_deg < 10:
        return "very low"
    if elevation_deg < 25:
        return "fairly low"
    return "higher in the sky"


def format_distance_km(distance_m: float) -> str:
    return f"{distance_m / 1000.0:.1f} km"


def format_duration_minutes(duration_s: float) -> str:
    total_minutes = int(round(duration_s / 60.0))
    hours, minutes = divmod(total_minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes} min"


def format_coordinates_label(coordinates: Coordinates) -> str:
    return f"{coordinates.lat:.5f}, {coordinates.lon:.5f}"


def suggest_default_timezone() -> str:
    local_tz = datetime.now().astimezone().tzinfo
    key = getattr(local_tz, "key", None)
    return key if isinstance(key, str) else "UTC"


def configure_logging(level_name: str) -> logging.Logger:
    level = getattr(logging, level_name.upper(), logging.INFO)
    logger = logging.getLogger("sunrouter")
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.propagate = False
    logger.setLevel(level)
    return logger
