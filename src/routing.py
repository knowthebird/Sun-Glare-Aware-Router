from __future__ import annotations

import logging
from typing import Protocol

import requests

from src.cache import RateLimiter, TTLCache
from src.config import Settings
from src.models import Coordinates, Route, RouteMetrics
from src.utils import ProviderError

logger = logging.getLogger("sunrouter.routing")


class Router(Protocol):
    def get_routes(self, origin: Coordinates, destination: Coordinates, profile: str) -> list[Route]:
        ...


class OSRMRouter:
    def __init__(
        self,
        base_url: str,
        user_agent: str,
        timeout_s: float,
        max_alternatives: int,
        session: requests.Session | object | None = None,
        cache: TTLCache[str, list[Route]] | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self.timeout_s = timeout_s
        self.max_alternatives = max(1, max_alternatives)
        self.session = session or requests.Session()
        self.cache = cache or TTLCache[str, list[Route]](ttl_s=900.0)
        self.rate_limiter = rate_limiter or RateLimiter(min_interval_s=1.0)

    def get_routes(self, origin: Coordinates, destination: Coordinates, profile: str) -> list[Route]:
        cache_key = (
            f"{profile}:{origin.lat:.6f},{origin.lon:.6f}->{destination.lat:.6f},{destination.lon:.6f}"
        )
        cached = self.cache.get(cache_key)
        if cached is not None:
            logger.debug("Router cache hit for key=%s", cache_key)
            return cached

        url = (
            f"{self.base_url}/{profile}/"
            f"{origin.lon:.6f},{origin.lat:.6f};{destination.lon:.6f},{destination.lat:.6f}"
        )
        self.rate_limiter.wait()
        logger.info(
            "Routing from lat=%.5f lon=%.5f to lat=%.5f lon=%.5f via %s profile=%s",
            origin.lat,
            origin.lon,
            destination.lat,
            destination.lon,
            self.base_url,
            profile,
        )
        try:
            response = self.session.get(
                url,
                params={
                    "alternatives": "true",
                    "overview": "full",
                    "geometries": "geojson",
                    "steps": "false",
                },
                timeout=self.timeout_s,
                headers={"User-Agent": self.user_agent},
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # pragma: no cover - exercised through user-facing handling
            logger.exception("Routing failed for key=%s", cache_key)
            raise ProviderError(f"Routing request failed: {exc}") from exc

        routes = _parse_osrm_routes(payload, self.max_alternatives)
        logger.info("Routing returned %d candidate route(s)", len(routes))
        self.cache.set(cache_key, routes)
        return routes


def _parse_osrm_routes(payload: object, max_alternatives: int) -> list[Route]:
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
                metadata={"provider": "osrm", "route_index": index},
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
