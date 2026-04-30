from __future__ import annotations

from datetime import datetime, timedelta
import logging
import math
from typing import Callable

from src.i18n import t
from src.models import (
    Coordinates,
    Route,
    RouteEvaluation,
    RouteSegmentRisk,
    SunPosition,
)
from src.solar import get_sun_position
from src.utils import (
    angular_difference_degrees,
    calculate_bearing,
    clamp,
    haversine_distance_m,
    midpoint_coordinates,
)

logger = logging.getLogger("sunrouter.scoring")
# Treat segments at 35%+ normalized risk as "high risk" for summary metrics.
HIGH_RISK_SEGMENT_THRESHOLD = 0.35
SunPositionResolver = Callable[[datetime, Coordinates], SunPosition]


def glare_alignment_factor(angle_difference_deg: float) -> float:
    diff_rad = math.radians(angle_difference_deg)
    return clamp(((math.cos(diff_rad) + 1.0) / 2.0) ** 3, 0.0, 1.0)


def _elevation_factor(elevation_deg: float) -> float:
    if elevation_deg <= 0.0:
        return 0.0
    return clamp((45.0 - elevation_deg) / 45.0, 0.0, 1.0)


def _empty_evaluation(route: Route) -> RouteEvaluation:
    return RouteEvaluation(
        route=route,
        glare_score=0.0,
        total_length_m=0.0,
        peak_segment_score=0.0,
        aligned_distance_m=0.0,
        segment_risks=[],
    )


def evaluate_route(
    route: Route,
    trip_start_moment: datetime,
    sun_position_at: SunPositionResolver = get_sun_position,
) -> RouteEvaluation:
    if len(route.geometry) < 2:
        return _empty_evaluation(route)

    segments: list[tuple[Coordinates, Coordinates, float]] = []
    total_length_m = 0.0
    for start, end in zip(route.geometry, route.geometry[1:]):
        segment_length_m = haversine_distance_m(start, end)
        if segment_length_m <= 0.0:
            continue
        total_length_m += segment_length_m
        segments.append((start, end, segment_length_m))

    if total_length_m == 0.0:
        return _empty_evaluation(route)

    weighted_risk = 0.0
    peak_segment_score = 0.0
    aligned_distance_m = 0.0
    high_risk_distance_m = 0.0
    high_risk_duration_s = 0.0
    dominant_bearing_deg: float | None = None
    peak_risk_time_offset_min: float | None = None
    peak_risk_distance_m: float | None = None
    peak_risk_coordinates: Coordinates | None = None
    segment_risks: list[RouteSegmentRisk] = []
    elapsed_duration_s = 0.0
    elapsed_distance_m = 0.0

    for start, end, segment_length_m in segments:
        segment_duration_s = route.metrics.duration_s * (
            segment_length_m / total_length_m
        )
        segment_bearing = calculate_bearing(start, end)
        midpoint = midpoint_coordinates(start, end)
        midpoint_offset_s = elapsed_duration_s + (segment_duration_s / 2.0)
        sun_position = sun_position_at(
            trip_start_moment + timedelta(seconds=midpoint_offset_s),
            midpoint,
        )
        elevation_factor = _elevation_factor(sun_position.elevation_deg)
        angle_difference = angular_difference_degrees(
            segment_bearing,
            sun_position.azimuth_deg,
        )
        angular_factor = glare_alignment_factor(angle_difference)
        segment_score = elevation_factor * angular_factor
        segment_score_pct = round(segment_score * 100.0, 2)
        weighted_segment_score = segment_score * segment_length_m
        weighted_risk += weighted_segment_score

        if segment_score > 0.0 and angle_difference <= 45.0:
            aligned_distance_m += segment_length_m

        if segment_score >= HIGH_RISK_SEGMENT_THRESHOLD:
            high_risk_distance_m += segment_length_m
            high_risk_duration_s += segment_duration_s

        if weighted_segment_score > peak_segment_score:
            peak_segment_score = weighted_segment_score
            dominant_bearing_deg = segment_bearing
            peak_risk_time_offset_min = round(midpoint_offset_s / 60.0, 2)
            peak_risk_distance_m = round(
                elapsed_distance_m + (segment_length_m / 2.0),
                2,
            )
            peak_risk_coordinates = midpoint

        segment_risks.append(
            RouteSegmentRisk(
                start_coordinates=start,
                end_coordinates=end,
                midpoint_coordinates=midpoint,
                segment_length_m=round(segment_length_m, 2),
                estimated_duration_s=round(segment_duration_s, 2),
                start_offset_s=round(elapsed_duration_s, 2),
                midpoint_offset_s=round(midpoint_offset_s, 2),
                bearing_deg=segment_bearing,
                angle_difference_deg=round(angle_difference, 2),
                sun_position=sun_position,
                glare_score=segment_score_pct,
            )
        )
        elapsed_duration_s += segment_duration_s
        elapsed_distance_m += segment_length_m

    glare_score = (
        0.0
        if total_length_m == 0
        else clamp((weighted_risk / total_length_m) * 100.0, 0.0, 100.0)
    )

    return RouteEvaluation(
        route=route,
        glare_score=round(glare_score, 2),
        total_length_m=total_length_m,
        peak_segment_score=round(peak_segment_score, 2),
        aligned_distance_m=round(aligned_distance_m, 2),
        dominant_bearing_deg=dominant_bearing_deg,
        high_risk_distance_m=round(high_risk_distance_m, 2),
        high_risk_duration_s=round(high_risk_duration_s, 2),
        peak_risk_time_offset_min=peak_risk_time_offset_min,
        peak_risk_distance_m=peak_risk_distance_m,
        peak_risk_coordinates=peak_risk_coordinates,
        segment_risks=segment_risks,
    )


def rank_routes(
    routes: list[Route],
    trip_start_moment: datetime,
    sun_position_at: SunPositionResolver = get_sun_position,
) -> list[RouteEvaluation]:
    evaluations = [
        evaluate_route(route, trip_start_moment, sun_position_at=sun_position_at)
        for route in routes
    ]
    ranked = sorted(
        evaluations,
        key=lambda evaluation: (
            evaluation.glare_score,
            evaluation.high_risk_duration_s,
            evaluation.route.metrics.distance_m,
            evaluation.route.metrics.duration_s,
        ),
    )
    logger.info(
        "Scored %d route(s) for departure=%s; best glare score=%.1f",
        len(ranked),
        trip_start_moment.isoformat(),
        ranked[0].glare_score if ranked else 0.0,
    )
    return ranked


def explain_recommendation(
    recommended: RouteEvaluation,
    alternatives: list[RouteEvaluation],
    departure_sun_position: SunPosition,
    language: str = "es",
) -> str:
    if departure_sun_position.elevation_deg <= 0:
        return t(language, "scoring.sun_below_horizon")

    if not alternatives:
        if recommended.high_risk_duration_s <= 0.0:
            return t(language, "scoring.single_low_risk")
        return t(
            language,
            "scoring.single_high_risk",
            minutes=recommended.high_risk_duration_s / 60.0,
        )

    best_alternative = alternatives[0]
    score_gap = best_alternative.glare_score - recommended.glare_score

    if recommended.high_risk_duration_s <= 0.0:
        return t(language, "scoring.no_high_risk")

    if score_gap >= 15:
        modifier = t(language, "scoring.modifier.clearly")
    elif score_gap >= 5:
        modifier = t(language, "scoring.modifier.noticeably")
    else:
        modifier = t(language, "scoring.modifier.slightly")

    return t(
        language,
        "scoring.reduction",
        modifier=modifier,
        recommended_minutes=recommended.high_risk_duration_s / 60.0,
        alternative_minutes=best_alternative.high_risk_duration_s / 60.0,
    )
