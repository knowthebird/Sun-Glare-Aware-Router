from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from astral import Observer
from astral.sun import azimuth, elevation

from src.models import Coordinates, SunPosition


def resolve_local_datetime(
    date_value: date, time_value: time, timezone_name: str
) -> datetime:
    local_zone = ZoneInfo(timezone_name)
    return datetime.combine(date_value, time_value, tzinfo=local_zone)


def get_sun_position(moment: datetime, coordinates: Coordinates) -> SunPosition:
    observer = Observer(latitude=coordinates.lat, longitude=coordinates.lon)
    return SunPosition(
        azimuth_deg=float(azimuth(observer, moment)),
        elevation_deg=float(elevation(observer, moment)),
    )
