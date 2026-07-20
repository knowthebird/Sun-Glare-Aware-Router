from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from src.models import Coordinates, Route, RouteMetrics, SunPosition
from src.scoring import (
    HIGH_RISK_SEGMENT_SCORE,
    MAX_ANALYSIS_COORDINATES,
    evaluate_route,
    explain_recommendation,
    glare_alignment_factor,
    rank_routes,
    route_analysis_geometry,
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


def test_segment_times_remain_monotonic_for_fifty_hour_route() -> None:
    route = make_route(
        "cross-country-style",
        [
            Coordinates(lat=40.0, lon=-74.0),
            Coordinates(lat=41.0, lon=-90.0),
            Coordinates(lat=39.0, lon=-105.0),
            Coordinates(lat=37.0, lon=-122.0),
        ],
        duration_s=50 * 60 * 60,
    )
    trip_start = datetime.fromisoformat("2026-07-19T08:00:00+00:00")
    instants: list[datetime] = []

    result = evaluate_route(
        route,
        trip_start,
        sun_position_at=lambda moment, coordinates: (
            instants.append(moment)
            or SunPosition(azimuth_deg=90.0, elevation_deg=-5.0)
        ),
    )

    offsets = [segment.midpoint_offset_s for segment in result.segment_risks]
    assert offsets == sorted(offsets)
    assert result.segment_risks[-1].start_offset_s + result.segment_risks[
        -1
    ].estimated_duration_s == 50 * 60 * 60
    assert instants == sorted(instants)
    assert instants[-1] > trip_start + timedelta(days=1)


def test_segment_instants_use_utc_elapsed_time_across_spring_dst() -> None:
    route = make_route(
        "dst",
        [
            Coordinates(lat=40.0, lon=-74.0),
            Coordinates(lat=40.1, lon=-74.0),
            Coordinates(lat=40.2, lon=-74.0),
        ],
        duration_s=4 * 60 * 60,
    )
    trip_start = datetime(2026, 3, 8, 0, 30, tzinfo=ZoneInfo("America/New_York"))
    instants: list[datetime] = []

    evaluate_route(
        route,
        trip_start,
        sun_position_at=lambda moment, coordinates: (
            instants.append(moment)
            or SunPosition(azimuth_deg=90.0, elevation_deg=-5.0)
        ),
    )

    assert [moment.tzinfo for moment in instants] == [UTC, UTC]
    assert [moment.isoformat() for moment in instants] == [
        "2026-03-08T06:30:00+00:00",
        "2026-03-08T08:30:00+00:00",
    ]


def test_same_physical_instant_scores_same_in_different_display_timezones() -> None:
    route = make_route(
        "timezone-display",
        [Coordinates(lat=40.0, lon=-74.0), Coordinates(lat=40.0, lon=-73.0)],
        duration_s=3600.0,
    )
    utc_start = datetime.fromisoformat("2026-07-19T12:00:00+00:00")
    eastern_start = utc_start.astimezone(ZoneInfo("America/New_York"))

    def resolver(moment: datetime, coordinates: Coordinates) -> SunPosition:
        assert moment.tzinfo is UTC
        return SunPosition(
            azimuth_deg=90.0 if moment == datetime(2026, 7, 19, 12, 30, tzinfo=UTC) else 0.0,
            elevation_deg=10.0,
        )

    assert evaluate_route(route, utc_start, sun_position_at=resolver).glare_score == (
        evaluate_route(route, eastern_start, sun_position_at=resolver).glare_score
    )


def test_large_geometry_uses_bounded_analysis_representation() -> None:
    geometry = [
        Coordinates(lat=39.0 + (index * 0.0001), lon=-77.0 + (index * 0.0002))
        for index in range(2_500)
    ]
    route = Route(
        route_id="large",
        geometry=geometry,
        metrics=RouteMetrics(distance_m=500_000.0, duration_s=26 * 60 * 60),
    )

    analysis_geometry = route_analysis_geometry(route.geometry)
    result = evaluate_route(
        route,
        datetime.fromisoformat("2026-07-19T08:00:00+00:00"),
        sun_position_at=lambda moment, coordinates: SunPosition(
            azimuth_deg=90.0,
            elevation_deg=-5.0,
        ),
    )

    assert len(analysis_geometry) <= MAX_ANALYSIS_COORDINATES
    assert analysis_geometry[0] == geometry[0]
    assert analysis_geometry[-1] == geometry[-1]
    assert result.route.geometry == geometry
    assert result.analysis_resampled is True
    assert len(result.segment_risks) <= MAX_ANALYSIS_COORDINATES - 1


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


def test_peak_glare_prefers_short_severe_segment_over_long_medium_area() -> None:
    route = make_route(
        "long-medium-short-severe",
        [
            Coordinates(lat=0.0, lon=0.0),
            Coordinates(lat=0.0, lon=0.09),
            Coordinates(lat=0.0, lon=0.18),
            Coordinates(lat=0.0, lon=0.1805),
        ],
        duration_s=1800.0,
    )
    trip_start = datetime.fromisoformat("2026-03-18T07:00:00+00:00")

    result = evaluate_route(
        route,
        trip_start,
        sun_position_at=lambda moment, coordinates: SunPosition(
            azimuth_deg=90.0,
            elevation_deg=5.0 if coordinates.lon > 0.18 else 30.0,
        ),
    )

    assert result.peak_glare_segment is not None
    assert result.peak_glare_segment.midpoint_coordinates == Coordinates(
        lat=0.0,
        lon=0.18025,
    )
    assert result.peak_glare_score > 80.0
    assert result.peak_segment_score == result.peak_glare_score
    assert result.longest_high_glare_stretch is not None
    assert len(result.longest_high_glare_stretch.segments) == 1
    assert result.longest_high_glare_stretch.peak_segment == result.peak_glare_segment
    assert all(
        segment.glare_score < HIGH_RISK_SEGMENT_SCORE
        for segment in result.segment_risks[:2]
    )


def test_peak_glare_and_longest_high_glare_stretch_can_differ() -> None:
    route = make_route(
        "short-severe-long-high",
        [
            Coordinates(lat=0.0, lon=0.0),
            Coordinates(lat=0.0, lon=0.005),
            Coordinates(lat=0.0, lon=0.006),
            Coordinates(lat=0.0, lon=0.016),
            Coordinates(lat=0.0, lon=0.026),
            Coordinates(lat=0.0, lon=0.036),
        ],
        duration_s=1800.0,
    )
    trip_start = datetime.fromisoformat("2026-03-18T07:00:00+00:00")

    result = evaluate_route(
        route,
        trip_start,
        sun_position_at=lambda moment, coordinates: SunPosition(
            azimuth_deg=90.0,
            elevation_deg=(
                5.0
                if coordinates.lon < 0.005
                else (30.0 if coordinates.lon < 0.006 else 20.0)
            ),
        ),
    )

    assert result.peak_glare_segment is not None
    assert result.longest_high_glare_stretch is not None
    assert result.peak_glare_segment.midpoint_coordinates == Coordinates(
        lat=0.0,
        lon=0.0025,
    )
    assert result.longest_high_glare_stretch.start_coordinates == Coordinates(
        lat=0.0,
        lon=0.006,
    )
    assert result.longest_high_glare_stretch.end_coordinates == Coordinates(
        lat=0.0,
        lon=0.036,
    )
    assert result.longest_high_glare_stretch.peak_segment != result.peak_glare_segment
    assert result.longest_high_glare_stretch.duration_s > (
        result.peak_glare_segment.estimated_duration_s
    )
    assert result.longest_high_glare_stretch.max_glare_score < result.peak_glare_score


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
