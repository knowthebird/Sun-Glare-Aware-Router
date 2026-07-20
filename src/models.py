from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Literal


RouteTimeSearchMode = Literal["departure", "arrival"]
RouteDateRangeSearchStrategy = Literal["exact", "adaptive"]
RouteDateRangeBudgetOutcome = Literal["within_budget", "exhausted"]


@dataclass(frozen=True)
class Coordinates:
    lat: float
    lon: float


@dataclass(frozen=True)
class GeocodeResult:
    label: str
    coordinates: Coordinates
    provider_id: str | None = None


@dataclass(frozen=True)
class AddressSuggestion:
    label: str
    coordinates: Coordinates
    provider_id: str | None = None


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
class RouteSegmentRisk:
    start_coordinates: Coordinates
    end_coordinates: Coordinates
    midpoint_coordinates: Coordinates
    segment_length_m: float
    estimated_duration_s: float
    start_offset_s: float
    midpoint_offset_s: float
    bearing_deg: float
    angle_difference_deg: float
    sun_position: SunPosition
    glare_score: float


@dataclass(frozen=True)
class RouteHighGlareStretch:
    start_coordinates: Coordinates
    end_coordinates: Coordinates
    start_offset_s: float
    end_offset_s: float
    duration_s: float
    distance_m: float
    start_distance_m: float
    end_distance_m: float
    max_glare_score: float
    peak_segment: RouteSegmentRisk
    segments: list[RouteSegmentRisk] = field(default_factory=list)


@dataclass(frozen=True)
class RouteEvaluation:
    route: Route
    glare_score: float
    total_length_m: float
    peak_segment_score: float
    aligned_distance_m: float
    dominant_bearing_deg: float | None = None
    high_risk_distance_m: float = 0.0
    high_risk_duration_s: float = 0.0
    peak_risk_time_offset_min: float | None = None
    peak_risk_distance_m: float | None = None
    peak_risk_coordinates: Coordinates | None = None
    peak_glare_segment: RouteSegmentRisk | None = None
    peak_glare_coordinates: Coordinates | None = None
    peak_glare_score: float = 0.0
    peak_glare_category: str | None = None
    longest_high_glare_stretch: RouteHighGlareStretch | None = None
    any_high_risk_segments: bool = False
    segment_risks: list[RouteSegmentRisk] = field(default_factory=list)
    analysis_coordinate_count: int = 0
    original_coordinate_count: int = 0
    analysis_resampled: bool = False
    analysis_policy: str | None = None


@dataclass(frozen=True)
class RouteTimeCandidate:
    requested_time: datetime
    departure_time: datetime
    arrival_time: datetime
    route_evaluation: RouteEvaluation

    @property
    def glare_score(self) -> float:
        return self.route_evaluation.glare_score

    @property
    def high_risk_duration_s(self) -> float:
        return self.route_evaluation.high_risk_duration_s

    @property
    def high_risk_distance_m(self) -> float:
        return self.route_evaluation.high_risk_distance_m


@dataclass(frozen=True)
class RouteTimeWindowEvaluation:
    search_mode: RouteTimeSearchMode
    earliest_time: datetime
    latest_time: datetime
    increment: timedelta
    candidates: list[RouteTimeCandidate]
    ranked_candidates: list[RouteTimeCandidate]

    @property
    def recommended_candidate(self) -> RouteTimeCandidate:
        return self.ranked_candidates[0]


@dataclass(frozen=True)
class RouteDateRangeRequest:
    start_date: date
    end_date: date
    daily_earliest_time: time
    daily_latest_time: time
    search_mode: RouteTimeSearchMode
    timezone_name: str
    final_resolution: timedelta
    evaluation_budget: int


@dataclass(frozen=True)
class RouteDateRangeCandidateSummary:
    requested_time: datetime
    departure_time: datetime
    arrival_time: datetime
    glare_score: float
    high_risk_duration_s: float
    high_risk_distance_m: float
    date_index: int
    time_offset_s: int
    search_phase: str
    peak_glare_score: float = 0.0
    peak_glare_category: str | None = None


@dataclass(frozen=True)
class RouteDateRangeVisualizationCell:
    requested_wall_date: date
    requested_wall_time: time
    requested_time: datetime
    departure_time: datetime
    arrival_time: datetime
    glare_score: float
    high_risk_duration_s: float
    high_risk_distance_m: float
    peak_glare_score: float
    peak_glare_category: str | None
    utc_offset_minutes: int
    date_index: int
    time_offset_s: int
    reused_optimizer_evaluation: bool
    peak_segment_index: int | None = None
    peak_segment_sun_azimuth_deg: float | None = None
    peak_segment_sun_elevation_deg: float | None = None
    peak_segment_angle_difference_deg: float | None = None
    peak_segment_bearing_deg: float | None = None
    high_risk_threshold_crossed: bool = False


@dataclass(frozen=True)
class RouteDateRangeBestTimePoint:
    sampled_date: date
    representative_time: time
    representative_time_offset_s: int
    minimum_glare_score: float
    interval_average_score: float


@dataclass(frozen=True)
class RouteDateRangeAdjacentChange:
    previous_date: date
    current_date: date
    requested_wall_time: time
    previous_utc_offset_minutes: int
    current_utc_offset_minutes: int
    previous_glare_score: float
    current_glare_score: float
    score_delta: float
    previous_peak_sun_azimuth_deg: float | None
    current_peak_sun_azimuth_deg: float | None
    previous_peak_sun_elevation_deg: float | None
    current_peak_sun_elevation_deg: float | None
    previous_peak_segment_index: int | None
    current_peak_segment_index: int | None
    previous_peak_segment_score: float
    current_peak_segment_score: float
    previous_peak_angle_difference_deg: float | None
    current_peak_angle_difference_deg: float | None
    previous_peak_bearing_deg: float | None
    current_peak_bearing_deg: float | None
    scoring_threshold_crossed: bool


@dataclass(frozen=True)
class RouteDateRangeVisualizationDiagnostics:
    route_geometry_fingerprint: str
    date_interval_days: int
    time_interval: timedelta
    requested_cell_count: int
    evaluated_cell_count: int
    reused_optimizer_evaluations: int
    new_evaluations: int
    evaluation_time_s: float
    invalid_wall_time_count: int
    dst_transition_dates: tuple[date, ...]
    large_adjacent_change_count: int


@dataclass(frozen=True)
class RouteDateRangeVisualizationGrid:
    cells: list[RouteDateRangeVisualizationCell]
    representative_best_times: list[RouteDateRangeBestTimePoint]
    fixed_time_offset_s: int
    diagnostics: RouteDateRangeVisualizationDiagnostics
    large_adjacent_changes: list[RouteDateRangeAdjacentChange]


@dataclass(frozen=True)
class RouteDateRangeSearchDiagnostics:
    candidate_count_at_final_resolution: int
    initial_date_step_days: int
    initial_time_step: timedelta
    refinement_rounds: int
    retained_basin_count: int
    duplicate_candidate_evaluations_avoided: int
    ambiguous_wall_times: int
    nonexistent_wall_times_adjusted: int
    dst_transition_date_indices: tuple[int, ...]
    sampled_date_indices: tuple[int, ...]
    sampled_time_offsets_s: tuple[int, ...]


@dataclass(frozen=True)
class RouteDateRangeEvaluation:
    request: RouteDateRangeRequest
    search_strategy: RouteDateRangeSearchStrategy
    candidate_summaries: list[RouteDateRangeCandidateSummary]
    ranked_candidate_summaries: list[RouteDateRangeCandidateSummary]
    recommended_candidate: RouteTimeCandidate
    top_alternative_candidates: list[RouteTimeCandidate]
    unique_evaluations: int
    exact: bool
    final_date_resolution_days: int
    final_time_resolution: timedelta
    budget_outcome: RouteDateRangeBudgetOutcome
    diagnostics: RouteDateRangeSearchDiagnostics
    visualization_grid: RouteDateRangeVisualizationGrid | None = None


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


@dataclass(frozen=True)
class RouteAlternativesResult:
    origin: SelectedLocation
    destination: SelectedLocation
    routing_profile: str
    routes: list[Route]


@dataclass(frozen=True)
class TimeWindowEvaluationParams:
    route_id: str
    search_mode: RouteTimeSearchMode
    trip_date: date
    earliest_time: time
    latest_time: time
    timezone_name: str


@dataclass(frozen=True)
class DateRangeEvaluationParams:
    route_id: str
    search_mode: RouteTimeSearchMode
    start_date: date
    end_date: date
    daily_earliest_time: time
    daily_latest_time: time
    timezone_name: str
