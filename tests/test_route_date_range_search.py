from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest

from src.models import Coordinates, Route, RouteEvaluation, RouteMetrics, SunPosition
from src.route_time_search import (
    evaluate_route_date_range,
    validate_adaptive_date_range_against_exact,
)


def make_route(duration_s: float = 1800.0) -> Route:
    return Route(
        route_id="selected",
        geometry=[
            Coordinates(lat=0.0, lon=0.0),
            Coordinates(lat=0.0, lon=0.01),
        ],
        metrics=RouteMetrics(distance_m=1000.0, duration_s=duration_s),
    )


def fake_evaluation(
    route: Route, score: float, *, high_risk_s: float = 0.0
) -> RouteEvaluation:
    return RouteEvaluation(
        route=route,
        glare_score=round(score, 2),
        total_length_m=route.metrics.distance_m,
        peak_segment_score=round(score, 2),
        aligned_distance_m=0.0,
        high_risk_distance_m=high_risk_s,
        high_risk_duration_s=high_risk_s,
        segment_risks=[],
    )


class FakeScorer:
    def __init__(self, start_date: date, target_day: int, target_minute: int) -> None:
        self.start_date = start_date
        self.target_day = target_day
        self.target_minute = target_minute
        self.calls: list[tuple[datetime, bool]] = []

    def __call__(
        self,
        route: Route,
        requested_time: datetime,
        departure_time: datetime,
        arrival_time: datetime,
        include_segment_risks: bool,
    ) -> RouteEvaluation:
        self.calls.append((departure_time, include_segment_risks))
        day_index = (requested_time.date() - self.start_date).days
        minute = (requested_time.hour * 60) + requested_time.minute
        score = abs(day_index - self.target_day) + (
            abs(minute - self.target_minute) / 100.0
        )
        return fake_evaluation(route, score)


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def minute_of_day(value: time) -> int:
    return (value.hour * 60) + value.minute


def test_exact_range_evaluates_every_candidate_and_reports_metadata() -> None:
    route = make_route()
    scorer = FakeScorer(date(2026, 1, 1), target_day=1, target_minute=490)

    result = evaluate_route_date_range(
        route,
        date(2026, 1, 1),
        date(2026, 1, 2),
        time(8, 0),
        time(8, 20),
        search_mode="departure",
        timezone_name="UTC",
        evaluation_budget=10,
        route_evaluator=scorer,
    )

    assert result.exact is True
    assert result.search_strategy == "exact"
    assert result.unique_evaluations == 6
    assert len(result.candidate_summaries) == 6
    assert result.diagnostics.candidate_count_at_final_resolution == 6
    assert result.final_date_resolution_days == 1
    assert result.final_time_resolution == timedelta(minutes=10)
    assert result.budget_outcome == "within_budget"
    assert result.recommended_candidate.requested_time == dt(
        "2026-01-02T08:10:00+00:00"
    )
    assert any(include_details for _, include_details in scorer.calls)


def test_adaptive_range_samples_less_than_large_candidate_space() -> None:
    route = make_route()
    scorer = FakeScorer(date(2026, 1, 1), target_day=20, target_minute=680)

    result = evaluate_route_date_range(
        route,
        date(2026, 1, 1),
        date(2026, 2, 15),
        time(6, 0),
        time(18, 0),
        search_mode="departure",
        timezone_name="UTC",
        evaluation_budget=180,
        route_evaluator=scorer,
    )

    assert result.exact is False
    assert result.search_strategy == "adaptive"
    assert result.unique_evaluations <= 180
    assert (
        result.unique_evaluations
        < result.diagnostics.candidate_count_at_final_resolution
    )
    assert len(result.candidate_summaries) == result.unique_evaluations


def test_adaptive_search_discovers_known_best_basin() -> None:
    route = make_route()
    scorer = FakeScorer(date(2026, 1, 1), target_day=21, target_minute=680)

    result = evaluate_route_date_range(
        route,
        date(2026, 1, 1),
        date(2026, 3, 31),
        time(6, 0),
        time(18, 0),
        search_mode="departure",
        timezone_name="UTC",
        evaluation_budget=700,
        route_evaluator=scorer,
    )

    assert result.budget_outcome == "within_budget"
    assert result.recommended_candidate.requested_time == dt(
        "2026-01-22T11:20:00+00:00"
    )
    assert result.final_date_resolution_days == 1
    assert result.final_time_resolution == timedelta(minutes=10)


def test_adaptive_search_retains_multiple_promising_basins() -> None:
    route = make_route()
    start = date(2026, 1, 1)
    basins = [(20, 8 * 60), (70, 17 * 60)]

    def scorer(
        route: Route,
        requested_time: datetime,
        departure_time: datetime,
        arrival_time: datetime,
        include_segment_risks: bool,
    ) -> RouteEvaluation:
        day_index = (requested_time.date() - start).days
        minute = (requested_time.hour * 60) + requested_time.minute
        score = min(
            abs(day_index - basin_day) + abs(minute - basin_minute) / 100.0
            for basin_day, basin_minute in basins
        )
        return fake_evaluation(route, score)

    result = evaluate_route_date_range(
        route,
        start,
        date(2026, 3, 31),
        time(6, 0),
        time(18, 0),
        search_mode="departure",
        timezone_name="UTC",
        evaluation_budget=800,
        route_evaluator=scorer,
    )

    top_requested = [
        candidate.requested_time for candidate in result.top_alternative_candidates
    ]
    top_requested.append(result.recommended_candidate.requested_time)
    assert result.diagnostics.retained_basin_count >= 2
    assert any(value.date() == date(2026, 1, 21) for value in top_requested)
    assert any(value.date() == date(2026, 3, 12) for value in top_requested)


def test_adaptive_search_refines_dates() -> None:
    route = make_route()
    scorer = FakeScorer(date(2026, 1, 1), target_day=25, target_minute=720)

    result = evaluate_route_date_range(
        route,
        date(2026, 1, 1),
        date(2026, 3, 20),
        time(6, 0),
        time(18, 0),
        search_mode="departure",
        timezone_name="UTC",
        evaluation_budget=700,
        route_evaluator=scorer,
    )

    assert result.recommended_candidate.requested_time.date() == date(2026, 1, 26)


def test_adaptive_search_refines_times() -> None:
    route = make_route()
    scorer = FakeScorer(date(2026, 1, 1), target_day=20, target_minute=640)

    result = evaluate_route_date_range(
        route,
        date(2026, 1, 1),
        date(2026, 3, 1),
        time(6, 0),
        time(18, 0),
        search_mode="departure",
        timezone_name="UTC",
        evaluation_budget=700,
        route_evaluator=scorer,
    )

    assert result.recommended_candidate.requested_time.time() == time(10, 40)


def test_search_includes_date_and_time_boundaries() -> None:
    route = make_route()
    scorer = FakeScorer(date(2026, 1, 1), target_day=59, target_minute=18 * 60)

    result = evaluate_route_date_range(
        route,
        date(2026, 1, 1),
        date(2026, 3, 1),
        time(6, 0),
        time(18, 0),
        search_mode="departure",
        timezone_name="UTC",
        evaluation_budget=250,
        route_evaluator=scorer,
    )

    assert result.recommended_candidate.requested_time == dt(
        "2026-03-01T18:00:00+00:00"
    )


def test_date_range_results_are_deterministic() -> None:
    route = make_route()
    kwargs = dict(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 2, 28),
        daily_earliest_time=time(6, 0),
        daily_latest_time=time(18, 0),
        search_mode="departure",
        timezone_name="UTC",
        evaluation_budget=400,
        route_evaluator=FakeScorer(date(2026, 1, 1), target_day=24, target_minute=610),
    )

    first = evaluate_route_date_range(route, **kwargs)
    second = evaluate_route_date_range(route, **kwargs)

    assert [item.requested_time for item in first.ranked_candidate_summaries] == [
        item.requested_time for item in second.ranked_candidate_summaries
    ]
    assert first.diagnostics == second.diagnostics


def test_tie_breaking_uses_earliest_requested_time_after_score_and_risk() -> None:
    route = make_route()

    def scorer(
        route: Route,
        requested_time: datetime,
        departure_time: datetime,
        arrival_time: datetime,
        include_segment_risks: bool,
    ) -> RouteEvaluation:
        return fake_evaluation(route, 0.0)

    result = evaluate_route_date_range(
        route,
        date(2026, 1, 2),
        date(2026, 1, 3),
        time(8, 0),
        time(8, 10),
        search_mode="departure",
        timezone_name="UTC",
        evaluation_budget=10,
        route_evaluator=scorer,
    )

    assert result.recommended_candidate.requested_time == dt(
        "2026-01-02T08:00:00+00:00"
    )


def test_budget_is_enforced_for_adaptive_search() -> None:
    route = make_route()
    scorer = FakeScorer(date(2026, 1, 1), target_day=45, target_minute=720)

    result = evaluate_route_date_range(
        route,
        date(2026, 1, 1),
        date(2026, 4, 30),
        time(6, 0),
        time(18, 0),
        search_mode="departure",
        timezone_name="UTC",
        evaluation_budget=40,
        route_evaluator=scorer,
    )

    assert result.unique_evaluations <= 40
    assert result.budget_outcome == "exhausted"
    assert (
        result.final_date_resolution_days == result.diagnostics.initial_date_step_days
    )
    assert result.final_time_resolution == result.diagnostics.initial_time_step


def test_candidate_summaries_are_returned_in_chronological_order() -> None:
    route = make_route()
    scorer = FakeScorer(date(2026, 1, 1), target_day=20, target_minute=680)

    result = evaluate_route_date_range(
        route,
        date(2026, 1, 1),
        date(2026, 2, 15),
        time(6, 0),
        time(18, 0),
        search_mode="departure",
        timezone_name="UTC",
        evaluation_budget=180,
        route_evaluator=scorer,
    )

    assert [summary.requested_time for summary in result.candidate_summaries] == sorted(
        summary.requested_time for summary in result.candidate_summaries
    )


def test_duplicate_candidate_evaluations_are_not_scored_twice() -> None:
    route = make_route(duration_s=0.0)
    calls = 0

    def scorer(
        route: Route,
        requested_time: datetime,
        departure_time: datetime,
        arrival_time: datetime,
        include_segment_risks: bool,
    ) -> RouteEvaluation:
        nonlocal calls
        if not include_segment_risks:
            calls += 1
        return fake_evaluation(route, 0.0)

    result = evaluate_route_date_range(
        route,
        date(2026, 3, 8),
        date(2026, 3, 8),
        time(2, 0),
        time(3, 0),
        search_mode="departure",
        timezone_name="America/New_York",
        evaluation_budget=20,
        route_evaluator=scorer,
    )

    assert result.diagnostics.nonexistent_wall_times_adjusted == 6
    assert result.diagnostics.duplicate_candidate_evaluations_avoided == 6
    assert result.unique_evaluations == 1
    assert calls == 1


def test_departure_mode_derives_arrival_time() -> None:
    route = make_route(duration_s=3600.0)

    result = evaluate_route_date_range(
        route,
        date(2026, 1, 1),
        date(2026, 1, 1),
        time(8, 0),
        time(8, 0),
        search_mode="departure",
        timezone_name="UTC",
        evaluation_budget=1,
        route_evaluator=lambda route, requested_time, departure_time, arrival_time, include_segment_risks: (
            fake_evaluation(route, 0.0)
        ),
    )

    assert result.recommended_candidate.departure_time == dt(
        "2026-01-01T08:00:00+00:00"
    )
    assert result.recommended_candidate.arrival_time == dt("2026-01-01T09:00:00+00:00")


def test_arrival_mode_can_derive_previous_day_departure() -> None:
    route = make_route(duration_s=2400.0)

    result = evaluate_route_date_range(
        route,
        date(2026, 1, 2),
        date(2026, 1, 2),
        time(0, 10),
        time(0, 10),
        search_mode="arrival",
        timezone_name="UTC",
        evaluation_budget=1,
        route_evaluator=lambda route, requested_time, departure_time, arrival_time, include_segment_risks: (
            fake_evaluation(route, 0.0)
        ),
    )

    assert result.recommended_candidate.arrival_time == dt("2026-01-02T00:10:00+00:00")
    assert result.recommended_candidate.departure_time == dt(
        "2026-01-01T23:30:00+00:00"
    )


def test_arrival_mode_can_derive_departure_several_days_earlier() -> None:
    route = make_route(duration_s=50 * 60 * 60)

    result = evaluate_route_date_range(
        route,
        date(2026, 7, 21),
        date(2026, 7, 21),
        time(10, 15),
        time(10, 15),
        search_mode="arrival",
        timezone_name="UTC",
        evaluation_budget=1,
        route_evaluator=lambda route, requested_time, departure_time, arrival_time, include_segment_risks: (
            fake_evaluation(route, 0.0)
        ),
    )

    assert result.recommended_candidate.arrival_time == dt(
        "2026-07-21T10:15:00+00:00"
    )
    assert result.recommended_candidate.departure_time == dt(
        "2026-07-19T08:15:00+00:00"
    )


def test_departure_mode_can_report_cross_midnight_arrival() -> None:
    route = make_route(duration_s=2400.0)

    result = evaluate_route_date_range(
        route,
        date(2026, 1, 1),
        date(2026, 1, 1),
        time(23, 40),
        time(23, 40),
        search_mode="departure",
        timezone_name="UTC",
        evaluation_budget=1,
        route_evaluator=lambda route, requested_time, departure_time, arrival_time, include_segment_risks: (
            fake_evaluation(route, 0.0)
        ),
    )

    assert result.recommended_candidate.departure_time == dt(
        "2026-01-01T23:40:00+00:00"
    )
    assert result.recommended_candidate.arrival_time == dt("2026-01-02T00:20:00+00:00")


def test_departure_mode_uses_elapsed_utc_across_dst_transition() -> None:
    route = make_route(duration_s=4 * 60 * 60)

    result = evaluate_route_date_range(
        route,
        date(2026, 3, 8),
        date(2026, 3, 8),
        time(0, 30),
        time(0, 30),
        search_mode="departure",
        timezone_name="America/New_York",
        evaluation_budget=1,
        route_evaluator=lambda route, requested_time, departure_time, arrival_time, include_segment_risks: (
            fake_evaluation(route, 0.0)
        ),
    )

    assert result.recommended_candidate.departure_time.isoformat() == (
        "2026-03-08T00:30:00-05:00"
    )
    assert result.recommended_candidate.arrival_time.isoformat() == (
        "2026-03-08T05:30:00-04:00"
    )


def test_daylight_saving_transition_policy_is_reported() -> None:
    route = make_route(duration_s=0.0)

    spring = evaluate_route_date_range(
        route,
        date(2026, 3, 8),
        date(2026, 3, 8),
        time(2, 30),
        time(2, 30),
        search_mode="departure",
        timezone_name="America/New_York",
        evaluation_budget=1,
        route_evaluator=lambda route, requested_time, departure_time, arrival_time, include_segment_risks: (
            fake_evaluation(route, 0.0)
        ),
    )
    fall = evaluate_route_date_range(
        route,
        date(2026, 11, 1),
        date(2026, 11, 1),
        time(1, 30),
        time(1, 30),
        search_mode="departure",
        timezone_name="America/New_York",
        evaluation_budget=1,
        route_evaluator=lambda route, requested_time, departure_time, arrival_time, include_segment_risks: (
            fake_evaluation(route, 0.0)
        ),
    )

    assert spring.recommended_candidate.requested_time == dt(
        "2026-03-08T03:00:00-04:00"
    )
    assert spring.diagnostics.nonexistent_wall_times_adjusted == 1
    assert (
        fall.recommended_candidate.requested_time.isoformat()
        == "2026-11-01T01:30:00-04:00"
    )
    assert fall.diagnostics.ambiguous_wall_times == 1


def test_fake_solar_resolver_can_drive_date_range_scoring() -> None:
    route = make_route(duration_s=600.0)

    result = evaluate_route_date_range(
        route,
        date(2026, 1, 1),
        date(2026, 1, 1),
        time(8, 0),
        time(8, 20),
        search_mode="departure",
        timezone_name="UTC",
        evaluation_budget=3,
        sun_position_at=lambda moment, coordinates: SunPosition(
            azimuth_deg=90.0,
            elevation_deg=-5.0 if moment.minute >= 10 else 20.0,
        ),
    )

    assert result.recommended_candidate.requested_time == dt(
        "2026-01-01T08:10:00+00:00"
    )
    assert result.recommended_candidate.glare_score == 0.0


def test_validation_helper_compares_adaptive_result_with_exact_search() -> None:
    route = make_route()
    scorer = FakeScorer(date(2026, 1, 1), target_day=1, target_minute=490)

    validation = validate_adaptive_date_range_against_exact(
        route,
        date(2026, 1, 1),
        date(2026, 1, 3),
        time(8, 0),
        time(8, 20),
        search_mode="departure",
        timezone_name="UTC",
        adaptive_evaluation_budget=6,
        route_evaluator=scorer,
    )

    assert validation.exact_evaluation.exact is True
    assert validation.adaptive_evaluation.exact is False
    assert validation.exact_best_score == 0.0
    assert validation.adaptive_best_score >= validation.exact_best_score
    assert validation.best_score_delta >= 0.0
    assert set(validation.per_date_best_score_delta) == {
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 3),
    }
    assert validation.top_candidate_overlap >= 1


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {"start_date": date(2026, 1, 2), "end_date": date(2026, 1, 1)},
            "start_date",
        ),
        (
            {"daily_earliest_time": time(9, 0), "daily_latest_time": time(8, 0)},
            "daily_latest_time",
        ),
        ({"final_resolution": timedelta(0)}, "final_resolution"),
        ({"evaluation_budget": 0}, "evaluation_budget"),
        ({"evaluation_budget": 10_001}, "evaluation_budget"),
        ({"timezone_name": "Not/AZone"}, "timezone_name"),
    ],
)
def test_invalid_date_range_requests_are_rejected(
    kwargs: dict[str, object],
    message: str,
) -> None:
    params = {
        "start_date": date(2026, 1, 1),
        "end_date": date(2026, 1, 1),
        "daily_earliest_time": time(8, 0),
        "daily_latest_time": time(9, 0),
        "search_mode": "departure",
        "timezone_name": "UTC",
        "evaluation_budget": 10,
        "route_evaluator": lambda route, requested_time, departure_time, arrival_time, include_segment_risks: (
            fake_evaluation(route, 0.0)
        ),
    }
    params.update(kwargs)

    with pytest.raises(ValueError, match=message):
        evaluate_route_date_range(make_route(), **params)


def test_date_range_limit_is_rejected() -> None:
    with pytest.raises(ValueError, match="maximum"):
        evaluate_route_date_range(
            make_route(),
            date(2026, 1, 1),
            date(2027, 1, 2),
            time(8, 0),
            time(9, 0),
            search_mode="departure",
            timezone_name="UTC",
            evaluation_budget=10,
            route_evaluator=lambda route, requested_time, departure_time, arrival_time, include_segment_risks: (
                fake_evaluation(route, 0.0)
            ),
        )
