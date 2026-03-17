from __future__ import annotations

import logging
import math

from src.models import Route, RouteEvaluation, SunPosition
from src.utils import angular_difference_degrees, calculate_bearing, clamp, compass_direction, describe_sun_height, haversine_distance_m

logger = logging.getLogger("sunrouter.scoring")


def glare_alignment_factor(angle_difference_deg: float) -> float:
    diff_rad = math.radians(angle_difference_deg)
    return clamp(((math.cos(diff_rad) + 1.0) / 2.0) ** 3, 0.0, 1.0)


def evaluate_route(route: Route, sun_position: SunPosition) -> RouteEvaluation:
    if len(route.geometry) < 2:
        return RouteEvaluation(
            route=route,
            glare_score=0.0,
            total_length_m=0.0,
            peak_segment_score=0.0,
            aligned_distance_m=0.0,
        )

    total_length_m = 0.0
    weighted_risk = 0.0
    peak_segment_score = 0.0
    aligned_distance_m = 0.0
    dominant_bearing_deg: float | None = None

    elevation_factor = 0.0
    if sun_position.elevation_deg > 0.0:
        elevation_factor = clamp((45.0 - sun_position.elevation_deg) / 45.0, 0.0, 1.0)

    for start, end in zip(route.geometry, route.geometry[1:]):
        segment_length_m = haversine_distance_m(start, end)
        if segment_length_m <= 0:
            continue

        total_length_m += segment_length_m
        if elevation_factor == 0.0:
            continue

        segment_bearing = calculate_bearing(start, end)
        angle_difference = angular_difference_degrees(segment_bearing, sun_position.azimuth_deg)
        angular_factor = glare_alignment_factor(angle_difference)
        segment_score = elevation_factor * angular_factor
        weighted_segment_score = segment_score * segment_length_m
        weighted_risk += weighted_segment_score

        if weighted_segment_score > peak_segment_score:
            peak_segment_score = weighted_segment_score
            dominant_bearing_deg = segment_bearing

        if angle_difference <= 45.0:
            aligned_distance_m += segment_length_m

    glare_score = 0.0 if total_length_m == 0 else clamp((weighted_risk / total_length_m) * 100.0, 0.0, 100.0)

    return RouteEvaluation(
        route=route,
        glare_score=round(glare_score, 2),
        total_length_m=total_length_m,
        peak_segment_score=round(peak_segment_score, 2),
        aligned_distance_m=round(aligned_distance_m, 2),
        dominant_bearing_deg=dominant_bearing_deg,
    )


def rank_routes(routes: list[Route], sun_position: SunPosition) -> list[RouteEvaluation]:
    evaluations = [evaluate_route(route, sun_position) for route in routes]
    ranked = sorted(
        evaluations,
        key=lambda evaluation: (evaluation.glare_score, evaluation.route.metrics.duration_s),
    )
    logger.info(
        "Scored %d route(s) with sun azimuth=%.1f elevation=%.1f; best glare score=%.1f",
        len(ranked),
        sun_position.azimuth_deg,
        sun_position.elevation_deg,
        ranked[0].glare_score if ranked else 0.0,
    )
    return ranked


def explain_recommendation(
    recommended: RouteEvaluation,
    alternatives: list[RouteEvaluation],
    sun_position: SunPosition,
) -> str:
    if sun_position.elevation_deg <= 0:
        return "The sun is below the horizon at the selected time, so glare risk is minimal."

    direction = compass_direction(sun_position.azimuth_deg)
    height = describe_sun_height(sun_position.elevation_deg)

    if not alternatives:
        return (
            f"This route is the only candidate returned. It still highlights potential glare on "
            f"{direction} segments while the sun is {height}."
        )

    comparison = alternatives[0].glare_score - recommended.glare_score
    if comparison >= 15:
        modifier = "meaningfully"
    elif comparison >= 5:
        modifier = "moderately"
    else:
        modifier = "slightly"

    return (
        f"This route {modifier} reduces sun glare by avoiding long {direction} segments "
        f"while the sun is {height}."
    )
