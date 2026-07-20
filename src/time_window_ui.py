from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from src.i18n import t
from src.models import (
    DateRangeEvaluationParams,
    Route,
    RouteDateRangeCandidateSummary,
    RouteDateRangeEvaluation,
    RouteDateRangeVisualizationGrid,
    RouteTimeCandidate,
    RouteTimeSearchMode,
    RouteTimeWindowEvaluation,
    TimeWindowEvaluationParams,
)
from src.utils import (
    format_datetime_with_zone,
    format_distance_km,
    format_duration_minutes,
)


def build_time_window(
    trip_date: date,
    earliest_time: time,
    latest_time: time,
    timezone_name: str,
) -> tuple[datetime, datetime]:
    timezone = ZoneInfo(timezone_name)
    earliest = datetime.combine(trip_date, earliest_time, tzinfo=timezone)
    latest = datetime.combine(trip_date, latest_time, tzinfo=timezone)
    if latest < earliest:
        raise ValueError("Latest time must be the same as or after earliest time.")
    return earliest, latest


def date_range_preset_dates(today: date, preset: str) -> tuple[date, date]:
    if preset == "next_7_days":
        return today, today + timedelta(days=6)
    if preset == "next_30_days":
        return today, today + timedelta(days=29)
    if preset == "this_summer":
        summer_start = date(today.year, 6, 1)
        summer_end = date(today.year, 8, 31)
        if today > summer_end:
            return date(today.year + 1, 6, 1), date(today.year + 1, 8, 31)
        return max(today, summer_start), summer_end
    raise ValueError("unknown date range preset")


def time_window_params_match_current(
    params: TimeWindowEvaluationParams,
    *,
    route_id: str,
    search_mode: RouteTimeSearchMode,
    trip_date: date,
    earliest_time: time,
    latest_time: time,
    timezone_name: str,
) -> bool:
    return params == TimeWindowEvaluationParams(
        route_id=route_id,
        search_mode=search_mode,
        trip_date=trip_date,
        earliest_time=earliest_time,
        latest_time=latest_time,
        timezone_name=timezone_name,
    )


def date_range_params_match_current(
    params: DateRangeEvaluationParams,
    *,
    route_id: str,
    search_mode: RouteTimeSearchMode,
    start_date: date,
    end_date: date,
    daily_earliest_time: time,
    daily_latest_time: time,
    timezone_name: str,
) -> bool:
    return params == DateRangeEvaluationParams(
        route_id=route_id,
        search_mode=search_mode,
        start_date=start_date,
        end_date=end_date,
        daily_earliest_time=daily_earliest_time,
        daily_latest_time=daily_latest_time,
        timezone_name=timezone_name,
    )


def time_window_result_signature(params: TimeWindowEvaluationParams) -> str:
    return "|".join(
        [
            params.route_id,
            params.search_mode,
            params.trip_date.isoformat(),
            params.earliest_time.isoformat(),
            params.latest_time.isoformat(),
            params.timezone_name,
        ]
    )


def date_range_result_signature(params: DateRangeEvaluationParams) -> str:
    return "|".join(
        [
            params.route_id,
            params.search_mode,
            params.start_date.isoformat(),
            params.end_date.isoformat(),
            params.daily_earliest_time.isoformat(),
            params.daily_latest_time.isoformat(),
            params.timezone_name,
        ]
    )


def fastest_route_id(routes: list[Route]) -> str | None:
    if not routes:
        return None
    return min(routes, key=lambda route: route.metrics.duration_s).route_id


def find_route_by_id(routes: list[Route], route_id: str | None) -> Route | None:
    if route_id is None:
        return None
    return next((route for route in routes if route.route_id == route_id), None)


def route_display_name(route: Route, fallback_index: int, language: str) -> str:
    route_index = route.metadata.get("route_index")
    if isinstance(route_index, int) and route_index > 0:
        return t(language, "common.option", index=route_index)
    return t(language, "common.option", index=fallback_index)


def route_choice_labels(routes: list[Route], language: str) -> dict[str, str]:
    fastest_id = fastest_route_id(routes)
    labels: dict[str, str] = {}
    for index, route in enumerate(routes, start=1):
        badges: list[str] = []
        if route.route_id == fastest_id:
            badges.append(t(language, "table.fastest"))
        suffix = f" ({', '.join(badges)})" if badges else ""
        labels[route.route_id] = (
            f"{route_display_name(route, index, language)}{suffix} - "
            f"{format_duration_minutes(route.metrics.duration_s)}, "
            f"{format_distance_km(route.metrics.distance_m)}"
        )
    return labels


def candidate_key(candidate: RouteTimeCandidate) -> str:
    return candidate.requested_time.isoformat()


def candidate_choice_label(
    candidate: RouteTimeCandidate,
    search_mode: RouteTimeSearchMode,
    *,
    is_recommended: bool,
) -> str:
    marker = "Best - " if is_recommended else ""
    departure = _format_trip_endpoint(candidate.departure_time, candidate)
    arrival = _format_trip_endpoint(candidate.arrival_time, candidate)
    if search_mode == "arrival":
        return f"{marker}Arrive {arrival} (depart {departure})"
    return f"{marker}Depart {departure} (arrive {arrival})"


def find_candidate_by_key(
    evaluation: RouteTimeWindowEvaluation,
    selected_key: str | None,
) -> RouteTimeCandidate:
    for candidate in evaluation.candidates:
        if candidate_key(candidate) == selected_key:
            return candidate
    return evaluation.recommended_candidate


def date_range_candidate_options(
    evaluation: RouteDateRangeEvaluation,
) -> list[RouteTimeCandidate]:
    return [
        evaluation.recommended_candidate,
        *evaluation.top_alternative_candidates,
    ]


def find_date_range_candidate_by_key(
    evaluation: RouteDateRangeEvaluation,
    selected_key: str | None,
) -> RouteTimeCandidate:
    for candidate in date_range_candidate_options(evaluation):
        if candidate_key(candidate) == selected_key:
            return candidate
    return evaluation.recommended_candidate


def date_range_candidate_choice_label(
    candidate: RouteTimeCandidate,
    search_mode: RouteTimeSearchMode,
    *,
    rank: int,
    is_recommended: bool,
) -> str:
    marker = "Best - " if is_recommended else f"#{rank} - "
    departure = _format_trip_endpoint(candidate.departure_time, candidate)
    arrival = _format_trip_endpoint(candidate.arrival_time, candidate)
    if search_mode == "arrival":
        return f"{marker}{candidate.arrival_time:%Y-%m-%d} arrive {arrival} (depart {departure})"
    return f"{marker}{candidate.departure_time:%Y-%m-%d} depart {departure} (arrive {arrival})"


def candidate_result_rows(
    evaluation: RouteTimeWindowEvaluation,
    language: str,
) -> list[dict[str, object]]:
    recommended_key = candidate_key(evaluation.recommended_candidate)
    rows: list[dict[str, object]] = []
    for candidate in sorted(
        evaluation.candidates, key=lambda item: item.requested_time
    ):
        rows.append(
            {
                t(language, "time_window.table.recommended"): t(language, "common.yes")
                if candidate_key(candidate) == recommended_key
                else "",
                t(
                    language, "time_window.table.departure"
                ): _format_trip_endpoint(candidate.departure_time, candidate),
                t(
                    language, "time_window.table.arrival"
                ): _format_trip_endpoint(candidate.arrival_time, candidate),
                t(language, "time_window.table.glare"): round(candidate.glare_score, 1),
                t(language, "time_window.table.high_risk"): format_duration_minutes(
                    candidate.high_risk_duration_s
                ),
                t(language, "time_window.table.duration"): format_duration_minutes(
                    candidate.route_evaluation.route.metrics.duration_s
                ),
            }
        )
    return rows


def date_range_top_candidate_rows(
    evaluation: RouteDateRangeEvaluation,
    language: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for rank, candidate in enumerate(date_range_candidate_options(evaluation), start=1):
        rows.append(
            {
                t(language, "date_range.table.rank"): rank,
                t(language, "date_range.table.recommended"): t(
                    language,
                    "common.yes",
                )
                if rank == 1
                else "",
                t(
                    language,
                    "date_range.table.date",
                ): candidate.requested_time.strftime("%Y-%m-%d"),
                t(
                    language,
                    "time_window.table.departure",
                ): _format_trip_endpoint(candidate.departure_time, candidate),
                t(
                    language,
                    "time_window.table.arrival",
                ): _format_trip_endpoint(candidate.arrival_time, candidate),
                t(language, "time_window.table.glare"): round(
                    candidate.glare_score,
                    1,
                ),
                t(language, "time_window.table.high_risk"): format_duration_minutes(
                    candidate.high_risk_duration_s,
                ),
                t(language, "time_window.table.duration"): format_duration_minutes(
                    candidate.route_evaluation.route.metrics.duration_s,
                ),
            }
        )
    return rows


def date_range_best_by_date_chart_rows(
    evaluation: RouteDateRangeEvaluation,
) -> list[dict[str, object]]:
    return date_range_overview_chart_rows(evaluation)


def date_range_evaluated_candidate_chart_rows(
    evaluation: RouteDateRangeEvaluation,
) -> list[dict[str, object]]:
    recommended_key = candidate_key(evaluation.recommended_candidate)
    alternative_keys = {
        candidate_key(candidate) for candidate in evaluation.top_alternative_candidates
    }
    rows: list[dict[str, object]] = []
    for summary in evaluation.candidate_summaries:
        summary_key = summary.requested_time.isoformat()
        if summary_key == recommended_key:
            marker = "Recommended"
            marker_size = 180
        elif summary_key in alternative_keys:
            marker = "Top alternative"
            marker_size = 110
        elif summary.search_phase == "coarse":
            marker = "Coarse"
            marker_size = 55
        elif summary.search_phase == "exact":
            marker = "Exact"
            marker_size = 55
        else:
            marker = "Refinement"
            marker_size = 75
        rows.append(
            {
                "Requested datetime": summary.requested_time,
                "Glare score": round(summary.glare_score, 1),
                "Search phase": summary.search_phase,
                "Candidate marker": marker,
                "Marker size": marker_size,
                "Date": summary.requested_time.strftime("%Y-%m-%d"),
                "Requested time": summary.requested_time.strftime("%H:%M"),
                "Departure": summary.departure_time.strftime("%Y-%m-%d %H:%M %Z"),
                "Arrival": summary.arrival_time.strftime("%Y-%m-%d %H:%M %Z"),
            }
        )
    return rows


def date_range_overview_chart_rows(
    evaluation: RouteDateRangeEvaluation,
) -> list[dict[str, object]]:
    overview_phase = "exact" if evaluation.exact else "coarse"
    overview_summaries = [
        summary
        for summary in evaluation.candidate_summaries
        if summary.search_phase == overview_phase
    ]
    summaries_by_date: dict[date, list[RouteDateRangeCandidateSummary]] = {}
    for summary in overview_summaries:
        local_date = summary.requested_time.date()
        summaries_by_date.setdefault(local_date, []).append(summary)
    if not summaries_by_date:
        return []
    expected_sample_count = max(
        len(summaries) for summaries in summaries_by_date.values()
    )

    timezone = ZoneInfo(evaluation.request.timezone_name)
    return [
        {
            "Sampled date": datetime.combine(
                local_date,
                time.min,
                tzinfo=timezone,
            ),
            "Best sampled glare score": round(
                min(summary.glare_score for summary in summaries),
                1,
            ),
            "Candidates sampled on date": len(summaries),
        }
        for local_date, summaries in sorted(summaries_by_date.items())
        if len(summaries) == expected_sample_count
    ]


def date_range_overview_title(
    evaluation: RouteDateRangeEvaluation,
    language: str = "en",
) -> str:
    if evaluation.exact:
        return t(language, "date_range.exact_overview_chart")
    return t(language, "date_range.coarse_overview_chart")


def date_range_visualization_time_offsets(
    evaluation: RouteDateRangeEvaluation,
) -> list[int]:
    grid = evaluation.visualization_grid
    if grid is None:
        return []
    return sorted({cell.time_offset_s for cell in grid.cells})


def date_range_default_fixed_time_offset(
    evaluation: RouteDateRangeEvaluation,
) -> int | None:
    grid = evaluation.visualization_grid
    if grid is None:
        return None
    return grid.fixed_time_offset_s


def time_offset_label(offset_s: int) -> str:
    return _format_local_time(_time_from_offset_s(offset_s))


def date_range_heatmap_title(
    evaluation: RouteDateRangeEvaluation,
    language: str,
) -> str:
    key = (
        "date_range.heatmap_title_departure"
        if evaluation.request.search_mode == "departure"
        else "date_range.heatmap_title_arrival"
    )
    return t(language, key)


def date_range_heatmap_axis_label(
    evaluation: RouteDateRangeEvaluation,
    language: str,
) -> str:
    key = (
        "date_range.heatmap_axis_departure"
        if evaluation.request.search_mode == "departure"
        else "date_range.heatmap_axis_arrival"
    )
    return t(language, key)


def date_range_fixed_time_title(
    evaluation: RouteDateRangeEvaluation,
    selected_time_offset_s: int,
    language: str,
) -> str:
    key = (
        "date_range.fixed_title_departure"
        if evaluation.request.search_mode == "departure"
        else "date_range.fixed_title_arrival"
    )
    return t(language, key, time=time_offset_label(selected_time_offset_s))


def date_range_heatmap_rows(
    evaluation: RouteDateRangeEvaluation,
) -> list[dict[str, object]]:
    grid = evaluation.visualization_grid
    if grid is None:
        return []
    timezone = ZoneInfo(evaluation.request.timezone_name)
    end_boundary = evaluation.request.end_date + timedelta(days=1)
    time_interval_minutes = int(grid.diagnostics.time_interval.total_seconds() / 60)
    rows: list[dict[str, object]] = []
    for cell in grid.cells:
        date_end = min(
            cell.requested_wall_date
            + timedelta(days=grid.diagnostics.date_interval_days),
            end_boundary,
        )
        rows.append(
            {
                "Date start": datetime.combine(
                    cell.requested_wall_date,
                    time.min,
                    tzinfo=timezone,
                ).isoformat(),
                "Date end": datetime.combine(
                    date_end,
                    time.min,
                    tzinfo=timezone,
                ).isoformat(),
                "Requested time start minutes": cell.time_offset_s / 60,
                "Requested time end minutes": (
                    cell.time_offset_s / 60
                )
                + time_interval_minutes,
                "Glare score": round(cell.glare_score, 1),
                "Date": cell.requested_wall_date.isoformat(),
                "Requested time": _format_local_time(cell.requested_wall_time),
                "Calculated departure": cell.departure_time.strftime(
                    "%Y-%m-%d %H:%M %Z"
                ),
                "Calculated arrival": cell.arrival_time.strftime("%Y-%m-%d %H:%M %Z"),
                "High-risk duration": format_duration_minutes(
                    cell.high_risk_duration_s
                ),
                "Peak glare": (
                    f"{cell.peak_glare_score:.1f}"
                    if cell.peak_glare_category is None
                    else f"{cell.peak_glare_category} ({cell.peak_glare_score:.1f})"
                ),
                "UTC offset": _format_utc_offset(cell.utc_offset_minutes),
                "Evaluation source": "Reused optimizer evaluation"
                if cell.reused_optimizer_evaluation
                else "Visualization-grid evaluation",
            }
        )
    return rows


def date_range_best_time_overlay_rows(
    evaluation: RouteDateRangeEvaluation,
) -> list[dict[str, object]]:
    grid = evaluation.visualization_grid
    if grid is None:
        return []
    timezone = ZoneInfo(evaluation.request.timezone_name)
    return [
        {
            "Sampled date": datetime.combine(
                point.sampled_date,
                time.min,
                tzinfo=timezone,
            ).isoformat(),
            "Representative time minutes": point.representative_time_offset_s / 60,
            "Representative lowest-glare time": _format_local_time(
                point.representative_time
            ),
            "Minimum glare score": round(point.minimum_glare_score, 1),
            "Interval average score": round(point.interval_average_score, 1),
        }
        for point in grid.representative_best_times
    ]


def date_range_fixed_time_chart_rows(
    evaluation: RouteDateRangeEvaluation,
    selected_time_offset_s: int,
) -> list[dict[str, object]]:
    grid = evaluation.visualization_grid
    if grid is None:
        return []
    timezone = ZoneInfo(evaluation.request.timezone_name)
    selected_cells = sorted(
        (
            cell
            for cell in grid.cells
            if cell.time_offset_s == selected_time_offset_s
        ),
        key=lambda cell: cell.requested_wall_date,
    )
    rows: list[dict[str, object]] = []
    previous_date: date | None = None
    series_index = 0
    for cell in selected_cells:
        if (
            previous_date is not None
            and (cell.requested_wall_date - previous_date).days
            > grid.diagnostics.date_interval_days
        ):
            series_index += 1
        rows.append(
            {
                "Sampled date": datetime.combine(
                    cell.requested_wall_date,
                    time.min,
                    tzinfo=timezone,
                ).isoformat(),
                "Glare score": round(cell.glare_score, 1),
                "Series": str(series_index),
                "Date": cell.requested_wall_date.isoformat(),
                "Requested time": _format_local_time(cell.requested_wall_time),
                "Calculated departure": cell.departure_time.strftime(
                    "%Y-%m-%d %H:%M %Z"
                ),
                "Calculated arrival": cell.arrival_time.strftime("%Y-%m-%d %H:%M %Z"),
                "High-risk duration": format_duration_minutes(
                    cell.high_risk_duration_s
                ),
                "Peak glare": (
                    f"{cell.peak_glare_score:.1f}"
                    if cell.peak_glare_category is None
                    else f"{cell.peak_glare_category} ({cell.peak_glare_score:.1f})"
                ),
                "UTC offset": _format_utc_offset(cell.utc_offset_minutes),
                "Evaluation source": "Reused optimizer evaluation"
                if cell.reused_optimizer_evaluation
                else "Visualization-grid evaluation",
            }
        )
        previous_date = cell.requested_wall_date
    return rows


def date_range_dst_annotation_rows(
    evaluation: RouteDateRangeEvaluation,
) -> list[dict[str, object]]:
    grid = evaluation.visualization_grid
    if grid is None:
        return []
    timezone = ZoneInfo(evaluation.request.timezone_name)
    return [
        {
            "Transition date": datetime.combine(
                transition_date,
                time.min,
                tzinfo=timezone,
            ).isoformat(),
            "Label": transition_date.isoformat(),
        }
        for transition_date in grid.diagnostics.dst_transition_dates
    ]


def date_range_visualization_caption(
    evaluation: RouteDateRangeEvaluation,
    language: str,
) -> str:
    grid = evaluation.visualization_grid
    if grid is None:
        return ""
    return t(
        language,
        "date_range.heatmap_caption",
        date_step=grid.diagnostics.date_interval_days,
        time_step=int(grid.diagnostics.time_interval.total_seconds() / 60),
        cells=grid.diagnostics.evaluated_cell_count,
    )


def date_range_visualization_performance_caption(
    evaluation: RouteDateRangeEvaluation,
    language: str,
    *,
    rendering_time_s: float,
) -> str:
    grid = evaluation.visualization_grid
    if grid is None:
        return ""
    return t(
        language,
        "date_range.visualization_performance",
        cells=grid.diagnostics.evaluated_cell_count,
        reused=grid.diagnostics.reused_optimizer_evaluations,
        new=grid.diagnostics.new_evaluations,
        eval_time=grid.diagnostics.evaluation_time_s,
        render_time=round(rendering_time_s, 3),
    )


def date_range_large_change_rows(
    evaluation: RouteDateRangeEvaluation,
    *,
    limit: int = 40,
) -> list[dict[str, object]]:
    grid = evaluation.visualization_grid
    if grid is None:
        return []
    return [
        {
            "Previous date": change.previous_date.isoformat(),
            "Current date": change.current_date.isoformat(),
            "Requested local time": _format_local_time(change.requested_wall_time),
            "Previous score": round(change.previous_glare_score, 1),
            "Current score": round(change.current_glare_score, 1),
            "Delta": round(change.score_delta, 1),
            "Previous UTC offset": _format_utc_offset(
                change.previous_utc_offset_minutes
            ),
            "Current UTC offset": _format_utc_offset(change.current_utc_offset_minutes),
            "Previous sun azimuth": change.previous_peak_sun_azimuth_deg,
            "Current sun azimuth": change.current_peak_sun_azimuth_deg,
            "Previous sun elevation": change.previous_peak_sun_elevation_deg,
            "Current sun elevation": change.current_peak_sun_elevation_deg,
            "Previous peak segment": change.previous_peak_segment_index,
            "Current peak segment": change.current_peak_segment_index,
            "Previous peak score": change.previous_peak_segment_score,
            "Current peak score": change.current_peak_segment_score,
            "Previous angle difference": change.previous_peak_angle_difference_deg,
            "Current angle difference": change.current_peak_angle_difference_deg,
            "Previous bearing": change.previous_peak_bearing_deg,
            "Current bearing": change.current_peak_bearing_deg,
            "Scoring threshold crossed": change.scoring_threshold_crossed,
        }
        for change in grid.large_adjacent_changes[:limit]
    ]


def date_range_grid_debug_summary(
    grid: RouteDateRangeVisualizationGrid,
) -> dict[str, object]:
    return {
        "route_geometry_fingerprint": grid.diagnostics.route_geometry_fingerprint,
        "date_interval_days": grid.diagnostics.date_interval_days,
        "time_interval_minutes": int(
            grid.diagnostics.time_interval.total_seconds() / 60
        ),
        "requested_cells": grid.diagnostics.requested_cell_count,
        "evaluated_cells": grid.diagnostics.evaluated_cell_count,
        "reused_optimizer_evaluations": grid.diagnostics.reused_optimizer_evaluations,
        "new_evaluations": grid.diagnostics.new_evaluations,
        "visualization_grid_evaluation_time_s": grid.diagnostics.evaluation_time_s,
        "invalid_wall_time_count": grid.diagnostics.invalid_wall_time_count,
        "dst_transition_dates": [
            value.isoformat() for value in grid.diagnostics.dst_transition_dates
        ],
        "large_adjacent_change_count": grid.diagnostics.large_adjacent_change_count,
    }


def date_range_evaluated_candidates_caption(language: str) -> str:
    return t(language, "date_range.evaluated_candidates_caption")


def date_range_overview_caption(
    evaluation: RouteDateRangeEvaluation,
    language: str,
) -> str:
    rows = date_range_overview_chart_rows(evaluation)
    sample_counts = sorted(
        {
            row["Candidates sampled on date"]
            for row in rows
            if isinstance(row["Candidates sampled on date"], int)
        }
    )
    if not rows:
        return ""
    if len(sample_counts) == 1:
        sample_count_text = str(sample_counts[0])
    else:
        sample_count_text = f"{sample_counts[0]}-{sample_counts[-1]}"
    if evaluation.exact:
        return t(
            language,
            "date_range.exact_overview_caption",
            time_resolution=int(
                evaluation.request.final_resolution.total_seconds() / 60,
            ),
            sample_count=sample_count_text,
        )
    return t(
        language,
        "date_range.coarse_overview_caption",
        date_step=evaluation.diagnostics.initial_date_step_days,
        time_step=int(evaluation.diagnostics.initial_time_step.total_seconds() / 60),
        sample_count=sample_count_text,
    )


def date_range_dst_transition_caption(
    evaluation: RouteDateRangeEvaluation,
    language: str,
) -> str | None:
    timezone = ZoneInfo(evaluation.request.timezone_name)
    transition_dates: list[date] = []
    previous_offset = datetime.combine(
        evaluation.request.start_date,
        time(12, 0),
        tzinfo=timezone,
    ).utcoffset()
    day_count = (evaluation.request.end_date - evaluation.request.start_date).days + 1
    for index in range(1, day_count):
        local_date = evaluation.request.start_date + timedelta(days=index)
        current_offset = datetime.combine(
            local_date,
            time(12, 0),
            tzinfo=timezone,
        ).utcoffset()
        if current_offset != previous_offset:
            transition_dates.append(local_date)
        previous_offset = current_offset
    if not transition_dates:
        return None
    return t(
        language,
        "date_range.dst_caption",
        dates=", ".join(value.isoformat() for value in transition_dates),
    )


def _summary_distance_from_recommendation(
    summary: RouteDateRangeCandidateSummary,
    recommended: RouteTimeCandidate,
) -> tuple[int, float, datetime]:
    day_distance = abs(
        (summary.requested_time.date() - recommended.requested_time.date()).days
    )
    time_distance = abs(
        (
            datetime.combine(date.min, summary.requested_time.time())
            - datetime.combine(date.min, recommended.requested_time.time())
        ).total_seconds()
    )
    return day_distance, time_distance, summary.requested_time


def date_range_candidate_sample_rows(
    evaluation: RouteDateRangeEvaluation,
    language: str,
    *,
    limit: int = 80,
) -> list[dict[str, object]]:
    summaries = sorted(
        evaluation.candidate_summaries,
        key=lambda summary: _summary_distance_from_recommendation(
            summary,
            evaluation.recommended_candidate,
        ),
    )[:limit]
    summaries = sorted(summaries, key=lambda summary: summary.requested_time)
    return [
        {
            t(language, "date_range.table.date"): summary.requested_time.strftime(
                "%Y-%m-%d"
            ),
            t(
                language,
                "time_window.table.departure",
            ): _format_summary_endpoint(summary.departure_time, summary),
            t(language, "time_window.table.arrival"): _format_summary_endpoint(
                summary.arrival_time, summary
            ),
            t(language, "time_window.table.glare"): round(summary.glare_score, 1),
            t(language, "time_window.table.high_risk"): format_duration_minutes(
                summary.high_risk_duration_s,
            ),
            t(language, "date_range.table.phase"): summary.search_phase,
        }
        for summary in summaries
    ]


def glare_chart_rows(
    evaluation: RouteTimeWindowEvaluation,
) -> list[dict[str, object]]:
    return [
        {
            "Time": candidate.requested_time.strftime("%H:%M"),
            "Glare score": candidate.glare_score,
        }
        for candidate in sorted(
            evaluation.candidates, key=lambda item: item.requested_time
        )
    ]


def _time_from_offset_s(offset_s: int) -> time:
    hour, remainder = divmod(offset_s, 3600)
    minute, second = divmod(remainder, 60)
    return time(hour=hour, minute=minute, second=second)


def _format_local_time(value: time) -> str:
    if value.second:
        return value.strftime("%H:%M:%S")
    return value.strftime("%H:%M")


def _format_utc_offset(offset_minutes: int) -> str:
    sign = "+" if offset_minutes >= 0 else "-"
    absolute = abs(offset_minutes)
    hours, minutes = divmod(absolute, 60)
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


def _format_trip_endpoint(moment: datetime, candidate: RouteTimeCandidate) -> str:
    if candidate.departure_time.date() == candidate.arrival_time.date():
        return moment.strftime("%H:%M")
    return format_datetime_with_zone(moment)


def _format_summary_endpoint(
    moment: datetime,
    summary: RouteDateRangeCandidateSummary,
) -> str:
    if summary.departure_time.date() == summary.arrival_time.date():
        return moment.strftime("%H:%M")
    return format_datetime_with_zone(moment)
