from __future__ import annotations

import logging
from typing import Protocol

import requests

from src.cache import RateLimiter, TTLCache
from src.config import Settings
from src.models import Coordinates, GeocodeResult
from src.utils import ProviderError

logger = logging.getLogger("sunrouter.geocoding")


class Geocoder(Protocol):
    def geocode(self, query: str) -> GeocodeResult | None:
        ...

    def reverse_geocode(self, coordinates: Coordinates) -> GeocodeResult | None:
        ...


class NominatimGeocoder:
    def __init__(
        self,
        base_url: str,
        reverse_base_url: str,
        user_agent: str,
        timeout_s: float,
        session: requests.Session | object | None = None,
        cache: TTLCache[str, GeocodeResult | None] | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.reverse_base_url = reverse_base_url.rstrip("/")
        self.user_agent = user_agent
        self.timeout_s = timeout_s
        self.session = session or requests.Session()
        self.cache = cache or TTLCache[str, GeocodeResult | None](ttl_s=900.0)
        self.rate_limiter = rate_limiter or RateLimiter(min_interval_s=1.0)

    def geocode(self, query: str) -> GeocodeResult | None:
        clean_query = query.strip()
        if not clean_query:
            return None

        cached = self.cache.get(clean_query)
        if cached is not None:
            logger.debug("Geocoder cache hit for query=%s", clean_query)
            return cached

        self.rate_limiter.wait()
        logger.info("Geocoding query=%s via %s", clean_query, self.base_url)
        try:
            response = self.session.get(
                self.base_url,
                params={
                    "q": clean_query,
                    "format": "jsonv2",
                    "limit": 1,
                },
                timeout=self.timeout_s,
                headers={"User-Agent": self.user_agent},
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # pragma: no cover - exercised through user-facing handling
            logger.exception("Geocoding failed for query=%s", clean_query)
            raise ProviderError(f"Geocoding request failed: {exc}") from exc

        result = _parse_nominatim_result(payload)
        if result is None:
            logger.info("Geocoding returned no result for query=%s", clean_query)
        else:
            logger.info(
                "Geocoding resolved query=%s to lat=%.5f lon=%.5f",
                clean_query,
                result.coordinates.lat,
                result.coordinates.lon,
            )
        self.cache.set(clean_query, result)
        return result

    def reverse_geocode(self, coordinates: Coordinates) -> GeocodeResult | None:
        cache_key = f"reverse:{coordinates.lat:.5f},{coordinates.lon:.5f}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            logger.debug("Reverse geocoder cache hit for coordinates=%s", cache_key)
            return cached

        self.rate_limiter.wait()
        logger.info(
            "Reverse geocoding lat=%.5f lon=%.5f via %s",
            coordinates.lat,
            coordinates.lon,
            self.reverse_base_url,
        )
        try:
            response = self.session.get(
                self.reverse_base_url,
                params={
                    "lat": coordinates.lat,
                    "lon": coordinates.lon,
                    "format": "jsonv2",
                    "zoom": 18,
                },
                timeout=self.timeout_s,
                headers={"User-Agent": self.user_agent},
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # pragma: no cover - exercised through user-facing handling
            logger.exception("Reverse geocoding failed for lat=%.5f lon=%.5f", coordinates.lat, coordinates.lon)
            raise ProviderError(f"Reverse geocoding request failed: {exc}") from exc

        result = _parse_nominatim_reverse_result(payload)
        self.cache.set(cache_key, result)
        return result


def _parse_nominatim_result(payload: object) -> GeocodeResult | None:
    if not isinstance(payload, list) or not payload:
        return None

    item = payload[0]
    if not isinstance(item, dict):
        return None

    label = str(item.get("display_name", "")).strip()
    lat = item.get("lat")
    lon = item.get("lon")
    if not label or lat is None or lon is None:
        return None

    return GeocodeResult(
        label=label,
        coordinates=Coordinates(lat=float(lat), lon=float(lon)),
    )


def _parse_nominatim_reverse_result(payload: object) -> GeocodeResult | None:
    if not isinstance(payload, dict):
        return None

    label = str(payload.get("display_name", "")).strip()
    lat = payload.get("lat")
    lon = payload.get("lon")
    if not label or lat is None or lon is None:
        return None

    return GeocodeResult(
        label=label,
        coordinates=Coordinates(lat=float(lat), lon=float(lon)),
    )


def build_geocoder(settings: Settings) -> Geocoder:
    if settings.geocoder_provider != "nominatim":
        raise ProviderError(f"Unsupported geocoder provider: {settings.geocoder_provider}")

    return NominatimGeocoder(
        base_url=settings.geocoder_base_url,
        reverse_base_url=settings.reverse_geocoder_base_url,
        user_agent=settings.user_agent,
        timeout_s=settings.http_timeout_s,
        cache=TTLCache(ttl_s=settings.cache_ttl_s),
        rate_limiter=RateLimiter(settings.geocoder_min_interval_s),
    )
