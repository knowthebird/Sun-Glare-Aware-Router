from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
import math
from typing import Callable

from src.i18n import t
from src.models import (
    Coordinates,
    Route,
    RouteEvaluation,
    RouteHighGlareStretch,
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
HIGH_RISK_SEGMENT_SCORE = HIGH_RISK_SEGMENT_THRESHOLD * 100.0
MAX_ANALYSIS_COORDINATES = 500
TURN_PRESERVATION_THRESHOLD_DEG = 25.0
SunPositionResolver = Callable[[datetime, Coordinates], SunPosition]


def glare_alignment_factor(angle_difference_deg: float) -> float:
    diff_rad = math.radians(angle_difference_deg)
    return clamp(((math.cos(diff_rad) + 1.0) / 2.0) ** 3, 0.0, 1.0)


def _elevation_factor(elevation_deg: float) -> float:
    if elevation_deg <= 0.0:
        return 0.0
    return clamp((45.0 - elevation_deg) / 45.0, 0.0, 1.0)


def glare_category_for_score(score: float) -> str:
    if score >= 65.0:
        return "severe"
    if score >= HIGH_RISK_SEGMENT_SCORE:
        return "high"
    if score >= 20.0:
        return "moderate"
    if score >= 5.0:
        return "low"
    return "minimal"


def _empty_evaluation(route: Route) -> RouteEvaluation:
    return RouteEvaluation(
        route=route,
        glare_score=0.0,
        total_length_m=0.0,
        peak_segment_score=0.0,
        aligned_distance_m=0.0,
        segment_risks=[],
        analysis_coordinate_count=0,
        original_coordinate_count=len(route.geometry),
        analysis_resampled=False,
        analysis_policy=f"max_analysis_coordinates={MAX_ANALYSIS_COORDINATES}",
    )


def route_analysis_geometry(
    geometry: list[Coordinates],
    *,
    max_coordinates: int = MAX_ANALYSIS_COORDINATES,
) -> list[Coordinates]:
    """Return a bounded route geometry for scoring while preserving route shape."""

    if max_coordinates < 2:
        raise ValueError("max_coordinates must be at least 2")

    deduped = _dedupe_consecutive_coordinates(geometry)
    if len(deduped) <= max_coordinates:
        return deduped

    distances = _cumulative_distances(deduped)
    total_distance = distances[-1]
    if total_distance <= 0.0:
        return [deduped[0], deduped[-1]]

    turn_points = _major_turn_points(deduped, distances)
    turn_budget = max(0, max_coordinates // 3)
    strongest_turns = sorted(
        turn_points,
        key=lambda item: (-item[1], distances[item[0]]),
    )[:turn_budget]
    reserved_distances = {0.0, total_distance}
    for index, _turn_strength in strongest_turns:
        reserved_distances.add(distances[index])

    target_count = max_coordinates - len(reserved_distances)
    if target_count > 0:
        spacing = total_distance / (target_count + 1)
        for sample_index in range(1, target_count + 1):
            reserved_distances.add(spacing * sample_index)

    sampled = [
        _interpolate_at_distance(deduped, distances, distance_m)
        for distance_m in sorted(reserved_distances)
    ]
    return _dedupe_consecutive_coordinates(sampled)


def _dedupe_consecutive_coordinates(
    geometry: list[Coordinates],
) -> list[Coordinates]:
    deduped: list[Coordinates] = []
    for point in geometry:
        if not deduped or point != deduped[-1]:
            deduped.append(point)
    return deduped


def _cumulative_distances(geometry: list[Coordinates]) -> list[float]:
    distances = [0.0]
    elapsed = 0.0
    for start, end in zip(geometry, geometry[1:]):
        elapsed += haversine_distance_m(start, end)
        distances.append(elapsed)
    return distances


def _major_turn_points(
    geometry: list[Coordinates],
    distances: list[float],
) -> list[tuple[int, float]]:
    turn_points: list[tuple[int, float]] = []
    for index in range(1, len(geometry) - 1):
        inbound_distance = distances[index] - distances[index - 1]
        outbound_distance = distances[index + 1] - distances[index]
        if inbound_distance <= 0.0 or outbound_distance <= 0.0:
            continue
        inbound_bearing = calculate_bearing(geometry[index - 1], geometry[index])
        outbound_bearing = calculate_bearing(geometry[index], geometry[index + 1])
        turn_strength = angular_difference_degrees(inbound_bearing, outbound_bearing)
        if turn_strength >= TURN_PRESERVATION_THRESHOLD_DEG:
            turn_points.append((index, turn_strength))
    return turn_points


def _interpolate_at_distance(
    geometry: list[Coordinates],
    distances: list[float],
    target_distance_m: float,
) -> Coordinates:
    if target_distance_m <= 0.0:
        return geometry[0]
    if target_distance_m >= distances[-1]:
        return geometry[-1]

    low = 0
    high = len(distances) - 1
    while low < high:
        mid = (low + high) // 2
        if distances[mid] < target_distance_m:
            low = mid + 1
        else:
            high = mid

    end_index = max(1, low)
    start_index = end_index - 1
    segment_distance = distances[end_index] - distances[start_index]
    if segment_distance <= 0.0:
        return geometry[end_index]
    fraction = (target_distance_m - distances[start_index]) / segment_distance
    start = geometry[start_index]
    end = geometry[end_index]
    return Coordinates(
        lat=start.lat + ((end.lat - start.lat) * fraction),
        lon=start.lon + ((end.lon - start.lon) * fraction),
    )


def _segment_instant(trip_start_moment: datetime, offset_s: float) -> datetime:
    if trip_start_moment.tzinfo is None or trip_start_moment.utcoffset() is None:
        return trip_start_moment + timedelta(seconds=offset_s)
    return trip_start_moment.astimezone(UTC) + timedelta(seconds=offset_s)


def _make_high_glare_stretch(
    segments: list[RouteSegmentRisk],
    start_distance_m: float,
) -> RouteHighGlareStretch:
    peak_segment = max(segments, key=lambda segment: segment.glare_score)
    duration_s = sum(segment.estimated_duration_s for segment in segments)
    distance_m = sum(segment.segment_length_m for segment in segments)
    return RouteHighGlareStretch(
        start_coordinates=segments[0].start_coordinates,
        end_coordinates=segments[-1].end_coordinates,
        start_offset_s=segments[0].start_offset_s,
        end_offset_s=round(
            segments[-1].start_offset_s + segments[-1].estimated_duration_s,
            2,
        ),
        duration_s=round(duration_s, 2),
        distance_m=round(distance_m, 2),
        start_distance_m=round(start_distance_m, 2),
        end_distance_m=round(start_distance_m + distance_m, 2),
        max_glare_score=peak_segment.glare_score,
        peak_segment=peak_segment,
        segments=list(segments),
    )


def _longest_high_glare_stretch(
    segment_risks: list[RouteSegmentRisk],
) -> RouteHighGlareStretch | None:
    stretches: list[RouteHighGlareStretch] = []
    current_segments: list[RouteSegmentRisk] = []
    current_start_distance_m = 0.0
    elapsed_distance_m = 0.0

    for segment in segment_risks:
        qualifies = segment.glare_score >= HIGH_RISK_SEGMENT_SCORE
        if qualifies:
            if not current_segments:
                current_start_distance_m = elapsed_distance_m
            current_segments.append(segment)
        elif current_segments:
            stretches.append(
                _make_high_glare_stretch(
                    current_segments,
                    current_start_distance_m,
                )
            )
            current_segments = []
        elapsed_distance_m += segment.segment_length_m

    if current_segments:
        stretches.append(
            _make_high_glare_stretch(current_segments, current_start_distance_m)
        )

    if not stretches:
        return None

    return max(
        enumerate(stretches),
        key=lambda item: (
            item[1].duration_s,
            item[1].distance_m,
            item[1].max_glare_score,
            -item[0],
        ),
    )[1]


def evaluate_route(
    route: Route,
    trip_start_moment: datetime,
    sun_position_at: SunPositionResolver = get_sun_position,
    *,
    include_segment_risks: bool = True,
) -> RouteEvaluation:
    if len(route.geometry) < 2:
        return _empty_evaluation(route)

    analysis_geometry = route_analysis_geometry(route.geometry)
    analysis_resampled = analysis_geometry != _dedupe_consecutive_coordinates(
        route.geometry
    )
    segments: list[tuple[Coordinates, Coordinates, float]] = []
    total_length_m = 0.0
    for start, end in zip(analysis_geometry, analysis_geometry[1:]):
        segment_length_m = haversine_distance_m(start, end)
        if segment_length_m <= 0.0:
            continue
        total_length_m += segment_length_m
        segments.append((start, end, segment_length_m))

    if total_length_m == 0.0:
        return _empty_evaluation(route)

    weighted_risk = 0.0
    aligned_distance_m = 0.0
    high_risk_distance_m = 0.0
    high_risk_duration_s = 0.0
    peak_glare_segment: RouteSegmentRisk | None = None
    peak_glare_distance_m: float | None = None
    all_segment_risks: list[RouteSegmentRisk] = []
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
            _segment_instant(trip_start_moment, midpoint_offset_s),
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

        segment_risk = RouteSegmentRisk(
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
        if (
            peak_glare_segment is None
            or segment_risk.glare_score > peak_glare_segment.glare_score
        ):
            peak_glare_segment = segment_risk
            peak_glare_distance_m = round(
                elapsed_distance_m + (segment_length_m / 2.0),
                2,
            )
        all_segment_risks.append(segment_risk)
        if include_segment_risks:
            segment_risks.append(segment_risk)
        elapsed_duration_s += segment_duration_s
        elapsed_distance_m += segment_length_m

    longest_stretch = _longest_high_glare_stretch(all_segment_risks)
    glare_score = (
        0.0
        if total_length_m == 0
        else clamp((weighted_risk / total_length_m) * 100.0, 0.0, 100.0)
    )
    peak_glare_score = (
        0.0 if peak_glare_segment is None else peak_glare_segment.glare_score
    )

    return RouteEvaluation(
        route=route,
        glare_score=round(glare_score, 2),
        total_length_m=total_length_m,
        peak_segment_score=peak_glare_score,
        aligned_distance_m=round(aligned_distance_m, 2),
        dominant_bearing_deg=(
            None if peak_glare_segment is None else peak_glare_segment.bearing_deg
        ),
        high_risk_distance_m=round(high_risk_distance_m, 2),
        high_risk_duration_s=round(high_risk_duration_s, 2),
        peak_risk_time_offset_min=(
            None
            if peak_glare_segment is None
            else round(peak_glare_segment.midpoint_offset_s / 60.0, 2)
        ),
        peak_risk_distance_m=peak_glare_distance_m,
        peak_risk_coordinates=(
            None
            if peak_glare_segment is None
            else peak_glare_segment.midpoint_coordinates
        ),
        peak_glare_segment=peak_glare_segment,
        peak_glare_coordinates=(
            None
            if peak_glare_segment is None
            else peak_glare_segment.midpoint_coordinates
        ),
        peak_glare_score=peak_glare_score,
        peak_glare_category=glare_category_for_score(peak_glare_score),
        longest_high_glare_stretch=longest_stretch,
        any_high_risk_segments=longest_stretch is not None,
        segment_risks=segment_risks,
        analysis_coordinate_count=len(analysis_geometry),
        original_coordinate_count=len(route.geometry),
        analysis_resampled=analysis_resampled,
        analysis_policy=f"max_analysis_coordinates={MAX_ANALYSIS_COORDINATES}",
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
