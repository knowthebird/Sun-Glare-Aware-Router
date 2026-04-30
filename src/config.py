from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import available_timezones

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    geocoder_provider: str
    geocoder_base_url: str
    reverse_geocoder_base_url: str
    geocoder_min_interval_s: float
    router_provider: str
    router_base_url: str
    router_min_interval_s: float
    routing_profile: str
    user_agent: str
    http_timeout_s: float
    cache_ttl_s: float
    max_alternatives: int
    default_timezone: str
    log_level: str


def _env_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    return float(raw_value) if raw_value is not None else default


def _env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    return int(raw_value) if raw_value is not None else default


def load_settings() -> Settings:
    load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)
    timezone_name = os.getenv("SUNROUTER_DEFAULT_TIMEZONE", "Europe/Madrid")

    return Settings(
        geocoder_provider=os.getenv("SUNROUTER_GEOCODER_PROVIDER", "nominatim").lower(),
        geocoder_base_url=os.getenv(
            "SUNROUTER_GEOCODER_BASE_URL",
            "https://nominatim.openstreetmap.org/search",
        ),
        reverse_geocoder_base_url=os.getenv(
            "SUNROUTER_REVERSE_GEOCODER_BASE_URL",
            "https://nominatim.openstreetmap.org/reverse",
        ),
        geocoder_min_interval_s=_env_float("SUNROUTER_GEOCODER_MIN_INTERVAL_S", 1.0),
        router_provider=os.getenv("SUNROUTER_ROUTER_PROVIDER", "osrm").lower(),
        router_base_url=os.getenv(
            "SUNROUTER_ROUTER_BASE_URL",
            "https://router.project-osrm.org/route/v1",
        ),
        router_min_interval_s=_env_float("SUNROUTER_ROUTER_MIN_INTERVAL_S", 1.0),
        routing_profile=os.getenv("SUNROUTER_ROUTING_PROFILE", "driving"),
        user_agent=os.getenv("SUNROUTER_USER_AGENT", "sun-glare-router-mvp/0.1"),
        http_timeout_s=_env_float("SUNROUTER_HTTP_TIMEOUT_S", 10.0),
        cache_ttl_s=_env_float("SUNROUTER_CACHE_TTL_S", 900.0),
        max_alternatives=_env_int("SUNROUTER_MAX_ALTERNATIVES", 3),
        default_timezone=timezone_name
        if timezone_name in available_timezones()
        else "UTC",
        log_level=os.getenv("SUNROUTER_LOG_LEVEL", "INFO").upper(),
    )


def supported_timezones() -> list[str]:
    return sorted(available_timezones())
