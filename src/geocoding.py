from __future__ import annotations

import logging
from typing import Protocol

from src.cache import RateLimiter, TTLCache
from src.config import Settings
from src.http_client import build_http_session
from src.models import AddressSuggestion, Coordinates, GeocodeResult
from src.utils import ProviderError

logger = logging.getLogger("sunrouter.geocoding")


class HTTPResponse(Protocol):
    def raise_for_status(self) -> None: ...

    def json(self) -> object: ...


class HTTPSession(Protocol):
    def get(
        self,
        url: str,
        *,
        params: dict[str, object],
        timeout: float,
        headers: dict[str, str],
    ) -> HTTPResponse: ...


class Geocoder(Protocol):
    def geocode(self, query: str) -> GeocodeResult | None: ...

    def reverse_geocode(self, coordinates: Coordinates) -> GeocodeResult | None: ...


class SuggestionProvider(Protocol):
    def suggest(self, query: str) -> list[AddressSuggestion]: ...


class DisabledSuggestionProvider:
    def suggest(self, query: str) -> list[AddressSuggestion]:
        return []


class NominatimGeocoder:
    def __init__(
        self,
        base_url: str,
        reverse_base_url: str,
        user_agent: str,
        timeout_s: float,
        session: HTTPSession | None = None,
        cache: TTLCache[str, GeocodeResult | None] | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.reverse_base_url = reverse_base_url.rstrip("/")
        self.user_agent = user_agent
        self.timeout_s = timeout_s
        self.session = session or build_http_session()
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
        except (
            Exception
        ) as exc:  # pragma: no cover - exercised through user-facing handling
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
        except (
            Exception
        ) as exc:  # pragma: no cover - exercised through user-facing handling
            logger.exception(
                "Reverse geocoding failed for lat=%.5f lon=%.5f",
                coordinates.lat,
                coordinates.lon,
            )
            raise ProviderError(f"Reverse geocoding request failed: {exc}") from exc

        result = _parse_nominatim_reverse_result(payload)
        self.cache.set(cache_key, result)
        return result


class PhotonSuggestionProvider:
    def __init__(
        self,
        endpoint_url: str,
        user_agent: str,
        timeout_s: float,
        min_query_length: int,
        max_results: int,
        session: HTTPSession | None = None,
        cache: TTLCache[str, list[AddressSuggestion]] | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self.endpoint_url = endpoint_url.rstrip("/")
        self.user_agent = user_agent
        self.timeout_s = timeout_s
        self.min_query_length = min_query_length
        self.max_results = max_results
        self.session = session or build_http_session()
        self.cache = cache or TTLCache[str, list[AddressSuggestion]](ttl_s=900.0)
        self.rate_limiter = rate_limiter or RateLimiter(min_interval_s=0.25)

    def suggest(self, query: str) -> list[AddressSuggestion]:
        clean_query = query.strip()
        if len(clean_query) < self.min_query_length:
            return []

        cache_key = clean_query.casefold()
        cached = self.cache.get(cache_key)
        if cached is not None:
            logger.debug("Suggestion cache hit for query=%s", clean_query)
            return cached

        self.rate_limiter.wait()
        logger.info("Fetching address suggestions for query=%s via Photon", clean_query)
        try:
            response = self.session.get(
                self.endpoint_url,
                params={"q": clean_query, "limit": self.max_results},
                timeout=self.timeout_s,
                headers={"User-Agent": self.user_agent},
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            logger.warning("Photon suggestion request failed for query=%s", clean_query)
            self.cache.set(cache_key, [])
            raise ProviderError(f"Suggestion request failed: {exc}") from exc

        suggestions = _parse_photon_suggestions(payload, limit=self.max_results)
        self.cache.set(cache_key, suggestions)
        return suggestions


def _clean_text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _append_unique(parts: list[str], value: str) -> None:
    clean_value = value.strip()
    if clean_value and clean_value.casefold() not in {
        part.casefold() for part in parts
    }:
        parts.append(clean_value)


def _photon_label(properties: dict[str, object]) -> str:
    parts: list[str] = []
    name = _clean_text(properties.get("name"))
    street = _clean_text(properties.get("street"))
    house_number = _clean_text(properties.get("housenumber"))
    street_address = " ".join(part for part in (house_number, street) if part).strip()
    locality = (
        _clean_text(properties.get("city"))
        or _clean_text(properties.get("district"))
        or _clean_text(properties.get("locality"))
        or _clean_text(properties.get("county"))
    )

    _append_unique(parts, name)
    _append_unique(parts, street_address or street)
    _append_unique(parts, _clean_text(properties.get("postcode")))
    _append_unique(parts, locality)
    _append_unique(parts, _clean_text(properties.get("state")))
    _append_unique(parts, _clean_text(properties.get("country")))

    return ", ".join(parts)


def _photon_provider_id(properties: dict[str, object]) -> str | None:
    osm_type = _clean_text(properties.get("osm_type"))
    osm_id = _clean_text(properties.get("osm_id"))
    if osm_type and osm_id:
        return f"{osm_type}:{osm_id}"
    return None


def _parse_photon_suggestions(
    payload: object, *, limit: int
) -> list[AddressSuggestion]:
    if not isinstance(payload, dict):
        return []
    features = payload.get("features")
    if not isinstance(features, list):
        return []

    suggestions: list[AddressSuggestion] = []
    seen: set[tuple[str, float, float]] = set()
    for feature in features:
        if len(suggestions) >= limit:
            break
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties")
        geometry = feature.get("geometry")
        if not isinstance(properties, dict) or not isinstance(geometry, dict):
            continue
        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, list) or len(coordinates) < 2:
            continue

        label = _photon_label(properties)
        if not label:
            continue
        try:
            lon = float(coordinates[0])
            lat = float(coordinates[1])
        except (TypeError, ValueError):
            continue

        identity = (label.casefold(), round(lat, 7), round(lon, 7))
        if identity in seen:
            continue
        seen.add(identity)
        suggestions.append(
            AddressSuggestion(
                label=label,
                coordinates=Coordinates(lat=lat, lon=lon),
                provider_id=_photon_provider_id(properties),
            )
        )

    return suggestions


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
        raise ProviderError(
            f"Unsupported geocoder provider: {settings.geocoder_provider}"
        )

    return NominatimGeocoder(
        base_url=settings.geocoder_base_url,
        reverse_base_url=settings.reverse_geocoder_base_url,
        user_agent=settings.user_agent,
        timeout_s=settings.http_timeout_s,
        cache=TTLCache(ttl_s=settings.cache_ttl_s),
        rate_limiter=RateLimiter(settings.geocoder_min_interval_s),
    )


def build_suggestion_provider(settings: Settings) -> SuggestionProvider:
    if not settings.suggestions_enabled:
        return DisabledSuggestionProvider()
    if settings.suggestion_provider != "photon":
        raise ProviderError(
            f"Unsupported suggestion provider: {settings.suggestion_provider}"
        )

    return PhotonSuggestionProvider(
        endpoint_url=settings.suggestion_endpoint_url,
        user_agent=settings.user_agent,
        timeout_s=settings.http_timeout_s,
        min_query_length=settings.suggestion_min_query_length,
        max_results=settings.suggestion_max_results,
        cache=TTLCache(ttl_s=settings.cache_ttl_s),
        rate_limiter=RateLimiter(settings.suggestion_min_interval_s),
    )
