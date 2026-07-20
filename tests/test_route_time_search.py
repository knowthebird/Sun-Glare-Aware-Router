from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.models import Coordinates, Route, RouteMetrics, SunPosition
from src.route_time_search import evaluate_route_time_window


def make_route(duration_s: float = 1800.0) -> Route:
    return Route(
        route_id="selected",
        geometry=[
            Coordinates(lat=0.0, lon=0.0),
            Coordinates(lat=0.0, lon=0.01),
            Coordinates(lat=0.0, lon=0.02),
        ],
        metrics=RouteMetrics(distance_m=2000.0, duration_s=duration_s),
    )


def zero_glare_resolver(moment: datetime, coordinates: Coordinates) -> SunPosition:
    return SunPosition(azimuth_deg=90.0, elevation_deg=-5.0)


def iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def test_departure_window_samples_in_ten_minute_increments() -> None:
    route = make_route(duration_s=1800.0)

    result = evaluate_route_time_window(
        route,
        iso("2026-03-18T08:00:00+00:00"),
        iso("2026-03-18T08:20:00+00:00"),
        search_mode="departure",
        sun_position_at=zero_glare_resolver,
    )

    assert [candidate.requested_time for candidate in result.candidates] == [
        iso("2026-03-18T08:00:00+00:00"),
        iso("2026-03-18T08:10:00+00:00"),
        iso("2026-03-18T08:20:00+00:00"),
    ]
    assert [candidate.departure_time for candidate in result.candidates] == [
        iso("2026-03-18T08:00:00+00:00"),
        iso("2026-03-18T08:10:00+00:00"),
        iso("2026-03-18T08:20:00+00:00"),
    ]
    assert [candidate.arrival_time for candidate in result.candidates] == [
        iso("2026-03-18T08:30:00+00:00"),
        iso("2026-03-18T08:40:00+00:00"),
        iso("2026-03-18T08:50:00+00:00"),
    ]


def test_arrival_window_samples_arrivals_and_derives_departures() -> None:
    route = make_route(duration_s=1800.0)

    result = evaluate_route_time_window(
        route,
        iso("2026-03-18T09:00:00+00:00"),
        iso("2026-03-18T09:20:00+00:00"),
        search_mode="arrival",
        sun_position_at=zero_glare_resolver,
    )

    assert [candidate.requested_time for candidate in result.candidates] == [
        iso("2026-03-18T09:00:00+00:00"),
        iso("2026-03-18T09:10:00+00:00"),
        iso("2026-03-18T09:20:00+00:00"),
    ]
    assert [candidate.departure_time for candidate in result.candidates] == [
        iso("2026-03-18T08:30:00+00:00"),
        iso("2026-03-18T08:40:00+00:00"),
        iso("2026-03-18T08:50:00+00:00"),
    ]
    assert [candidate.arrival_time for candidate in result.candidates] == [
        iso("2026-03-18T09:00:00+00:00"),
        iso("2026-03-18T09:10:00+00:00"),
        iso("2026-03-18T09:20:00+00:00"),
    ]


def test_arrival_window_can_calculate_departure_on_previous_date() -> None:
    route = make_route(duration_s=2400.0)

    result = evaluate_route_time_window(
        route,
        iso("2026-03-19T00:10:00+00:00"),
        iso("2026-03-19T00:10:00+00:00"),
        search_mode="arrival",
        sun_position_at=zero_glare_resolver,
    )

    candidate = result.recommended_candidate
    assert candidate.requested_time == iso("2026-03-19T00:10:00+00:00")
    assert candidate.arrival_time == iso("2026-03-19T00:10:00+00:00")
    assert candidate.departure_time == iso("2026-03-18T23:30:00+00:00")


def test_departure_window_preserves_twenty_six_hour_duration() -> None:
    route = make_route(duration_s=26 * 60 * 60)

    result = evaluate_route_time_window(
        route,
        iso("2026-07-19T08:00:00+00:00"),
        iso("2026-07-19T08:00:00+00:00"),
        search_mode="departure",
        sun_position_at=zero_glare_resolver,
    )

    candidate = result.recommended_candidate
    assert candidate.departure_time == iso("2026-07-19T08:00:00+00:00")
    assert candidate.arrival_time == iso("2026-07-20T10:00:00+00:00")


def test_departure_window_preserves_fifty_hour_duration() -> None:
    route = make_route(duration_s=50 * 60 * 60)

    result = evaluate_route_time_window(
        route,
        iso("2026-12-31T23:30:00+00:00"),
        iso("2026-12-31T23:30:00+00:00"),
        search_mode="departure",
        sun_position_at=zero_glare_resolver,
    )

    assert result.recommended_candidate.arrival_time == iso(
        "2027-01-03T01:30:00+00:00"
    )


def test_arrival_window_can_calculate_departure_several_days_earlier() -> None:
    route = make_route(duration_s=50 * 60 * 60)

    result = evaluate_route_time_window(
        route,
        iso("2026-07-21T10:15:00+00:00"),
        iso("2026-07-21T10:15:00+00:00"),
        search_mode="arrival",
        sun_position_at=zero_glare_resolver,
    )

    assert result.recommended_candidate.departure_time == iso(
        "2026-07-19T08:15:00+00:00"
    )


def test_departure_window_uses_elapsed_utc_across_dst_transition() -> None:
    route = make_route(duration_s=4 * 60 * 60)

    result = evaluate_route_time_window(
        route,
        datetime(2026, 3, 8, 0, 30, tzinfo=ZoneInfo("America/New_York")),
        datetime(2026, 3, 8, 0, 30, tzinfo=ZoneInfo("America/New_York")),
        search_mode="departure",
        sun_position_at=zero_glare_resolver,
    )

    assert result.recommended_candidate.arrival_time.isoformat() == (
        "2026-03-08T05:30:00-04:00"
    )


def test_candidate_times_include_start_and_stop_before_non_increment_end() -> None:
    route = make_route()

    result = evaluate_route_time_window(
        route,
        iso("2026-03-18T08:03:00+00:00"),
        iso("2026-03-18T08:25:00+00:00"),
        search_mode="departure",
        sun_position_at=zero_glare_resolver,
    )

    assert [candidate.requested_time for candidate in result.candidates] == [
        iso("2026-03-18T08:03:00+00:00"),
        iso("2026-03-18T08:13:00+00:00"),
        iso("2026-03-18T08:23:00+00:00"),
    ]


def test_ranking_uses_high_risk_duration_before_time_tie_breaker() -> None:
    route = make_route(duration_s=600.0)

    def resolver(moment: datetime, coordinates: Coordinates) -> SunPosition:
        elevation_by_time = {
            iso("2026-03-18T08:02:30+00:00"): 27.0,
            iso("2026-03-18T08:07:30+00:00"): 36.0,
            iso("2026-03-18T08:12:30+00:00"): 31.5,
            iso("2026-03-18T08:17:30+00:00"): 31.5,
        }
        return SunPosition(
            azimuth_deg=90.0,
            elevation_deg=elevation_by_time[moment],
        )

    result = evaluate_route_time_window(
        route,
        iso("2026-03-18T08:00:00+00:00"),
        iso("2026-03-18T08:10:00+00:00"),
        search_mode="departure",
        sun_position_at=resolver,
    )

    assert [candidate.glare_score for candidate in result.ranked_candidates] == [
        30.0,
        30.0,
    ]
    assert [candidate.requested_time for candidate in result.ranked_candidates] == [
        iso("2026-03-18T08:10:00+00:00"),
        iso("2026-03-18T08:00:00+00:00"),
    ]
    assert [
        candidate.high_risk_duration_s for candidate in result.ranked_candidates
    ] == [
        0.0,
        300.0,
    ]


def test_ranking_uses_earliest_requested_time_as_final_tie_breaker() -> None:
    route = make_route()

    result = evaluate_route_time_window(
        route,
        iso("2026-03-18T08:00:00+00:00"),
        iso("2026-03-18T08:20:00+00:00"),
        search_mode="departure",
        sun_position_at=zero_glare_resolver,
    )

    assert [candidate.requested_time for candidate in result.ranked_candidates] == [
        iso("2026-03-18T08:00:00+00:00"),
        iso("2026-03-18T08:10:00+00:00"),
        iso("2026-03-18T08:20:00+00:00"),
    ]


def test_invalid_or_reversed_windows_are_rejected() -> None:
    route = make_route()

    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate_route_time_window(
            route,
            datetime(2026, 3, 18, 8, 0),
            iso("2026-03-18T08:20:00+00:00"),
            search_mode="departure",
        )

    with pytest.raises(ValueError, match="greater than or equal"):
        evaluate_route_time_window(
            route,
            iso("2026-03-18T08:20:00+00:00"),
            iso("2026-03-18T08:00:00+00:00"),
            search_mode="departure",
        )

    with pytest.raises(ValueError, match="maximum"):
        evaluate_route_time_window(
            route,
            iso("2026-03-18T08:00:00+00:00"),
            iso("2026-03-18T08:30:00+00:00"),
            search_mode="departure",
            max_window=timedelta(minutes=20),
        )


def test_invalid_search_mode_and_route_duration_are_rejected() -> None:
    route = make_route()

    with pytest.raises(ValueError, match="search_mode"):
        evaluate_route_time_window(
            route,
            iso("2026-03-18T08:00:00+00:00"),
            iso("2026-03-18T08:20:00+00:00"),
            search_mode="commute",  # type: ignore[arg-type]
        )

    with pytest.raises(ValueError, match="route duration"):
        evaluate_route_time_window(
            make_route(duration_s=-1.0),
            iso("2026-03-18T08:00:00+00:00"),
            iso("2026-03-18T08:20:00+00:00"),
            search_mode="departure",
        )


def test_lowest_glare_candidate_is_selected_with_fake_solar_resolver() -> None:
    route = make_route(duration_s=600.0)

    def resolver(moment: datetime, coordinates: Coordinates) -> SunPosition:
        elevation_by_time = {
            iso("2026-03-18T08:02:30+00:00"): 5.0,
            iso("2026-03-18T08:07:30+00:00"): 5.0,
            iso("2026-03-18T08:12:30+00:00"): -5.0,
            iso("2026-03-18T08:17:30+00:00"): -5.0,
            iso("2026-03-18T08:22:30+00:00"): 20.0,
            iso("2026-03-18T08:27:30+00:00"): 20.0,
        }
        return SunPosition(
            azimuth_deg=90.0,
            elevation_deg=elevation_by_time[moment],
        )

    result = evaluate_route_time_window(
        route,
        iso("2026-03-18T08:00:00+00:00"),
        iso("2026-03-18T08:20:00+00:00"),
        search_mode="departure",
        sun_position_at=resolver,
    )

    assert result.recommended_candidate.requested_time == iso(
        "2026-03-18T08:10:00+00:00"
    )
    assert result.recommended_candidate.glare_score == 0.0
    assert result.recommended_candidate.route_evaluation.segment_risks
