from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal, Protocol
from zoneinfo import available_timezones

from src.models import LocationPickerState

TimezoneSource = Literal["origin", "browser", "default"]

logger = logging.getLogger("sunrouter.timezones")


class CoordinateTimezoneFinder(Protocol):
    def timezone_at(self, *, lat: float, lng: float) -> str | None: ...


@dataclass(frozen=True)
class ResolvedTimezone:
    name: str
    source: TimezoneSource


@lru_cache(maxsize=1)
def get_coordinate_timezone_finder() -> CoordinateTimezoneFinder:
    from timezonefinder import TimezoneFinder

    return TimezoneFinder()


def is_valid_timezone_name(timezone_name: str | None) -> bool:
    return isinstance(timezone_name, str) and timezone_name in available_timezones()


def infer_timezone_from_origin(
    origin: LocationPickerState,
    finder: CoordinateTimezoneFinder | None = None,
) -> str | None:
    if origin.confirmed_location is None:
        return None

    coordinates = origin.confirmed_location.coordinates
    active_finder = finder if finder is not None else get_coordinate_timezone_finder()
    try:
        timezone_name = active_finder.timezone_at(
            lat=coordinates.lat,
            lng=coordinates.lon,
        )
    except Exception:
        logger.warning(
            "Timezone lookup failed for lat=%.5f lon=%.5f",
            coordinates.lat,
            coordinates.lon,
            exc_info=True,
        )
        return None

    return timezone_name if is_valid_timezone_name(timezone_name) else None


def resolve_automatic_timezone(
    *,
    origin: LocationPickerState | None,
    browser_timezone: str | None,
    configured_default_timezone: str,
    finder: CoordinateTimezoneFinder | None = None,
) -> ResolvedTimezone:
    if origin is not None:
        origin_timezone = infer_timezone_from_origin(origin, finder)
        if origin_timezone is not None:
            return ResolvedTimezone(origin_timezone, "origin")

    if is_valid_timezone_name(browser_timezone):
        return ResolvedTimezone(str(browser_timezone), "browser")

    if is_valid_timezone_name(configured_default_timezone):
        return ResolvedTimezone(configured_default_timezone, "default")

    return ResolvedTimezone("UTC", "default")
