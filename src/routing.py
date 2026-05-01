from __future__ import annotations

from dataclasses import replace
import logging
import math
from typing import Protocol


from src.cache import RateLimiter, TTLCache
from src.config import Settings
from src.http_client import build_http_session
from src.models import Coordinates, Route, RouteMetrics
from src.utils import (
    ProviderError,
    calculate_bearing,
    clamp,
    haversine_distance_m,
    midpoint_coordinates,
)

logger = logging.getLogger("sunrouter.routing")

MIN_FALLBACK_ROUTE_DISTANCE_M = 1_000.0
FALLBACK_FRACTIONS = (0.35, 0.5, 0.65)
MIN_FALLBACK_OFFSET_M = 600.0
MAX_FALLBACK_OFFSET_M = 20_000.0


class Router(Protocol):
    def get_routes(
        self, origin: Coordinates, destination: Coordinates, profile: str
    ) -> list[Route]: ...


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


class OSRMRouter:
    def __init__(
        self,
        base_url: str,
        user_agent: str,
        timeout_s: float,
        max_alternatives: int,
        session: HTTPSession | None = None,
        cache: TTLCache[str, list[Route]] | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self.timeout_s = timeout_s
        self.max_alternatives = max(1, max_alternatives)
        self.session = session or build_http_session()
        self.cache = cache or TTLCache[str, list[Route]](ttl_s=900.0)
        self.rate_limiter = rate_limiter or RateLimiter(min_interval_s=1.0)

    def get_routes(
        self, origin: Coordinates, destination: Coordinates, profile: str
    ) -> list[Route]:
        cache_key = f"{profile}:{origin.lat:.6f},{origin.lon:.6f}->{destination.lat:.6f},{destination.lon:.6f}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            logger.debug("Router cache hit for key=%s", cache_key)
            return cached

        logger.info(
            "Routing from lat=%.5f lon=%.5f to lat=%.5f lon=%.5f via %s profile=%s",
            origin.lat,
            origin.lon,
            destination.lat,
            destination.lon,
            self.base_url,
            profile,
        )
        direct_routes = self._request_osrm_routes(
            [origin, destination],
            profile,
            allow_alternatives=True,
            max_routes=self.max_alternatives,
        )
        routes = self._merge_unique_routes([], direct_routes)

        if len(routes) < self.max_alternatives:
            for via_point in _fallback_via_points(origin, destination):
                via_routes = self._request_osrm_routes(
                    [origin, via_point, destination],
                    profile,
                    allow_alternatives=False,
                    max_routes=1,
                    metadata={"fallback_via": True},
                )
                routes = self._merge_unique_routes(routes, via_routes)
                if len(routes) >= self.max_alternatives:
                    break

        indexed_routes = _assign_route_indices(routes[: self.max_alternatives])
        logger.info("Routing returned %d candidate route(s)", len(indexed_routes))
        self.cache.set(cache_key, indexed_routes)
        return indexed_routes

    def _request_osrm_routes(
        self,
        points: list[Coordinates],
        profile: str,
        *,
        allow_alternatives: bool,
        max_routes: int,
        metadata: dict[str, object] | None = None,
    ) -> list[Route]:
        url = f"{self.base_url}/{profile}/{_coordinate_path(points)}"
        try:
            self.rate_limiter.wait()
            response = self.session.get(
                url,
                params={
                    "alternatives": "true" if allow_alternatives else "false",
                    "overview": "full",
                    "geometries": "geojson",
                    "steps": "false",
                },
                timeout=self.timeout_s,
                headers={"User-Agent": self.user_agent},
            )
            response.raise_for_status()
            payload = response.json()
        except (
            Exception
        ) as exc:  # pragma: no cover - exercised through user-facing handling
            logger.exception("Routing failed for points=%s", points)
            raise ProviderError(f"Routing request failed: {exc}") from exc

        return _parse_osrm_routes(payload, max_routes, metadata=metadata)

    def _merge_unique_routes(
        self, existing_routes: list[Route], new_routes: list[Route]
    ) -> list[Route]:
        unique_routes = list(existing_routes)
        known_signatures = {_route_signature(route) for route in existing_routes}

        for route in new_routes:
            signature = _route_signature(route)
            if signature in known_signatures:
                continue
            unique_routes.append(route)
            known_signatures.add(signature)

        return unique_routes


def _coordinate_path(points: list[Coordinates]) -> str:
    return ";".join(f"{point.lon:.6f},{point.lat:.6f}" for point in points)


def _fallback_via_points(
    origin: Coordinates, destination: Coordinates
) -> list[Coordinates]:
    direct_distance_m = haversine_distance_m(origin, destination)
    if direct_distance_m < MIN_FALLBACK_ROUTE_DISTANCE_M:
        return []

    route_midpoint = midpoint_coordinates(origin, destination)
    route_bearing_deg = calculate_bearing(origin, destination)
    offset_distance_m = clamp(
        direct_distance_m * 0.18,
        MIN_FALLBACK_OFFSET_M,
        MAX_FALLBACK_OFFSET_M,
    )
    candidate_points: list[Coordinates] = []
    for fraction in FALLBACK_FRACTIONS:
        anchor = _interpolate_coordinates(origin, destination, fraction)
        for perpendicular_bearing in (
            (route_bearing_deg - 90.0) % 360.0,
            (route_bearing_deg + 90.0) % 360.0,
        ):
            candidate_points.append(
                _offset_coordinates(anchor, perpendicular_bearing, offset_distance_m)
            )

    # Centered candidates are useful when the direct midpoint falls on a corridor
    # that still produces different viable alternatives with the upstream router.
    candidate_points.append(
        _offset_coordinates(
            route_midpoint,
            (route_bearing_deg - 90.0) % 360.0,
            offset_distance_m * 0.5,
        )
    )
    candidate_points.append(
        _offset_coordinates(
            route_midpoint,
            (route_bearing_deg + 90.0) % 360.0,
            offset_distance_m * 0.5,
        )
    )
    return candidate_points


def _interpolate_coordinates(
    start: Coordinates, end: Coordinates, fraction: float
) -> Coordinates:
    return Coordinates(
        lat=start.lat + ((end.lat - start.lat) * fraction),
        lon=start.lon + ((end.lon - start.lon) * fraction),
    )


def _offset_coordinates(
    origin: Coordinates, bearing_deg: float, distance_m: float
) -> Coordinates:
    bearing_rad = math.radians(bearing_deg)
    delta_north_m = math.cos(bearing_rad) * distance_m
    delta_east_m = math.sin(bearing_rad) * distance_m

    lat_scale = 111_320.0
    lon_scale = max(111_320.0 * math.cos(math.radians(origin.lat)), 1.0)
    return Coordinates(
        lat=origin.lat + (delta_north_m / lat_scale),
        lon=origin.lon + (delta_east_m / lon_scale),
    )


def _route_signature(route: Route) -> tuple[tuple[float, float], ...]:
    if not route.geometry:
        return ()

    sample_indexes = sorted(
        {
            0,
            len(route.geometry) // 3,
            (2 * len(route.geometry)) // 3,
            len(route.geometry) - 1,
        }
    )
    return tuple(
        (
            round(route.geometry[index].lat, 5),
            round(route.geometry[index].lon, 5),
        )
        for index in sample_indexes
    )


def _assign_route_indices(routes: list[Route]) -> list[Route]:
    indexed_routes: list[Route] = []
    for index, route in enumerate(routes, start=1):
        indexed_routes.append(
            replace(
                route,
                route_id=f"route-{index}",
                metadata={**route.metadata, "route_index": index},
            )
        )
    return indexed_routes


def _parse_osrm_routes(
    payload: object,
    max_alternatives: int,
    *,
    metadata: dict[str, object] | None = None,
) -> list[Route]:
    if not isinstance(payload, dict):
        return []

    raw_routes = payload.get("routes")
    if not isinstance(raw_routes, list):
        return []

    parsed_routes: list[Route] = []
    for index, raw_route in enumerate(raw_routes[:max_alternatives], start=1):
        if not isinstance(raw_route, dict):
            continue

        raw_geometry = raw_route.get("geometry", {})
        if not isinstance(raw_geometry, dict):
            continue

        raw_coordinates = raw_geometry.get("coordinates", [])
        if not isinstance(raw_coordinates, list):
            continue

        geometry = [
            Coordinates(lat=float(point[1]), lon=float(point[0]))
            for point in raw_coordinates
            if isinstance(point, list) and len(point) >= 2
        ]
        if len(geometry) < 2:
            continue

        parsed_routes.append(
            Route(
                route_id=f"route-{index}",
                geometry=geometry,
                metrics=RouteMetrics(
                    distance_m=float(raw_route.get("distance", 0.0)),
                    duration_s=float(raw_route.get("duration", 0.0)),
                ),
                metadata={
                    "provider": "osrm",
                    "route_index": index,
                    **(metadata or {}),
                },
            )
        )

    return parsed_routes


def build_router(settings: Settings) -> Router:
    if settings.router_provider != "osrm":
        raise ProviderError(f"Unsupported router provider: {settings.router_provider}")

    return OSRMRouter(
        base_url=settings.router_base_url,
        user_agent=settings.user_agent,
        timeout_s=settings.http_timeout_s,
        max_alternatives=settings.max_alternatives,
        cache=TTLCache(ttl_s=settings.cache_ttl_s),
        rate_limiter=RateLimiter(settings.router_min_interval_s),
    )
