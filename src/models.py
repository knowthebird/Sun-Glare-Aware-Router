from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Coordinates:
    lat: float
    lon: float


@dataclass(frozen=True)
class GeocodeResult:
    label: str
    coordinates: Coordinates


@dataclass(frozen=True)
class RouteMetrics:
    distance_m: float
    duration_s: float


@dataclass(frozen=True)
class Route:
    route_id: str
    geometry: list[Coordinates]
    metrics: RouteMetrics
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SunPosition:
    azimuth_deg: float
    elevation_deg: float


@dataclass(frozen=True)
class RouteEvaluation:
    route: Route
    glare_score: float
    total_length_m: float
    peak_segment_score: float
    aligned_distance_m: float
    dominant_bearing_deg: float | None = None


@dataclass(frozen=True)
class SelectedLocation:
    coordinates: Coordinates
    label: str
    label_source: str


@dataclass(frozen=True)
class LocationPickerState:
    query_text: str
    provisional_result: GeocodeResult | None
    map_center: Coordinates
    confirmed_location: SelectedLocation | None
    map_revision: int


@dataclass(frozen=True)
class AnalysisRequest:
    origin: SelectedLocation
    destination: SelectedLocation
    trip_moment: datetime
    timezone_name: str


@dataclass(frozen=True)
class AnalysisResult:
    request: AnalysisRequest
    sun_position: SunPosition
    ranked_routes: list[RouteEvaluation]
    explanation: str
