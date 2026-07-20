from __future__ import annotations

from datetime import date, datetime, time

import pytest

from src.models import (
    Coordinates,
    DateRangeEvaluationParams,
    Route,
    RouteMetrics,
    SunPosition,
    TimeWindowEvaluationParams,
)
from src.route_time_search import evaluate_route_date_range, evaluate_route_time_window
from src.time_window_ui import (
    build_time_window,
    date_range_best_time_overlay_rows,
    date_range_dst_transition_caption,
    date_range_evaluated_candidate_chart_rows,
    date_range_best_by_date_chart_rows,
    date_range_fixed_time_chart_rows,
    date_range_heatmap_rows,
    date_range_overview_caption,
    date_range_overview_chart_rows,
    date_range_overview_title,
    date_range_params_match_current,
    date_range_preset_dates,
    date_range_result_signature,
    date_range_top_candidate_rows,
    date_range_visualization_caption,
    date_range_visualization_time_offsets,
    candidate_result_rows,
    fastest_route_id,
    route_choice_labels,
    time_window_params_match_current,
)


def make_route(route_id: str, duration_s: float, distance_m: float = 1000.0) -> Route:
    return Route(
        route_id=route_id,
        geometry=[
            Coordinates(lat=0.0, lon=0.0),
            Coordinates(lat=0.0, lon=0.01),
        ],
        metrics=RouteMetrics(distance_m=distance_m, duration_s=duration_s),
        metadata={"route_index": 1 if route_id == "slow" else 2},
    )


def zero_glare(moment: datetime, coordinates: Coordinates) -> SunPosition:
    return SunPosition(azimuth_deg=90.0, elevation_deg=-5.0)


def test_route_choice_labels_mark_fastest_route_by_default() -> None:
    routes = [
        make_route("slow", duration_s=1800.0, distance_m=12000.0),
        make_route("fast", duration_s=900.0, distance_m=15000.0),
    ]

    labels = route_choice_labels(routes, "en")

    assert fastest_route_id(routes) == "fast"
    assert labels["slow"] == "Option 1 - 30 min, 12.0 km"
    assert labels["fast"] == "Option 2 (Fastest) - 15 min, 15.0 km"


def test_candidate_rows_are_chronological_and_mark_recommendation() -> None:
    route = make_route("fast", duration_s=600.0)

    result = evaluate_route_time_window(
        route,
        datetime.fromisoformat("2026-03-18T08:00:00-04:00"),
        datetime.fromisoformat("2026-03-18T08:20:00-04:00"),
        search_mode="departure",
        sun_position_at=zero_glare,
    )

    rows = candidate_result_rows(result, "en")

    assert [row["Departure"] for row in rows] == ["08:00", "08:10", "08:20"]
    assert [row["Arrival"] for row in rows] == ["08:10", "08:20", "08:30"]
    assert [row["Recommended"] for row in rows] == ["Yes", "", ""]


def test_build_time_window_rejects_reversed_range() -> None:
    with pytest.raises(ValueError, match="Latest time"):
        build_time_window(
            date(2026, 3, 18),
            time(hour=10),
            time(hour=9),
            "America/New_York",
        )


def test_build_time_window_uses_requested_timezone() -> None:
    earliest, latest = build_time_window(
        date(2026, 3, 18),
        time(hour=8),
        time(hour=9),
        "America/New_York",
    )

    assert earliest.isoformat() == "2026-03-18T08:00:00-04:00"
    assert latest.isoformat() == "2026-03-18T09:00:00-04:00"


def test_date_range_presets_populate_editable_date_ranges() -> None:
    today = date(2026, 7, 19)

    assert date_range_preset_dates(today, "next_7_days") == (
        today,
        date(2026, 7, 25),
    )
    assert date_range_preset_dates(today, "next_30_days") == (
        today,
        date(2026, 8, 17),
    )
    assert date_range_preset_dates(today, "this_summer") == (
        today,
        date(2026, 8, 31),
    )


def test_date_range_params_match_material_inputs() -> None:
    params = DateRangeEvaluationParams(
        route_id="fast",
        search_mode="departure",
        start_date=date(2026, 3, 18),
        end_date=date(2026, 3, 20),
        daily_earliest_time=time(hour=8),
        daily_latest_time=time(hour=9),
        timezone_name="America/New_York",
    )

    assert date_range_params_match_current(
        params,
        route_id="fast",
        search_mode="departure",
        start_date=date(2026, 3, 18),
        end_date=date(2026, 3, 20),
        daily_earliest_time=time(hour=8),
        daily_latest_time=time(hour=9),
        timezone_name="America/New_York",
    )
    assert not date_range_params_match_current(
        params,
        route_id="slow",
        search_mode="departure",
        start_date=date(2026, 3, 18),
        end_date=date(2026, 3, 20),
        daily_earliest_time=time(hour=8),
        daily_latest_time=time(hour=9),
        timezone_name="America/New_York",
    )
    assert not date_range_params_match_current(
        params,
        route_id="fast",
        search_mode="departure",
        start_date=date(2026, 3, 18),
        end_date=date(2026, 3, 20),
        daily_earliest_time=time(hour=8),
        daily_latest_time=time(hour=9),
        timezone_name="UTC",
    )


def test_single_day_params_match_material_inputs() -> None:
    params = TimeWindowEvaluationParams(
        route_id="fast",
        search_mode="arrival",
        trip_date=date(2026, 3, 18),
        earliest_time=time(hour=8),
        latest_time=time(hour=9),
        timezone_name="America/New_York",
    )

    assert time_window_params_match_current(
        params,
        route_id="fast",
        search_mode="arrival",
        trip_date=date(2026, 3, 18),
        earliest_time=time(hour=8),
        latest_time=time(hour=9),
        timezone_name="America/New_York",
    )
    assert not time_window_params_match_current(
        params,
        route_id="fast",
        search_mode="departure",
        trip_date=date(2026, 3, 18),
        earliest_time=time(hour=8),
        latest_time=time(hour=9),
        timezone_name="America/New_York",
    )


def test_date_range_signature_changes_with_inputs() -> None:
    first = DateRangeEvaluationParams(
        route_id="fast",
        search_mode="departure",
        start_date=date(2026, 3, 18),
        end_date=date(2026, 3, 20),
        daily_earliest_time=time(hour=8),
        daily_latest_time=time(hour=9),
        timezone_name="America/New_York",
    )
    second = DateRangeEvaluationParams(
        route_id="fast",
        search_mode="departure",
        start_date=date(2026, 3, 18),
        end_date=date(2026, 3, 21),
        daily_earliest_time=time(hour=8),
        daily_latest_time=time(hour=9),
        timezone_name="America/New_York",
    )

    assert date_range_result_signature(first) != date_range_result_signature(second)


def test_date_range_rows_show_top_candidates_and_daily_chart() -> None:
    route = make_route("fast", duration_s=600.0)
    result = evaluate_route_date_range(
        route,
        date(2026, 3, 18),
        date(2026, 3, 20),
        time(hour=8),
        time(hour=8, minute=20),
        search_mode="departure",
        timezone_name="America/New_York",
        evaluation_budget=20,
        sun_position_at=zero_glare,
    )

    rows = date_range_top_candidate_rows(result, "en")
    chart_rows = date_range_best_by_date_chart_rows(result)

    assert rows[0]["Rank"] == 1
    assert rows[0]["Recommended"] == "Yes"
    assert rows[0]["Date"] == "2026-03-18"
    assert [row["Sampled date"].date().isoformat() for row in chart_rows] == [
        "2026-03-18",
        "2026-03-19",
        "2026-03-20",
    ]


def test_date_range_candidate_chart_rows_use_timezone_aware_datetimes() -> None:
    route = make_route("fast", duration_s=600.0)
    result = evaluate_route_date_range(
        route,
        date(2026, 3, 18),
        date(2026, 3, 18),
        time(hour=8),
        time(hour=8, minute=20),
        search_mode="departure",
        timezone_name="America/New_York",
        evaluation_budget=3,
        sun_position_at=zero_glare,
    )

    rows = date_range_evaluated_candidate_chart_rows(result)

    assert rows
    assert all(isinstance(row["Requested datetime"], datetime) for row in rows)
    assert all(row["Requested datetime"].tzinfo is not None for row in rows)
    assert rows[0]["Requested datetime"].isoformat() == "2026-03-18T08:00:00-04:00"
    assert {row["Candidate marker"] for row in rows} >= {
        "Recommended",
        "Top alternative",
    }


def test_adaptive_overview_uses_only_coarse_samples() -> None:
    route = make_route("fast", duration_s=600.0)
    result = evaluate_route_date_range(
        route,
        date(2026, 1, 1),
        date(2026, 3, 31),
        time(hour=6),
        time(hour=18),
        search_mode="departure",
        timezone_name="UTC",
        evaluation_budget=700,
        sun_position_at=zero_glare,
    )
    coarse_dates = {
        summary.requested_time.date()
        for summary in result.candidate_summaries
        if summary.search_phase == "coarse"
    }

    overview_rows = date_range_overview_chart_rows(result)

    assert result.exact is False
    assert {row["Sampled date"].date() for row in overview_rows} == coarse_dates
    assert len(overview_rows) < len(
        {summary.requested_time.date() for summary in result.candidate_summaries}
    )
    assert date_range_overview_title(result) == "Adaptive coarse date sample diagnostic"
    assert "coarse grid" in date_range_overview_caption(result, "en")


def test_dst_transition_caption_reports_crossed_transition() -> None:
    route = make_route("fast", duration_s=600.0)
    result = evaluate_route_date_range(
        route,
        date(2026, 10, 31),
        date(2026, 11, 2),
        time(hour=8),
        time(hour=8),
        search_mode="departure",
        timezone_name="America/New_York",
        evaluation_budget=3,
        sun_position_at=zero_glare,
    )

    caption = date_range_dst_transition_caption(result, "en")

    assert caption is not None
    assert "2026-11-01" in caption
    assert "daylight-saving" in caption
    assert "wall-clock" in caption


def test_date_range_visualization_rows_use_regular_grid() -> None:
    route = make_route("fast", duration_s=600.0)
    result = evaluate_route_date_range(
        route,
        date(2026, 3, 18),
        date(2026, 3, 20),
        time(hour=8),
        time(hour=8, minute=30),
        search_mode="departure",
        timezone_name="America/New_York",
        evaluation_budget=20,
        sun_position_at=zero_glare,
    )

    heatmap_rows = date_range_heatmap_rows(result)
    overlay_rows = date_range_best_time_overlay_rows(result)
    offsets = date_range_visualization_time_offsets(result)

    assert result.visualization_grid is not None
    assert result.visualization_grid.diagnostics.date_interval_days == 1
    assert result.visualization_grid.diagnostics.time_interval.total_seconds() == 900
    assert len(heatmap_rows) == 9
    assert offsets == [8 * 3600, (8 * 3600) + (15 * 60), (8 * 3600) + (30 * 60)]
    assert {row["Evaluation source"] for row in heatmap_rows} >= {
        "Reused optimizer evaluation",
        "Visualization-grid evaluation",
    }
    assert [row["Representative lowest-glare time"] for row in overlay_rows] == [
        "08:15",
        "08:15",
        "08:15",
    ]
    assert "every 1 day(s) and 15 min" in date_range_visualization_caption(
        result,
        "en",
    )


def test_fixed_time_curve_uses_same_local_time_on_sampled_dates() -> None:
    route = make_route("fast", duration_s=600.0)
    result = evaluate_route_date_range(
        route,
        date(2026, 3, 18),
        date(2026, 3, 20),
        time(hour=8),
        time(hour=8, minute=30),
        search_mode="arrival",
        timezone_name="America/New_York",
        evaluation_budget=20,
        sun_position_at=zero_glare,
    )

    rows = date_range_fixed_time_chart_rows(result, 8 * 3600)

    assert [row["Date"] for row in rows] == [
        "2026-03-18",
        "2026-03-19",
        "2026-03-20",
    ]
    assert {row["Requested time"] for row in rows} == {"08:00"}
    assert all("Calculated departure" in row for row in rows)


def test_visualization_grid_skips_nonexistent_wall_times() -> None:
    route = make_route("fast", duration_s=0.0)
    result = evaluate_route_date_range(
        route,
        date(2026, 3, 8),
        date(2026, 3, 8),
        time(hour=2, minute=0),
        time(hour=3, minute=0),
        search_mode="departure",
        timezone_name="America/New_York",
        evaluation_budget=20,
        sun_position_at=zero_glare,
    )

    heatmap_rows = date_range_heatmap_rows(result)

    assert result.visualization_grid is not None
    assert result.visualization_grid.diagnostics.invalid_wall_time_count > 0
    assert {row["Requested time"] for row in heatmap_rows} == {"03:00"}
