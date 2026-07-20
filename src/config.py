from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import available_timezones

from dotenv import load_dotenv

LOCAL_HTTP_HOSTS = {"localhost", "127.0.0.1", "::1"}
ROUTING_PROFILE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


class ConfigError(ValueError):
    """Raised when environment configuration is unsafe or unusable."""


@dataclass(frozen=True)
class Settings:
    geocoder_provider: str
    geocoder_base_url: str
    reverse_geocoder_base_url: str
    geocoder_min_interval_s: float
    suggestions_enabled: bool
    suggestion_provider: str
    suggestion_endpoint_url: str
    suggestion_min_query_length: int
    suggestion_max_results: int
    suggestion_min_interval_s: float
    suggestion_debounce_ms: int
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
    if raw_value is None:
        return default
    try:
        return float(raw_value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number.") from exc


def _env_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    clean_value = raw_value.strip().lower()
    if clean_value in {"1", "true", "yes", "on"}:
        return True
    if clean_value in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be true or false.")


def _env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer.") from exc


def _require_range(name: str, value: float, lower: float, upper: float) -> float:
    if lower <= value <= upper:
        return value
    raise ConfigError(f"{name} must be between {lower:g} and {upper:g}.")


def _require_int_range(name: str, value: int, lower: int, upper: int) -> int:
    if lower <= value <= upper:
        return value
    raise ConfigError(f"{name} must be between {lower} and {upper}.")


def _validate_provider_url(name: str, value: str) -> str:
    clean_value = value.strip()
    parsed_url = urlparse(clean_value)
    if parsed_url.scheme not in {"https", "http"} or not parsed_url.netloc:
        raise ConfigError(f"{name} must be an absolute http or https URL.")
    if parsed_url.username is not None or parsed_url.password is not None:
        raise ConfigError(f"{name} must not include credentials in the URL.")
    if parsed_url.scheme == "http" and parsed_url.hostname not in LOCAL_HTTP_HOSTS:
        raise ConfigError(f"{name} must use https unless it points to localhost.")
    return clean_value


def _validate_routing_profile(value: str) -> str:
    clean_value = value.strip()
    if ROUTING_PROFILE_PATTERN.fullmatch(clean_value) is None:
        raise ConfigError(
            "SUNROUTER_ROUTING_PROFILE may only contain letters, numbers, "
            "underscores, and hyphens."
        )
    return clean_value


def _validate_user_agent(value: str) -> str:
    clean_value = value.strip()
    if not clean_value:
        raise ConfigError("SUNROUTER_USER_AGENT must not be empty.")
    if len(clean_value) > 256:
        raise ConfigError("SUNROUTER_USER_AGENT must be 256 characters or fewer.")
    return clean_value


def load_settings() -> Settings:
    load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)
    timezone_name = os.getenv("SUNROUTER_DEFAULT_TIMEZONE", "America/New_York")
    http_timeout_s = _require_range(
        "SUNROUTER_HTTP_TIMEOUT_S",
        _env_float("SUNROUTER_HTTP_TIMEOUT_S", 10.0),
        1.0,
        60.0,
    )
    cache_ttl_s = _require_range(
        "SUNROUTER_CACHE_TTL_S",
        _env_float("SUNROUTER_CACHE_TTL_S", 900.0),
        0.0,
        86_400.0,
    )
    geocoder_min_interval_s = _require_range(
        "SUNROUTER_GEOCODER_MIN_INTERVAL_S",
        _env_float("SUNROUTER_GEOCODER_MIN_INTERVAL_S", 1.0),
        0.0,
        60.0,
    )
    suggestion_min_query_length = _require_int_range(
        "SUNROUTER_SUGGESTION_MIN_QUERY_LENGTH",
        _env_int("SUNROUTER_SUGGESTION_MIN_QUERY_LENGTH", 3),
        1,
        20,
    )
    suggestion_max_results = _require_int_range(
        "SUNROUTER_SUGGESTION_MAX_RESULTS",
        _env_int("SUNROUTER_SUGGESTION_MAX_RESULTS", 5),
        1,
        10,
    )
    suggestion_min_interval_s = _require_range(
        "SUNROUTER_SUGGESTION_MIN_INTERVAL_S",
        _env_float("SUNROUTER_SUGGESTION_MIN_INTERVAL_S", 0.35),
        0.0,
        60.0,
    )
    suggestion_debounce_ms = _require_int_range(
        "SUNROUTER_SUGGESTION_DEBOUNCE_MS",
        _env_int("SUNROUTER_SUGGESTION_DEBOUNCE_MS", 350),
        100,
        5000,
    )
    router_min_interval_s = _require_range(
        "SUNROUTER_ROUTER_MIN_INTERVAL_S",
        _env_float("SUNROUTER_ROUTER_MIN_INTERVAL_S", 1.0),
        0.0,
        60.0,
    )
    max_alternatives = _require_int_range(
        "SUNROUTER_MAX_ALTERNATIVES",
        _env_int("SUNROUTER_MAX_ALTERNATIVES", 3),
        1,
        5,
    )

    return Settings(
        geocoder_provider=os.getenv("SUNROUTER_GEOCODER_PROVIDER", "nominatim").lower(),
        geocoder_base_url=_validate_provider_url(
            "SUNROUTER_GEOCODER_BASE_URL",
            os.getenv(
                "SUNROUTER_GEOCODER_BASE_URL",
                "https://nominatim.openstreetmap.org/search",
            ),
        ),
        reverse_geocoder_base_url=_validate_provider_url(
            "SUNROUTER_REVERSE_GEOCODER_BASE_URL",
            os.getenv(
                "SUNROUTER_REVERSE_GEOCODER_BASE_URL",
                "https://nominatim.openstreetmap.org/reverse",
            ),
        ),
        geocoder_min_interval_s=geocoder_min_interval_s,
        suggestions_enabled=_env_bool("SUNROUTER_SUGGESTIONS_ENABLED", True),
        suggestion_provider=os.getenv(
            "SUNROUTER_SUGGESTION_PROVIDER", "photon"
        ).lower(),
        suggestion_endpoint_url=_validate_provider_url(
            "SUNROUTER_SUGGESTION_ENDPOINT_URL",
            os.getenv(
                "SUNROUTER_SUGGESTION_ENDPOINT_URL",
                "https://photon.komoot.io/api",
            ),
        ),
        suggestion_min_query_length=suggestion_min_query_length,
        suggestion_max_results=suggestion_max_results,
        suggestion_min_interval_s=suggestion_min_interval_s,
        suggestion_debounce_ms=suggestion_debounce_ms,
        router_provider=os.getenv("SUNROUTER_ROUTER_PROVIDER", "osrm").lower(),
        router_base_url=_validate_provider_url(
            "SUNROUTER_ROUTER_BASE_URL",
            os.getenv(
                "SUNROUTER_ROUTER_BASE_URL",
                "https://router.project-osrm.org/route/v1",
            ),
        ),
        router_min_interval_s=router_min_interval_s,
        routing_profile=_validate_routing_profile(
            os.getenv("SUNROUTER_ROUTING_PROFILE", "driving")
        ),
        user_agent=_validate_user_agent(
            os.getenv("SUNROUTER_USER_AGENT", "sun-glare-router/0.1.0")
        ),
        http_timeout_s=http_timeout_s,
        cache_ttl_s=cache_ttl_s,
        max_alternatives=max_alternatives,
        default_timezone=timezone_name
        if timezone_name in available_timezones()
        else "UTC",
        log_level=os.getenv("SUNROUTER_LOG_LEVEL", "INFO").upper(),
    )


def supported_timezones() -> list[str]:
    return sorted(available_timezones())
