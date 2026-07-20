from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
import hashlib
import math
from time import perf_counter
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.models import (
    Coordinates,
    RouteDateRangeAdjacentChange,
    RouteDateRangeCandidateSummary,
    RouteDateRangeEvaluation,
    RouteDateRangeBestTimePoint,
    RouteDateRangeRequest,
    RouteDateRangeSearchDiagnostics,
    RouteDateRangeVisualizationCell,
    RouteDateRangeVisualizationDiagnostics,
    RouteDateRangeVisualizationGrid,
    Route,
    RouteEvaluation,
    RouteTimeCandidate,
    RouteTimeSearchMode,
    RouteTimeWindowEvaluation,
)
from src.scoring import HIGH_RISK_SEGMENT_SCORE, SunPositionResolver, evaluate_route
from src.solar import get_sun_position

DEFAULT_SEARCH_INCREMENT = timedelta(minutes=10)
DEFAULT_MAX_SEARCH_WINDOW = timedelta(hours=24)
DEFAULT_DATE_RANGE_EVALUATION_BUDGET = 750
MAX_DATE_RANGE_EVALUATION_BUDGET = 10_000
DEFAULT_MAX_DATE_RANGE_DAYS = 366
DEFAULT_TOP_ALTERNATIVE_COUNT = 4
DEFAULT_RETAINED_BASINS = 8
COARSE_GRID_TARGET_PER_AXIS = 8
DEFAULT_VISUALIZATION_MAX_CELLS = 2_500
DEFAULT_LARGE_CHANGE_THRESHOLD = 35.0
NEAR_OPTIMAL_SCORE_TOLERANCE = 2.0

RouteCandidateEvaluator = Callable[
    [Route, datetime, datetime, datetime, bool],
    RouteEvaluation,
]


@dataclass(frozen=True)
class _SearchKey:
    date_index: int
    time_index: int


@dataclass(frozen=True)
class _CandidateTiming:
    requested_time: datetime
    departure_time: datetime
    arrival_time: datetime


@dataclass(frozen=True)
class DateRangeExactValidation:
    exact_evaluation: RouteDateRangeEvaluation
    adaptive_evaluation: RouteDateRangeEvaluation
    recommended_candidate_matches: bool
    exact_best_score: float
    adaptive_best_score: float
    best_score_delta: float
    top_candidate_overlap: int
    per_date_best_score_delta: dict[date, float | None]


def evaluate_route_time_window(
    route: Route,
    earliest_time: datetime,
    latest_time: datetime,
    *,
    search_mode: RouteTimeSearchMode,
    increment: timedelta = DEFAULT_SEARCH_INCREMENT,
    max_window: timedelta = DEFAULT_MAX_SEARCH_WINDOW,
    sun_position_at: SunPositionResolver = get_sun_position,
) -> RouteTimeWindowEvaluation:
    _validate_window(earliest_time, latest_time, increment, max_window)
    if search_mode not in ("departure", "arrival"):
        raise ValueError("search_mode must be either 'departure' or 'arrival'")
    if route.metrics.duration_s < 0.0:
        raise ValueError("route duration must be greater than or equal to zero")

    candidates: list[RouteTimeCandidate] = []
    route_duration = timedelta(seconds=route.metrics.duration_s)
    for requested_time in _candidate_times(earliest_time, latest_time, increment):
        if search_mode == "departure":
            departure_time = requested_time
            arrival_time = _add_elapsed_time(departure_time, route_duration)
        else:
            arrival_time = requested_time
            departure_time = _add_elapsed_time(arrival_time, -route_duration)

        route_evaluation = evaluate_route(
            route,
            departure_time,
            sun_position_at=sun_position_at,
        )
        candidates.append(
            RouteTimeCandidate(
                requested_time=requested_time,
                departure_time=departure_time,
                arrival_time=arrival_time,
                route_evaluation=route_evaluation,
            )
        )

    ranked_candidates = sorted(
        candidates,
        key=lambda candidate: (
            candidate.glare_score,
            candidate.high_risk_duration_s,
            candidate.requested_time,
        ),
    )
    return RouteTimeWindowEvaluation(
        search_mode=search_mode,
        earliest_time=earliest_time,
        latest_time=latest_time,
        increment=increment,
        candidates=candidates,
        ranked_candidates=ranked_candidates,
    )


def evaluate_route_date_range(
    route: Route,
    start_date: date,
    end_date: date,
    daily_earliest_time: time,
    daily_latest_time: time,
    *,
    search_mode: RouteTimeSearchMode,
    timezone_name: str,
    final_resolution: timedelta = DEFAULT_SEARCH_INCREMENT,
    evaluation_budget: int = DEFAULT_DATE_RANGE_EVALUATION_BUDGET,
    max_date_range_days: int = DEFAULT_MAX_DATE_RANGE_DAYS,
    max_visualization_cells: int = DEFAULT_VISUALIZATION_MAX_CELLS,
    sun_position_at: SunPositionResolver = get_sun_position,
    route_evaluator: RouteCandidateEvaluator | None = None,
) -> RouteDateRangeEvaluation:
    """Find the best single trip across a local-date range.

    Ambiguous wall-clock times use the first occurrence (``fold=0``).
    Nonexistent wall-clock times are advanced to the next valid local minute and
    reported in diagnostics.
    """

    timezone = _validate_date_range_request(
        route=route,
        start_date=start_date,
        end_date=end_date,
        daily_earliest_time=daily_earliest_time,
        daily_latest_time=daily_latest_time,
        search_mode=search_mode,
        timezone_name=timezone_name,
        final_resolution=final_resolution,
        evaluation_budget=evaluation_budget,
        max_date_range_days=max_date_range_days,
    )
    _validate_visualization_budget(max_visualization_cells)
    request = RouteDateRangeRequest(
        start_date=start_date,
        end_date=end_date,
        daily_earliest_time=daily_earliest_time,
        daily_latest_time=daily_latest_time,
        search_mode=search_mode,
        timezone_name=timezone_name,
        final_resolution=final_resolution,
        evaluation_budget=evaluation_budget,
    )
    day_count = (end_date - start_date).days + 1
    time_offsets_s = _final_time_offsets_s(
        daily_earliest_time,
        daily_latest_time,
        final_resolution,
    )
    candidate_count = day_count * len(time_offsets_s)
    exact = candidate_count <= evaluation_budget

    unique_evaluations = 0
    duplicate_evaluations_avoided = 0
    ambiguous_wall_times = 0
    nonexistent_wall_times_adjusted = 0
    summary_by_key: dict[_SearchKey, RouteDateRangeCandidateSummary] = {}
    evaluation_by_departure_utc: dict[datetime, RouteEvaluation] = {}
    exhausted = False
    route_duration = timedelta(seconds=route.metrics.duration_s)

    def evaluate_key(key: _SearchKey, phase: str) -> bool:
        nonlocal unique_evaluations
        nonlocal duplicate_evaluations_avoided
        nonlocal ambiguous_wall_times
        nonlocal nonexistent_wall_times_adjusted
        nonlocal exhausted

        if key in summary_by_key:
            return True

        local_date = start_date + timedelta(days=key.date_index)
        local_time = _local_time_from_offset(time_offsets_s[key.time_index])
        local_moment, wall_status = _resolve_local_wall_time(
            local_date,
            local_time,
            timezone,
        )
        if wall_status == "ambiguous":
            ambiguous_wall_times += 1
        elif wall_status == "nonexistent":
            nonexistent_wall_times_adjusted += 1

        timing = _candidate_timing(local_moment, search_mode, route_duration, timezone)
        departure_utc = timing.departure_time.astimezone(UTC)
        route_evaluation = evaluation_by_departure_utc.get(departure_utc)
        if route_evaluation is None:
            if unique_evaluations >= evaluation_budget:
                exhausted = True
                return False
            route_evaluation = _evaluate_candidate_route(
                route=route,
                timing=timing,
                include_segment_risks=False,
                sun_position_at=sun_position_at,
                route_evaluator=route_evaluator,
            )
            evaluation_by_departure_utc[departure_utc] = route_evaluation
            unique_evaluations += 1
        else:
            duplicate_evaluations_avoided += 1

        summary_by_key[key] = RouteDateRangeCandidateSummary(
            requested_time=timing.requested_time,
            departure_time=timing.departure_time,
            arrival_time=timing.arrival_time,
            glare_score=route_evaluation.glare_score,
            high_risk_duration_s=route_evaluation.high_risk_duration_s,
            high_risk_distance_m=route_evaluation.high_risk_distance_m,
            peak_glare_score=route_evaluation.peak_glare_score,
            peak_glare_category=route_evaluation.peak_glare_category,
            date_index=key.date_index,
            time_offset_s=time_offsets_s[key.time_index],
            search_phase=phase,
        )
        return True

    dst_transition_indices = _dst_transition_date_indices(
        start_date,
        day_count,
        timezone,
    )
    initial_date_step = _initial_step(day_count)
    initial_time_step_index = _initial_step(len(time_offsets_s))
    initial_date_indices = _initial_date_indices(
        day_count,
        initial_date_step,
        dst_transition_indices,
    )
    initial_time_indices = _initial_indices(
        len(time_offsets_s), initial_time_step_index
    )

    if exact:
        for date_index in range(day_count):
            for time_index in range(len(time_offsets_s)):
                evaluate_key(_SearchKey(date_index, time_index), "exact")
        final_date_resolution_days = 1
        final_time_resolution = final_resolution
        refinement_rounds = 0
        retained_basin_count = 0
    else:
        for key in _sorted_keys(initial_date_indices, initial_time_indices):
            if not evaluate_key(key, "coarse"):
                break

        current_date_step = initial_date_step
        current_time_step_index = initial_time_step_index
        refinement_rounds = 0
        retained_basin_count = 0
        while not exhausted and (current_date_step > 1 or current_time_step_index > 1):
            ranked_summaries = _rank_candidate_summaries(summary_by_key.values())
            basin_keys = _select_basin_keys(
                ranked_summaries,
                time_offsets_s,
                max_basins=DEFAULT_RETAINED_BASINS,
                date_gap=max(1, current_date_step // 2),
                time_gap=max(1, current_time_step_index // 2),
            )
            retained_basin_count = max(retained_basin_count, len(basin_keys))
            next_date_step = max(1, math.ceil(current_date_step / 2))
            next_time_step_index = max(1, math.ceil(current_time_step_index / 2))
            refinement_keys = _refinement_keys(
                basin_keys,
                max_date_index=day_count - 1,
                max_time_index=len(time_offsets_s) - 1,
                current_date_step=current_date_step,
                current_time_step_index=current_time_step_index,
                next_date_step=next_date_step,
                next_time_step_index=next_time_step_index,
            )
            evaluated_any = False
            for key in refinement_keys:
                if key not in summary_by_key:
                    evaluated_any = True
                if not evaluate_key(key, f"refine_{refinement_rounds + 1}"):
                    break
            if exhausted:
                break
            if not evaluated_any and not refinement_keys:
                break
            refinement_rounds += 1
            current_date_step = next_date_step
            current_time_step_index = next_time_step_index

        final_date_resolution_days = current_date_step
        final_time_resolution = final_resolution * current_time_step_index

    ranked_summaries = _rank_candidate_summaries(summary_by_key.values())
    if not ranked_summaries:
        raise ValueError("evaluation_budget is too small to evaluate any candidates")

    finalist_summaries = ranked_summaries[: DEFAULT_TOP_ALTERNATIVE_COUNT + 1]
    finalist_candidates = [
        _detailed_candidate(
            route=route,
            summary=summary,
            sun_position_at=sun_position_at,
            route_evaluator=route_evaluator,
        )
        for summary in finalist_summaries
    ]
    diagnostics = RouteDateRangeSearchDiagnostics(
        candidate_count_at_final_resolution=candidate_count,
        initial_date_step_days=initial_date_step,
        initial_time_step=final_resolution * initial_time_step_index,
        refinement_rounds=refinement_rounds,
        retained_basin_count=retained_basin_count,
        duplicate_candidate_evaluations_avoided=duplicate_evaluations_avoided,
        ambiguous_wall_times=ambiguous_wall_times,
        nonexistent_wall_times_adjusted=nonexistent_wall_times_adjusted,
        dst_transition_date_indices=tuple(dst_transition_indices),
        sampled_date_indices=tuple(
            sorted({summary.date_index for summary in summary_by_key.values()})
        ),
        sampled_time_offsets_s=tuple(
            sorted({summary.time_offset_s for summary in summary_by_key.values()})
        ),
    )
    candidate_summaries = _sort_candidate_summaries_for_display(summary_by_key.values())
    visualization_grid = _build_visualization_grid(
        route=route,
        request=request,
        candidate_summaries=candidate_summaries,
        default_fixed_time_offset_s=_seconds_since_midnight(
            finalist_candidates[0].requested_time.time()
        ),
        evaluation_by_departure_utc=evaluation_by_departure_utc,
        max_cells=max_visualization_cells,
        sun_position_at=sun_position_at,
        route_evaluator=route_evaluator,
    )
    return RouteDateRangeEvaluation(
        request=request,
        search_strategy="exact" if exact else "adaptive",
        candidate_summaries=candidate_summaries,
        ranked_candidate_summaries=ranked_summaries,
        recommended_candidate=finalist_candidates[0],
        top_alternative_candidates=finalist_candidates[1:],
        unique_evaluations=unique_evaluations,
        exact=exact,
        final_date_resolution_days=final_date_resolution_days,
        final_time_resolution=final_time_resolution,
        budget_outcome="exhausted" if exhausted else "within_budget",
        diagnostics=diagnostics,
        visualization_grid=visualization_grid,
    )


def validate_adaptive_date_range_against_exact(
    route: Route,
    start_date: date,
    end_date: date,
    daily_earliest_time: time,
    daily_latest_time: time,
    *,
    search_mode: RouteTimeSearchMode,
    timezone_name: str,
    adaptive_evaluation_budget: int = DEFAULT_DATE_RANGE_EVALUATION_BUDGET,
    final_resolution: timedelta = DEFAULT_SEARCH_INCREMENT,
    max_exact_evaluations: int = MAX_DATE_RANGE_EVALUATION_BUDGET,
    max_date_range_days: int = DEFAULT_MAX_DATE_RANGE_DAYS,
    sun_position_at: SunPositionResolver = get_sun_position,
    route_evaluator: RouteCandidateEvaluator | None = None,
) -> DateRangeExactValidation:
    """Compare adaptive date-range search with exhaustive search for small ranges."""

    candidate_count = (
        (end_date - start_date).days + 1
    ) * len(
        _final_time_offsets_s(
            daily_earliest_time,
            daily_latest_time,
            final_resolution,
        )
    )
    if candidate_count > max_exact_evaluations:
        raise ValueError("exact validation candidate count exceeds max_exact_evaluations")

    exact_evaluation = evaluate_route_date_range(
        route,
        start_date,
        end_date,
        daily_earliest_time,
        daily_latest_time,
        search_mode=search_mode,
        timezone_name=timezone_name,
        final_resolution=final_resolution,
        evaluation_budget=candidate_count,
        max_date_range_days=max_date_range_days,
        sun_position_at=sun_position_at,
        route_evaluator=route_evaluator,
    )
    adaptive_evaluation = evaluate_route_date_range(
        route,
        start_date,
        end_date,
        daily_earliest_time,
        daily_latest_time,
        search_mode=search_mode,
        timezone_name=timezone_name,
        final_resolution=final_resolution,
        evaluation_budget=adaptive_evaluation_budget,
        max_date_range_days=max_date_range_days,
        sun_position_at=sun_position_at,
        route_evaluator=route_evaluator,
    )
    exact_best_score = exact_evaluation.recommended_candidate.glare_score
    adaptive_best_score = adaptive_evaluation.recommended_candidate.glare_score
    exact_top_keys = {
        summary.requested_time.isoformat()
        for summary in exact_evaluation.ranked_candidate_summaries[
            : DEFAULT_TOP_ALTERNATIVE_COUNT + 1
        ]
    }
    adaptive_top_keys = {
        summary.requested_time.isoformat()
        for summary in adaptive_evaluation.ranked_candidate_summaries[
            : DEFAULT_TOP_ALTERNATIVE_COUNT + 1
        ]
    }
    exact_by_date = _best_score_by_date(exact_evaluation.candidate_summaries)
    adaptive_by_date = _best_score_by_date(adaptive_evaluation.candidate_summaries)
    return DateRangeExactValidation(
        exact_evaluation=exact_evaluation,
        adaptive_evaluation=adaptive_evaluation,
        recommended_candidate_matches=(
            exact_evaluation.recommended_candidate.requested_time
            == adaptive_evaluation.recommended_candidate.requested_time
        ),
        exact_best_score=exact_best_score,
        adaptive_best_score=adaptive_best_score,
        best_score_delta=adaptive_best_score - exact_best_score,
        top_candidate_overlap=len(exact_top_keys & adaptive_top_keys),
        per_date_best_score_delta={
            local_date: (
                None
                if local_date not in adaptive_by_date
                else adaptive_by_date[local_date] - exact_score
            )
            for local_date, exact_score in sorted(exact_by_date.items())
        },
    )


def _candidate_times(
    earliest_time: datetime,
    latest_time: datetime,
    increment: timedelta,
) -> list[datetime]:
    requested_times: list[datetime] = []
    requested_time = earliest_time
    while requested_time <= latest_time:
        requested_times.append(requested_time)
        requested_time += increment
    return requested_times


def _validate_window(
    earliest_time: datetime,
    latest_time: datetime,
    increment: timedelta,
    max_window: timedelta,
) -> None:
    if not _is_timezone_aware(earliest_time) or not _is_timezone_aware(latest_time):
        raise ValueError("earliest_time and latest_time must be timezone-aware")
    if latest_time < earliest_time:
        raise ValueError("latest_time must be greater than or equal to earliest_time")
    if increment <= timedelta(0):
        raise ValueError("increment must be greater than zero")
    if max_window < timedelta(0):
        raise ValueError("max_window must be greater than or equal to zero")
    if latest_time - earliest_time > max_window:
        raise ValueError("search window exceeds the maximum supported duration")


def _is_timezone_aware(moment: datetime) -> bool:
    return moment.tzinfo is not None and moment.utcoffset() is not None


def _add_elapsed_time(moment: datetime, duration: timedelta) -> datetime:
    return (moment.astimezone(UTC) + duration).astimezone(moment.tzinfo)


def _validate_date_range_request(
    *,
    route: Route,
    start_date: date,
    end_date: date,
    daily_earliest_time: time,
    daily_latest_time: time,
    search_mode: RouteTimeSearchMode,
    timezone_name: str,
    final_resolution: timedelta,
    evaluation_budget: int,
    max_date_range_days: int,
) -> ZoneInfo:
    if search_mode not in ("departure", "arrival"):
        raise ValueError("search_mode must be either 'departure' or 'arrival'")
    if route.metrics.duration_s < 0.0:
        raise ValueError("route duration must be greater than or equal to zero")
    if start_date > end_date:
        raise ValueError("start_date must not follow end_date")
    if (end_date - start_date).days + 1 > max_date_range_days:
        raise ValueError("date range exceeds the maximum supported duration")
    if _seconds_since_midnight(daily_latest_time) < _seconds_since_midnight(
        daily_earliest_time
    ):
        raise ValueError(
            "daily_latest_time must be greater than or equal to daily_earliest_time"
        )
    if final_resolution <= timedelta(0):
        raise ValueError("final_resolution must be greater than zero")
    if final_resolution.total_seconds() != int(final_resolution.total_seconds()):
        raise ValueError("final_resolution must be a whole number of seconds")
    if evaluation_budget <= 0:
        raise ValueError("evaluation_budget must be greater than zero")
    if evaluation_budget > MAX_DATE_RANGE_EVALUATION_BUDGET:
        raise ValueError(
            f"evaluation_budget must be at most {MAX_DATE_RANGE_EVALUATION_BUDGET}"
        )
    if max_date_range_days <= 0:
        raise ValueError("max_date_range_days must be greater than zero")
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("timezone_name must be a valid IANA timezone") from exc


def _validate_visualization_budget(max_visualization_cells: int) -> None:
    if max_visualization_cells <= 0:
        raise ValueError("max_visualization_cells must be greater than zero")


def _seconds_since_midnight(value: time) -> int:
    if value.microsecond:
        raise ValueError("daily time values must use whole seconds")
    return (value.hour * 3600) + (value.minute * 60) + value.second


def _final_time_offsets_s(
    earliest_time: time,
    latest_time: time,
    final_resolution: timedelta,
) -> list[int]:
    earliest_s = _seconds_since_midnight(earliest_time)
    latest_s = _seconds_since_midnight(latest_time)
    step_s = int(final_resolution.total_seconds())
    offsets = list(range(earliest_s, latest_s + 1, step_s))
    if not offsets or offsets[-1] != latest_s:
        offsets.append(latest_s)
    return offsets


def _local_time_from_offset(offset_s: int) -> time:
    hour, remainder = divmod(offset_s, 3600)
    minute, second = divmod(remainder, 60)
    return time(hour=hour, minute=minute, second=second)


def _resolve_local_wall_time(
    local_date: date,
    local_time: time,
    timezone: ZoneInfo,
) -> tuple[datetime, str | None]:
    naive = datetime.combine(local_date, local_time)
    valid_by_utc = _valid_local_wall_times(naive, timezone)
    if valid_by_utc:
        ordered = sorted(valid_by_utc.items(), key=lambda item: item[0])
        status = "ambiguous" if len(ordered) > 1 else None
        return ordered[0][1], status

    shifted = naive + timedelta(minutes=1)
    while shifted.date() == local_date:
        shifted_time = shifted.replace(second=0, microsecond=0)
        shifted_valid_by_utc = _valid_local_wall_times(shifted_time, timezone)
        if shifted_valid_by_utc:
            ordered = sorted(shifted_valid_by_utc.items(), key=lambda item: item[0])
            return ordered[0][1], "nonexistent"
        shifted += timedelta(minutes=1)
    raise ValueError("daily time window contains no valid local time")


def _valid_local_wall_times(
    naive: datetime,
    timezone: ZoneInfo,
) -> dict[datetime, datetime]:
    valid_by_utc: dict[datetime, datetime] = {}
    for fold in (0, 1):
        aware = naive.replace(tzinfo=timezone, fold=fold)
        roundtrip = aware.astimezone(UTC).astimezone(timezone).replace(tzinfo=None)
        if roundtrip == naive:
            valid_by_utc[aware.astimezone(UTC)] = aware
    return valid_by_utc


def _candidate_timing(
    requested_time: datetime,
    search_mode: RouteTimeSearchMode,
    route_duration: timedelta,
    timezone: ZoneInfo,
) -> _CandidateTiming:
    if search_mode == "departure":
        departure_time = requested_time
        arrival_time = (departure_time.astimezone(UTC) + route_duration).astimezone(
            timezone
        )
    else:
        arrival_time = requested_time
        departure_time = (arrival_time.astimezone(UTC) - route_duration).astimezone(
            timezone
        )
    return _CandidateTiming(
        requested_time=requested_time,
        departure_time=departure_time,
        arrival_time=arrival_time,
    )


def _evaluate_candidate_route(
    *,
    route: Route,
    timing: _CandidateTiming,
    include_segment_risks: bool,
    sun_position_at: SunPositionResolver,
    route_evaluator: RouteCandidateEvaluator | None,
) -> RouteEvaluation:
    if route_evaluator is not None:
        return route_evaluator(
            route,
            timing.requested_time,
            timing.departure_time,
            timing.arrival_time,
            include_segment_risks,
        )
    return evaluate_route(
        route,
        timing.departure_time,
        sun_position_at=sun_position_at,
        include_segment_risks=include_segment_risks,
    )


def _initial_step(item_count: int) -> int:
    if item_count <= 1:
        return 1
    return max(1, math.ceil((item_count - 1) / COARSE_GRID_TARGET_PER_AXIS))


def _initial_indices(item_count: int, step: int) -> list[int]:
    max_index = item_count - 1
    values = set(range(0, item_count, step))
    values.add(max_index)
    for numerator in (1, 2, 3):
        values.add(round(max_index * numerator / 4))
    return sorted(values)


def _initial_date_indices(
    day_count: int,
    step: int,
    dst_transition_indices: list[int],
) -> list[int]:
    values = set(_initial_indices(day_count, step))
    values.update(dst_transition_indices)
    return sorted(index for index in values if 0 <= index < day_count)


def _dst_transition_date_indices(
    start_date: date,
    day_count: int,
    timezone: ZoneInfo,
) -> list[int]:
    indices: set[int] = set()
    previous_offset = _noon_offset(start_date, timezone)
    for index in range(1, day_count):
        current_offset = _noon_offset(start_date + timedelta(days=index), timezone)
        if current_offset != previous_offset:
            indices.update(
                candidate
                for candidate in (index - 1, index, index + 1)
                if 0 <= candidate < day_count
            )
        previous_offset = current_offset
    return sorted(indices)


def _noon_offset(local_date: date, timezone: ZoneInfo) -> timedelta | None:
    return datetime.combine(local_date, time(12, 0), tzinfo=timezone).utcoffset()


def _sorted_keys(date_indices: list[int], time_indices: list[int]) -> list[_SearchKey]:
    return [
        _SearchKey(date_index, time_index)
        for date_index in sorted(date_indices)
        for time_index in sorted(time_indices)
    ]


def _rank_candidate_summaries(
    summaries: Iterable[RouteDateRangeCandidateSummary],
) -> list[RouteDateRangeCandidateSummary]:
    return sorted(
        summaries,
        key=lambda summary: (
            summary.glare_score,
            summary.high_risk_duration_s,
            summary.requested_time,
        ),
    )


def _sort_candidate_summaries_for_display(
    summaries: Iterable[RouteDateRangeCandidateSummary],
) -> list[RouteDateRangeCandidateSummary]:
    return sorted(
        summaries,
        key=lambda summary: (
            summary.requested_time,
            summary.departure_time.astimezone(UTC),
        ),
    )


def _best_score_by_date(
    summaries: Iterable[RouteDateRangeCandidateSummary],
) -> dict[date, float]:
    best_by_date: dict[date, float] = {}
    for summary in summaries:
        local_date = summary.requested_time.date()
        if local_date not in best_by_date:
            best_by_date[local_date] = summary.glare_score
        else:
            best_by_date[local_date] = min(
                best_by_date[local_date],
                summary.glare_score,
            )
    return best_by_date


def _select_basin_keys(
    ranked_summaries: list[RouteDateRangeCandidateSummary],
    time_offsets_s: list[int],
    *,
    max_basins: int,
    date_gap: int,
    time_gap: int,
) -> list[_SearchKey]:
    offset_to_index = {offset: index for index, offset in enumerate(time_offsets_s)}
    selected: list[_SearchKey] = []
    for summary in ranked_summaries:
        key = _SearchKey(summary.date_index, offset_to_index[summary.time_offset_s])
        if all(
            abs(key.date_index - existing.date_index) > date_gap
            or abs(key.time_index - existing.time_index) > time_gap
            for existing in selected
        ):
            selected.append(key)
        if len(selected) >= max_basins:
            return selected

    for summary in ranked_summaries:
        key = _SearchKey(summary.date_index, offset_to_index[summary.time_offset_s])
        if key not in selected:
            selected.append(key)
        if len(selected) >= max_basins:
            break
    return selected


def _refinement_keys(
    basin_keys: list[_SearchKey],
    *,
    max_date_index: int,
    max_time_index: int,
    current_date_step: int,
    current_time_step_index: int,
    next_date_step: int,
    next_time_step_index: int,
) -> list[_SearchKey]:
    keys: set[_SearchKey] = set()
    for basin in basin_keys:
        date_start = max(0, basin.date_index - current_date_step)
        date_end = min(max_date_index, basin.date_index + current_date_step)
        time_start = max(0, basin.time_index - current_time_step_index)
        time_end = min(max_time_index, basin.time_index + current_time_step_index)
        date_indices = set(range(date_start, date_end + 1, next_date_step))
        time_indices = set(range(time_start, time_end + 1, next_time_step_index))
        date_indices.update({date_start, basin.date_index, date_end})
        time_indices.update({time_start, basin.time_index, time_end})
        for date_index in date_indices:
            for time_index in time_indices:
                keys.add(_SearchKey(date_index, time_index))
    return sorted(keys, key=lambda key: (key.date_index, key.time_index))


def _detailed_candidate(
    *,
    route: Route,
    summary: RouteDateRangeCandidateSummary,
    sun_position_at: SunPositionResolver,
    route_evaluator: RouteCandidateEvaluator | None,
) -> RouteTimeCandidate:
    timing = _CandidateTiming(
        requested_time=summary.requested_time,
        departure_time=summary.departure_time,
        arrival_time=summary.arrival_time,
    )
    route_evaluation = _evaluate_candidate_route(
        route=route,
        timing=timing,
        include_segment_risks=True,
        sun_position_at=sun_position_at,
        route_evaluator=route_evaluator,
    )
    return RouteTimeCandidate(
        requested_time=summary.requested_time,
        departure_time=summary.departure_time,
        arrival_time=summary.arrival_time,
        route_evaluation=route_evaluation,
    )


def _build_visualization_grid(
    *,
    route: Route,
    request: RouteDateRangeRequest,
    candidate_summaries: list[RouteDateRangeCandidateSummary],
    default_fixed_time_offset_s: int,
    evaluation_by_departure_utc: dict[datetime, RouteEvaluation],
    max_cells: int,
    sun_position_at: SunPositionResolver,
    route_evaluator: RouteCandidateEvaluator | None,
) -> RouteDateRangeVisualizationGrid:
    started_at = perf_counter()
    timezone = ZoneInfo(request.timezone_name)
    day_count = (request.end_date - request.start_date).days + 1
    date_interval_days, time_interval = _visualization_intervals(
        day_count,
        request.daily_earliest_time,
        request.daily_latest_time,
        max_cells,
    )
    date_indices = _visualization_date_indices(day_count, date_interval_days)
    time_offsets_s = _final_time_offsets_s(
        request.daily_earliest_time,
        request.daily_latest_time,
        time_interval,
    )
    requested_cell_count = len(date_indices) * len(time_offsets_s)
    route_duration = timedelta(seconds=route.metrics.duration_s)
    optimizer_utc_keys = {
        summary.departure_time.astimezone(UTC) for summary in candidate_summaries
    }

    cells: list[RouteDateRangeVisualizationCell] = []
    invalid_wall_time_count = 0
    reused_optimizer_evaluations = 0
    new_evaluations = 0

    for date_index in date_indices:
        local_date = request.start_date + timedelta(days=date_index)
        for time_offset_s in time_offsets_s:
            local_time = _local_time_from_offset(time_offset_s)
            local_moment = _resolve_visualization_wall_time(
                local_date,
                local_time,
                timezone,
            )
            if local_moment is None:
                invalid_wall_time_count += 1
                continue

            timing = _candidate_timing(
                local_moment,
                request.search_mode,
                route_duration,
                timezone,
            )
            departure_utc = timing.departure_time.astimezone(UTC)
            route_evaluation = evaluation_by_departure_utc.get(departure_utc)
            reused_optimizer_evaluation = departure_utc in optimizer_utc_keys
            if route_evaluation is None:
                route_evaluation = _evaluate_candidate_route(
                    route=route,
                    timing=timing,
                    include_segment_risks=False,
                    sun_position_at=sun_position_at,
                    route_evaluator=route_evaluator,
                )
                evaluation_by_departure_utc[departure_utc] = route_evaluation
                new_evaluations += 1
            elif reused_optimizer_evaluation:
                reused_optimizer_evaluations += 1

            cells.append(
                _visualization_cell(
                    route=route,
                    date_index=date_index,
                    time_offset_s=time_offset_s,
                    requested_wall_date=local_date,
                    requested_wall_time=local_time,
                    timing=timing,
                    route_evaluation=route_evaluation,
                    reused_optimizer_evaluation=reused_optimizer_evaluation,
                )
            )

    fixed_time_offset_s = _nearest_offset_s(
        time_offsets_s,
        default_fixed_time_offset_s,
    )
    representative_best_times = _representative_best_times(
        cells,
        time_interval_s=int(time_interval.total_seconds()),
    )
    large_adjacent_changes = _large_adjacent_changes(cells)
    diagnostics = RouteDateRangeVisualizationDiagnostics(
        route_geometry_fingerprint=_route_geometry_fingerprint(route.geometry),
        date_interval_days=date_interval_days,
        time_interval=time_interval,
        requested_cell_count=requested_cell_count,
        evaluated_cell_count=len(cells),
        reused_optimizer_evaluations=reused_optimizer_evaluations,
        new_evaluations=new_evaluations,
        evaluation_time_s=round(perf_counter() - started_at, 4),
        invalid_wall_time_count=invalid_wall_time_count,
        dst_transition_dates=tuple(
            _dst_transition_dates(request.start_date, day_count, timezone)
        ),
        large_adjacent_change_count=len(large_adjacent_changes),
    )
    return RouteDateRangeVisualizationGrid(
        cells=cells,
        representative_best_times=representative_best_times,
        fixed_time_offset_s=fixed_time_offset_s,
        diagnostics=diagnostics,
        large_adjacent_changes=large_adjacent_changes,
    )


def _visualization_intervals(
    day_count: int,
    earliest_time: time,
    latest_time: time,
    max_cells: int,
) -> tuple[int, timedelta]:
    if day_count <= 31:
        date_interval_days = 1
        time_interval = timedelta(minutes=15)
    elif day_count <= 120:
        date_interval_days = 3
        time_interval = timedelta(minutes=30)
    else:
        date_interval_days = 7
        time_interval = timedelta(minutes=30)

    base_date_interval_days = date_interval_days
    base_time_interval = time_interval
    while True:
        date_count = len(_visualization_date_indices(day_count, date_interval_days))
        time_count = len(_final_time_offsets_s(earliest_time, latest_time, time_interval))
        if date_count * time_count <= max_cells:
            return date_interval_days, time_interval
        if time_count >= date_count:
            time_interval += base_time_interval
        else:
            date_interval_days += base_date_interval_days


def _visualization_date_indices(day_count: int, date_interval_days: int) -> list[int]:
    indices = list(range(0, day_count, date_interval_days))
    if indices[-1] != day_count - 1:
        indices.append(day_count - 1)
    return indices


def _resolve_visualization_wall_time(
    local_date: date,
    local_time: time,
    timezone: ZoneInfo,
) -> datetime | None:
    valid_by_utc = _valid_local_wall_times(datetime.combine(local_date, local_time), timezone)
    if not valid_by_utc:
        return None
    return sorted(valid_by_utc.items(), key=lambda item: item[0])[0][1]


def _visualization_cell(
    *,
    route: Route,
    date_index: int,
    time_offset_s: int,
    requested_wall_date: date,
    requested_wall_time: time,
    timing: _CandidateTiming,
    route_evaluation: RouteEvaluation,
    reused_optimizer_evaluation: bool,
) -> RouteDateRangeVisualizationCell:
    utc_offset = timing.requested_time.utcoffset() or timedelta(0)
    peak_segment = route_evaluation.peak_glare_segment
    return RouteDateRangeVisualizationCell(
        requested_wall_date=requested_wall_date,
        requested_wall_time=requested_wall_time,
        requested_time=timing.requested_time,
        departure_time=timing.departure_time,
        arrival_time=timing.arrival_time,
        glare_score=route_evaluation.glare_score,
        high_risk_duration_s=route_evaluation.high_risk_duration_s,
        high_risk_distance_m=route_evaluation.high_risk_distance_m,
        peak_glare_score=route_evaluation.peak_glare_score,
        peak_glare_category=route_evaluation.peak_glare_category,
        utc_offset_minutes=int(utc_offset.total_seconds() / 60),
        date_index=date_index,
        time_offset_s=time_offset_s,
        reused_optimizer_evaluation=reused_optimizer_evaluation,
        peak_segment_index=_peak_segment_index(route, peak_segment),
        peak_segment_sun_azimuth_deg=None
        if peak_segment is None
        else peak_segment.sun_position.azimuth_deg,
        peak_segment_sun_elevation_deg=None
        if peak_segment is None
        else peak_segment.sun_position.elevation_deg,
        peak_segment_angle_difference_deg=None
        if peak_segment is None
        else peak_segment.angle_difference_deg,
        peak_segment_bearing_deg=None if peak_segment is None else peak_segment.bearing_deg,
        high_risk_threshold_crossed=route_evaluation.peak_glare_score
        >= HIGH_RISK_SEGMENT_SCORE,
    )


def _peak_segment_index(route: Route, peak_segment: object | None) -> int | None:
    if peak_segment is None:
        return None
    start = getattr(peak_segment, "start_coordinates", None)
    end = getattr(peak_segment, "end_coordinates", None)
    for index, (segment_start, segment_end) in enumerate(
        zip(route.geometry, route.geometry[1:])
    ):
        if segment_start == start and segment_end == end:
            return index
    return None


def _representative_best_times(
    cells: list[RouteDateRangeVisualizationCell],
    *,
    time_interval_s: int,
) -> list[RouteDateRangeBestTimePoint]:
    by_date: dict[date, list[RouteDateRangeVisualizationCell]] = {}
    for cell in cells:
        by_date.setdefault(cell.requested_wall_date, []).append(cell)

    points: list[RouteDateRangeBestTimePoint] = []
    for sampled_date, date_cells in sorted(by_date.items()):
        ordered = sorted(date_cells, key=lambda cell: cell.time_offset_s)
        minimum_score = min(cell.glare_score for cell in ordered)
        qualifying = [
            cell
            for cell in ordered
            if cell.glare_score <= minimum_score + NEAR_OPTIMAL_SCORE_TOLERANCE
        ]
        intervals: list[list[RouteDateRangeVisualizationCell]] = []
        current: list[RouteDateRangeVisualizationCell] = []
        for cell in qualifying:
            if (
                current
                and cell.time_offset_s - current[-1].time_offset_s > time_interval_s
            ):
                intervals.append(current)
                current = []
            current.append(cell)
        if current:
            intervals.append(current)
        if not intervals:
            continue

        selected = min(
            intervals,
            key=lambda interval: (
                -(_interval_span_s(interval)),
                _interval_average_score(interval),
                interval[0].time_offset_s,
            ),
        )
        midpoint_offset_s = round(
            (selected[0].time_offset_s + selected[-1].time_offset_s) / 2
        )
        points.append(
            RouteDateRangeBestTimePoint(
                sampled_date=sampled_date,
                representative_time=_local_time_from_offset(midpoint_offset_s),
                representative_time_offset_s=midpoint_offset_s,
                minimum_glare_score=minimum_score,
                interval_average_score=_interval_average_score(selected),
            )
        )
    return points


def _interval_span_s(interval: list[RouteDateRangeVisualizationCell]) -> int:
    return interval[-1].time_offset_s - interval[0].time_offset_s


def _interval_average_score(interval: list[RouteDateRangeVisualizationCell]) -> float:
    return sum(cell.glare_score for cell in interval) / len(interval)


def _large_adjacent_changes(
    cells: list[RouteDateRangeVisualizationCell],
    *,
    threshold: float = DEFAULT_LARGE_CHANGE_THRESHOLD,
) -> list[RouteDateRangeAdjacentChange]:
    by_time: dict[int, list[RouteDateRangeVisualizationCell]] = {}
    for cell in cells:
        by_time.setdefault(cell.time_offset_s, []).append(cell)

    changes: list[RouteDateRangeAdjacentChange] = []
    for time_offset_s in sorted(by_time):
        ordered = sorted(
            by_time[time_offset_s],
            key=lambda cell: cell.requested_wall_date,
        )
        for previous, current in zip(ordered, ordered[1:]):
            delta = current.glare_score - previous.glare_score
            if abs(delta) < threshold:
                continue
            changes.append(
                RouteDateRangeAdjacentChange(
                    previous_date=previous.requested_wall_date,
                    current_date=current.requested_wall_date,
                    requested_wall_time=current.requested_wall_time,
                    previous_utc_offset_minutes=previous.utc_offset_minutes,
                    current_utc_offset_minutes=current.utc_offset_minutes,
                    previous_glare_score=previous.glare_score,
                    current_glare_score=current.glare_score,
                    score_delta=round(delta, 2),
                    previous_peak_sun_azimuth_deg=(
                        previous.peak_segment_sun_azimuth_deg
                    ),
                    current_peak_sun_azimuth_deg=current.peak_segment_sun_azimuth_deg,
                    previous_peak_sun_elevation_deg=(
                        previous.peak_segment_sun_elevation_deg
                    ),
                    current_peak_sun_elevation_deg=(
                        current.peak_segment_sun_elevation_deg
                    ),
                    previous_peak_segment_index=previous.peak_segment_index,
                    current_peak_segment_index=current.peak_segment_index,
                    previous_peak_segment_score=previous.peak_glare_score,
                    current_peak_segment_score=current.peak_glare_score,
                    previous_peak_angle_difference_deg=(
                        previous.peak_segment_angle_difference_deg
                    ),
                    current_peak_angle_difference_deg=(
                        current.peak_segment_angle_difference_deg
                    ),
                    previous_peak_bearing_deg=previous.peak_segment_bearing_deg,
                    current_peak_bearing_deg=current.peak_segment_bearing_deg,
                    scoring_threshold_crossed=(
                        previous.high_risk_threshold_crossed
                        != current.high_risk_threshold_crossed
                    ),
                )
            )
    return changes


def _nearest_offset_s(offsets: list[int], target_offset_s: int) -> int:
    return min(offsets, key=lambda offset: (abs(offset - target_offset_s), offset))


def _dst_transition_dates(
    start_date: date,
    day_count: int,
    timezone: ZoneInfo,
) -> list[date]:
    transition_dates: list[date] = []
    previous_offset = _noon_offset(start_date, timezone)
    for index in range(1, day_count):
        current_date = start_date + timedelta(days=index)
        current_offset = _noon_offset(current_date, timezone)
        if current_offset != previous_offset:
            transition_dates.append(current_date)
        previous_offset = current_offset
    return transition_dates


def _route_geometry_fingerprint(geometry: list[Coordinates]) -> str:
    digest = hashlib.sha256()
    for coordinate in geometry:
        digest.update(f"{coordinate.lat:.7f},{coordinate.lon:.7f};".encode("ascii"))
    return digest.hexdigest()[:16]
