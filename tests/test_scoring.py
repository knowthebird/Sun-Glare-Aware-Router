from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.models import Coordinates, Route, RouteMetrics, SunPosition
from src.scoring import (
    evaluate_route,
    explain_recommendation,
    glare_alignment_factor,
    rank_routes,
)


def make_route(
    name: str, geometry: list[Coordinates], *, duration_s: float = 600.0
) -> Route:
    return Route(
        route_id=name,
        geometry=geometry,
        metrics=RouteMetrics(distance_m=1000.0, duration_s=duration_s),
    )


def test_glare_alignment_factor_favors_sun_facing_segments() -> None:
    aligned = glare_alignment_factor(0.0)
    perpendicular = glare_alignment_factor(90.0)
    opposite = glare_alignment_factor(180.0)

    assert aligned == 1.0
    assert 0.0 < perpendicular < aligned
    assert opposite == 0.0


def test_evaluate_route_returns_zero_glare_at_night() -> None:
    route = make_route(
        "eastbound",
        [Coordinates(lat=0.0, lon=0.0), Coordinates(lat=0.0, lon=0.01)],
    )
    trip_start = datetime.fromisoformat("2026-03-18T07:00:00+00:00")

    result = evaluate_route(
        route,
        trip_start,
        sun_position_at=lambda moment, coordinates: SunPosition(
            azimuth_deg=90.0, elevation_deg=-5.0
        ),
    )

    assert result.glare_score == 0.0
    assert result.total_length_m > 0.0
    assert result.high_risk_duration_s == 0.0
    assert len(result.segment_risks) == 1
    assert result.segment_risks[0].sun_position.elevation_deg == -5.0


def test_evaluate_route_normalizes_scores_between_zero_and_one_hundred() -> None:
    eastbound = make_route(
        "eastbound",
        [Coordinates(lat=0.0, lon=0.0), Coordinates(lat=0.0, lon=0.02)],
    )
    northbound = make_route(
        "northbound",
        [Coordinates(lat=0.0, lon=0.0), Coordinates(lat=0.02, lon=0.0)],
    )
    trip_start = datetime.fromisoformat("2026-03-18T07:00:00+00:00")

    east_result = evaluate_route(
        eastbound,
        trip_start,
        sun_position_at=lambda moment, coordinates: SunPosition(
            azimuth_deg=90.0, elevation_deg=10.0
        ),
    )
    north_result = evaluate_route(
        northbound,
        trip_start,
        sun_position_at=lambda moment, coordinates: SunPosition(
            azimuth_deg=90.0, elevation_deg=10.0
        ),
    )

    assert 0.0 <= east_result.glare_score <= 100.0
    assert 0.0 <= north_result.glare_score <= 100.0
    assert east_result.glare_score > north_result.glare_score


def test_rank_routes_returns_empty_list_for_missing_routes() -> None:
    trip_start = datetime.fromisoformat("2026-03-18T07:00:00+00:00")

    assert rank_routes([], trip_start) == []


def test_evaluate_route_handles_missing_geometry() -> None:
    route = make_route("missing", [])
    trip_start = datetime.fromisoformat("2026-03-18T07:00:00+00:00")

    result = evaluate_route(route, trip_start)

    assert result.glare_score == 0.0
    assert result.total_length_m == 0.0
    assert result.segment_risks == []


def test_dynamic_scoring_differs_from_departure_only_scoring_on_long_routes() -> None:
    route = make_route(
        "long-eastbound",
        [
            Coordinates(lat=0.0, lon=0.0),
            Coordinates(lat=0.0, lon=0.01),
            Coordinates(lat=0.0, lon=0.02),
            Coordinates(lat=0.0, lon=0.03),
        ],
        duration_s=1800.0,
    )
    trip_start = datetime.fromisoformat("2026-03-18T07:00:00+00:00")

    dynamic_result = evaluate_route(
        route,
        trip_start,
        sun_position_at=lambda moment, coordinates: SunPosition(
            azimuth_deg=0.0 if moment.minute < 20 else 90.0,
            elevation_deg=12.0,
        ),
    )
    static_result = evaluate_route(
        route,
        trip_start,
        sun_position_at=lambda moment, coordinates: SunPosition(
            azimuth_deg=0.0, elevation_deg=12.0
        ),
    )

    assert dynamic_result.glare_score > static_result.glare_score
    assert dynamic_result.high_risk_duration_s > 0.0


def test_evaluate_route_reports_peak_risk_in_the_middle_of_the_trip() -> None:
    route = make_route(
        "changing-risk",
        [
            Coordinates(lat=0.0, lon=0.0),
            Coordinates(lat=0.0, lon=0.01),
            Coordinates(lat=0.0, lon=0.02),
            Coordinates(lat=0.0, lon=0.03),
        ],
        duration_s=1800.0,
    )
    trip_start = datetime.fromisoformat("2026-03-18T07:00:00+00:00")

    result = evaluate_route(
        route,
        trip_start,
        sun_position_at=lambda moment, coordinates: SunPosition(
            azimuth_deg=90.0,
            elevation_deg=30.0
            if moment.minute < 10
            else (8.0 if moment.minute < 20 else -5.0),
        ),
    )

    assert result.peak_risk_time_offset_min == 15.0
    assert result.high_risk_duration_s == 600.0
    assert result.peak_risk_coordinates == Coordinates(lat=0.0, lon=0.015)


def test_rank_routes_accounts_for_when_the_risky_segment_happens() -> None:
    safer_late_route = make_route(
        "safer-late",
        [
            Coordinates(lat=0.0, lon=0.0),
            Coordinates(lat=0.01, lon=0.0),
            Coordinates(lat=0.01, lon=0.01),
        ],
        duration_s=1200.0,
    )
    riskier_early_route = make_route(
        "riskier-early",
        [
            Coordinates(lat=0.0, lon=0.0),
            Coordinates(lat=0.0, lon=0.01),
            Coordinates(lat=0.01, lon=0.01),
        ],
        duration_s=1200.0,
    )
    trip_start = datetime.fromisoformat("2026-03-18T07:00:00+00:00")

    ranked = rank_routes(
        [riskier_early_route, safer_late_route],
        trip_start,
        sun_position_at=lambda moment, coordinates: SunPosition(
            azimuth_deg=90.0,
            elevation_deg=5.0 if moment.minute < 10 else 25.0,
        ),
    )

    assert [item.route.route_id for item in ranked] == ["safer-late", "riskier-early"]


def test_rank_routes_breaks_ties_by_shorter_distance() -> None:
    shorter_route = Route(
        route_id="shorter",
        geometry=[Coordinates(lat=0.0, lon=0.0), Coordinates(lat=0.01, lon=0.0)],
        metrics=RouteMetrics(distance_m=900.0, duration_s=800.0),
    )
    longer_route = Route(
        route_id="longer",
        geometry=[Coordinates(lat=0.0, lon=0.0), Coordinates(lat=0.01, lon=0.0)],
        metrics=RouteMetrics(distance_m=1200.0, duration_s=700.0),
    )
    trip_start = datetime.fromisoformat("2026-03-18T07:00:00+00:00")

    ranked = rank_routes(
        [longer_route, shorter_route],
        trip_start,
        sun_position_at=lambda moment, coordinates: SunPosition(
            azimuth_deg=90.0,
            elevation_deg=-5.0,
        ),
    )

    assert [item.route.route_id for item in ranked] == ["shorter", "longer"]


def test_explain_recommendation_is_honest_when_only_one_route_exists() -> None:
    route = make_route(
        "only-route",
        [Coordinates(lat=0.0, lon=0.0), Coordinates(lat=0.0, lon=0.02)],
        duration_s=1800.0,
    )
    trip_start = datetime.fromisoformat("2026-03-18T07:00:00+00:00")
    evaluation = evaluate_route(
        route,
        trip_start,
        sun_position_at=lambda moment, coordinates: SunPosition(
            azimuth_deg=90.0,
            elevation_deg=8.0,
        ),
    )

    explanation = explain_recommendation(
        evaluation,
        [],
        departure_sun_position=SunPosition(azimuth_deg=90.0, elevation_deg=10.0),
    )

    assert "Solo se ha encontrado una ruta candidata" in explanation
    assert "análisis" in explanation


def test_explain_recommendation_supports_english() -> None:
    route = make_route(
        "only-route",
        [Coordinates(lat=0.0, lon=0.0), Coordinates(lat=0.0, lon=0.02)],
        duration_s=1800.0,
    )
    trip_start = datetime.fromisoformat("2026-03-18T07:00:00+00:00")
    evaluation = evaluate_route(
        route,
        trip_start,
        sun_position_at=lambda moment, coordinates: SunPosition(
            azimuth_deg=90.0,
            elevation_deg=8.0,
        ),
    )

    explanation = explain_recommendation(
        evaluation,
        [],
        departure_sun_position=SunPosition(azimuth_deg=90.0, elevation_deg=10.0),
        language="en",
    )

    assert "Only one candidate route was found" in explanation


def test_scoring_source_uses_utf8_strings_without_hex_escapes() -> None:
    source = Path("src/scoring.py").read_text(encoding="utf-8")

    assert "\\x" not in source
