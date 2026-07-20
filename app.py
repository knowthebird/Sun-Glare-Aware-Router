from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
import logging
from time import perf_counter
from typing import cast
from zoneinfo import ZoneInfo

import folium
import streamlit as st
from streamlit_folium import st_folium

from src.config import ConfigError, Settings, load_settings, supported_timezones
from src.geocoding import Geocoder, SuggestionProvider, build_geocoder
from src.geocoding import build_suggestion_provider
from src.i18n import t
from src.mapview import build_picker_map, build_route_map
from src.models import (
    AnalysisRequest,
    AnalysisResult,
    AddressSuggestion,
    Coordinates,
    DateRangeEvaluationParams,
    GeocodeResult,
    LocationPickerState,
    Route,
    RouteDateRangeEvaluation,
    RouteAlternativesResult,
    RouteEvaluation,
    RouteTimeSearchMode,
    RouteTimeWindowEvaluation,
    SelectedLocation,
    SunPosition,
    TimeWindowEvaluationParams,
)
from src.pickers import (
    apply_picker_search_result,
    apply_picker_suggestion_result,
    build_analysis_request,
    can_generate_routes,
    confirm_picker_location,
    create_picker_state,
)
from src.routing import Router, build_router
from src.route_time_search import (
    evaluate_route_date_range,
    evaluate_route_time_window,
)
from src.scoring import explain_recommendation, rank_routes
from src.time_window_ui import (
    build_time_window,
    candidate_choice_label,
    candidate_key,
    candidate_result_rows,
    date_range_candidate_choice_label,
    date_range_candidate_options,
    date_range_candidate_sample_rows,
    date_range_default_fixed_time_offset,
    date_range_dst_transition_caption,
    date_range_dst_annotation_rows,
    date_range_evaluated_candidate_chart_rows,
    date_range_evaluated_candidates_caption,
    date_range_fixed_time_chart_rows,
    date_range_fixed_time_title,
    date_range_grid_debug_summary,
    date_range_heatmap_axis_label,
    date_range_heatmap_rows,
    date_range_heatmap_title,
    date_range_best_time_overlay_rows,
    date_range_large_change_rows,
    date_range_overview_caption,
    date_range_overview_chart_rows,
    date_range_overview_title,
    date_range_params_match_current,
    date_range_preset_dates,
    date_range_result_signature,
    date_range_top_candidate_rows,
    date_range_visualization_caption,
    date_range_visualization_performance_caption,
    date_range_visualization_time_offsets,
    fastest_route_id,
    find_candidate_by_key,
    find_date_range_candidate_by_key,
    find_route_by_id,
    glare_chart_rows,
    route_choice_labels,
    route_display_name as time_window_route_display_name,
    time_offset_label,
    time_window_params_match_current,
    time_window_result_signature,
)

try:
    from streamlit_searchbox import st_searchbox  # type: ignore[reportMissingImports]
except ModuleNotFoundError:  # pragma: no cover - exercised by deployment shape
    st_searchbox = None
from src.timezones import (
    CoordinateTimezoneFinder,
    ResolvedTimezone,
    is_valid_timezone_name,
    resolve_automatic_timezone,
)
from src.utils import (
    ProviderError,
    configure_logging,
    format_datetime_with_zone,
    format_distance_km,
    format_duration_minutes,
)

ANALYSIS_RESULT_STATE_KEY = "sunrouter_analysis_result"
ROUTE_ALTERNATIVES_STATE_KEY = "sunrouter_route_alternatives"
TIME_WINDOW_RESULT_STATE_KEY = "sunrouter_time_window_result"
TIME_WINDOW_PARAMS_STATE_KEY = "sunrouter_time_window_params"
DATE_RANGE_RESULT_STATE_KEY = "sunrouter_date_range_result"
DATE_RANGE_PARAMS_STATE_KEY = "sunrouter_date_range_params"
ORIGIN_PICKER_STATE_KEY = "sunrouter_origin_picker_state"
DESTINATION_PICKER_STATE_KEY = "sunrouter_destination_picker_state"
SEARCH_SCOPE_STATE_KEY = "sunrouter_search_scope"
TRIP_DATE_STATE_KEY = "sunrouter_trip_date"
TRIP_TIME_STATE_KEY = "sunrouter_trip_time"
WINDOW_MODE_STATE_KEY = "sunrouter_window_mode"
WINDOW_EARLIEST_TIME_STATE_KEY = "sunrouter_window_earliest_time"
WINDOW_LATEST_TIME_STATE_KEY = "sunrouter_window_latest_time"
DATE_RANGE_START_DATE_STATE_KEY = "sunrouter_date_range_start_date"
DATE_RANGE_END_DATE_STATE_KEY = "sunrouter_date_range_end_date"
DATE_RANGE_MODE_STATE_KEY = "sunrouter_date_range_mode"
DATE_RANGE_EARLIEST_TIME_STATE_KEY = "sunrouter_date_range_earliest_time"
DATE_RANGE_LATEST_TIME_STATE_KEY = "sunrouter_date_range_latest_time"
SELECTED_ROUTE_ID_STATE_KEY = "sunrouter_selected_route_id"
INSPECTED_CANDIDATE_KEY_STATE_KEY = "sunrouter_inspected_candidate_key"
INSPECTED_RESULT_SIGNATURE_STATE_KEY = "sunrouter_inspected_result_signature"
DATE_RANGE_INSPECTED_CANDIDATE_KEY_STATE_KEY = (
    "sunrouter_date_range_inspected_candidate_key"
)
DATE_RANGE_FIXED_TIME_OFFSET_STATE_KEY = "sunrouter_date_range_fixed_time_offset"
DATE_RANGE_INSPECTED_RESULT_SIGNATURE_STATE_KEY = (
    "sunrouter_date_range_inspected_result_signature"
)
TIMEZONE_STATE_KEY = "sunrouter_timezone"
TIMEZONE_MODE_STATE_KEY = "sunrouter_timezone_mode"
TIMEZONE_SOURCE_STATE_KEY = "sunrouter_timezone_source"
LANGUAGE_STATE_KEY = "sunrouter_language"
LANGUAGE_WIDGET_STATE_KEY = "sunrouter_language_widget"
RECENT_SUGGESTIONS_STATE_KEY = "sunrouter_recent_suggestions"
TIMEZONE_MODE_AUTOMATIC = "automatic"
TIMEZONE_MODE_MANUAL = "manual"
DEFAULT_ORIGIN_QUERY = "Washington, District of Columbia, United States"
DEFAULT_DESTINATION_QUERY = "Sacramento, California, United States"
DEFAULT_ORIGIN_LOCATION = SelectedLocation(
    coordinates=Coordinates(lat=38.89510, lon=-77.03638),
    label=DEFAULT_ORIGIN_QUERY,
    label_source="demo",
)
DEFAULT_DESTINATION_LOCATION = SelectedLocation(
    coordinates=Coordinates(lat=38.58106, lon=-121.49389),
    label=DEFAULT_DESTINATION_QUERY,
    label_source="demo",
)
DEFAULT_MAP_CENTER = Coordinates(lat=38.89510, lon=-77.03638)

logger = logging.getLogger("sunrouter.app")


@st.cache_resource
def get_geocoder(settings: Settings) -> Geocoder:
    return build_geocoder(settings)


@st.cache_resource
def get_suggestion_provider(settings: Settings) -> SuggestionProvider:
    return build_suggestion_provider(settings)


@st.cache_resource
def get_router(settings: Settings) -> Router:
    return build_router(settings)


def get_picker_map(
    map_center: Coordinates,
    provisional_result: GeocodeResult | None,
    confirmed_location: SelectedLocation | None,
    picker_kind: str,
    language: str,
) -> folium.Map:
    return build_picker_map(
        LocationPickerState(
            query_text="",
            provisional_result=provisional_result,
            map_center=map_center,
            confirmed_location=confirmed_location,
            map_revision=0,
        ),
        picker_kind,
        language=language,
    )


def get_route_map(
    origin: Coordinates,
    destination: Coordinates,
    evaluations: tuple[RouteEvaluation, ...],
    recommended_route_id: str | None,
    language: str,
    trip_start_moment: datetime | None = None,
) -> folium.Map:
    return build_route_map(
        origin=origin,
        destination=destination,
        evaluations=list(evaluations),
        recommended_route_id=recommended_route_id,
        language=language,
        trip_start_moment=trip_start_moment,
    )


def inject_app_styles() -> None:
    st.markdown(
        """
        <style>
        .stApp {
            background:
                radial-gradient(circle at top left, rgba(45, 212, 191, 0.14), transparent 28%),
                radial-gradient(circle at top right, rgba(96, 165, 250, 0.12), transparent 24%),
                linear-gradient(180deg, #07111b 0%, #0b1722 100%);
        }
        .block-container {
            padding-top: 1.35rem;
            padding-bottom: 2.4rem;
        }
        .sunrouter-shell {
            background: linear-gradient(180deg, rgba(17, 24, 39, 0.92) 0%, rgba(15, 23, 42, 0.92) 100%);
            border: 1px solid rgba(45, 212, 191, 0.28);
            box-shadow: 0 20px 48px rgba(2, 8, 23, 0.28);
            border-radius: 18px;
            padding: 1rem 1.1rem;
            margin: 0.2rem 0 1rem 0;
            color: #dbeafe;
        }
        .sunrouter-shell strong {
            color: #f8fafc;
        }
        .sunrouter-note {
            background: rgba(13, 23, 39, 0.92);
            border: 1px solid rgba(96, 165, 250, 0.24);
            border-left: 4px solid #2dd4bf;
            border-radius: 14px;
            color: #dbeafe;
            padding: 0.85rem 1rem;
            margin: 0.35rem 0 0.9rem 0;
        }
        .sunrouter-table-shell {
            background: rgba(8, 15, 28, 0.92);
            border: 1px solid rgba(148, 163, 184, 0.18);
            border-radius: 18px;
            padding: 0.7rem 0.9rem 1rem 0.9rem;
            margin-top: 1rem;
        }
        div[data-testid="stMetric"] {
            background: rgba(15, 23, 42, 0.88);
            border: 1px solid rgba(148, 163, 184, 0.2);
            border-radius: 16px;
            padding: 0.7rem 0.8rem;
        }
        div[data-testid="stMetricLabel"] p {
            color: #93c5fd;
            font-weight: 600;
        }
        div[data-testid="stMetricValue"] {
            color: #f8fafc;
        }
        div[data-testid="stExpander"] {
            border-radius: 16px;
            border: 1px solid rgba(148, 163, 184, 0.2);
            background: rgba(15, 23, 42, 0.76);
        }
        div[data-testid="stForm"] {
            background: rgba(15, 23, 42, 0.74);
            border: 1px solid rgba(148, 163, 184, 0.18);
            border-radius: 16px;
            padding: 0.8rem 0.8rem 0.2rem 0.8rem;
        }
        div[data-testid="stDataFrame"] {
            border-radius: 16px;
            overflow: hidden;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def get_language_code() -> str:
    if LANGUAGE_STATE_KEY not in st.session_state:
        st.session_state[LANGUAGE_STATE_KEY] = "en"
    if LANGUAGE_WIDGET_STATE_KEY not in st.session_state:
        st.session_state[LANGUAGE_WIDGET_STATE_KEY] = "EN"
    return str(st.session_state[LANGUAGE_STATE_KEY])


def render_language_toggle() -> str:
    if LANGUAGE_WIDGET_STATE_KEY not in st.session_state:
        st.session_state[LANGUAGE_WIDGET_STATE_KEY] = "EN"
    selected_language = st.radio(
        t("es", "ui.language_label"),
        options=["ES", "EN"],
        key=LANGUAGE_WIDGET_STATE_KEY,
        horizontal=True,
    )
    language = "es" if selected_language == "ES" else "en"
    st.session_state[LANGUAGE_STATE_KEY] = language
    return language


def route_display_name(evaluation: RouteEvaluation, index: int, language: str) -> str:
    route_index = evaluation.route.metadata.get("route_index")
    if isinstance(route_index, int) and route_index > 0:
        return t(language, "common.option", index=route_index)
    return t(language, "common.option", index=index)


def _add_elapsed_time(moment: datetime, duration: timedelta) -> datetime:
    if moment.tzinfo is None or moment.utcoffset() is None:
        return moment + duration
    return (moment.astimezone(UTC) + duration).astimezone(moment.tzinfo)


def _format_time_relative_to_trip(moment: datetime, trip_start_moment: datetime) -> str:
    if moment.date() == trip_start_moment.date():
        return moment.strftime("%H:%M")
    return format_datetime_with_zone(moment)


def _format_trip_endpoint(moment: datetime, departure: datetime, arrival: datetime) -> str:
    if departure.date() == arrival.date():
        return moment.strftime("%H:%M")
    return format_datetime_with_zone(moment)


def _render_continuous_driving_notice(duration_s: float, language: str) -> None:
    if duration_s >= 12 * 60 * 60:
        st.caption(t(language, "time_window.continuous_driving_notice"))


def peak_risk_summary(
    evaluation: RouteEvaluation,
    trip_start_moment: datetime,
    language: str = "es",
) -> tuple[str, str]:
    if evaluation.peak_risk_time_offset_min is None:
        return (t(language, "common.no_peak"), "-")

    peak_moment = _add_elapsed_time(
        trip_start_moment,
        timedelta(minutes=evaluation.peak_risk_time_offset_min),
    )
    peak_time = _format_time_relative_to_trip(peak_moment, trip_start_moment)
    if evaluation.peak_risk_distance_m is None:
        return (peak_time, "-")

    return (
        peak_time,
        t(
            language,
            "common.km_value",
            distance=evaluation.peak_risk_distance_m / 1000.0,
        ),
    )


def comparison_rows(
    route_evaluations: list[RouteEvaluation],
    recommended_route_id: str,
    fastest_route_id: str,
    trip_start_moment: datetime,
    language: str = "es",
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, evaluation in enumerate(route_evaluations, start=1):
        peak_time, peak_distance = peak_risk_summary(
            evaluation,
            trip_start_moment,
            language,
        )
        rows.append(
            {
                t(language, "table.route"): route_display_name(
                    evaluation,
                    index,
                    language,
                ),
                t(language, "table.recommended"): t(language, "common.yes")
                if evaluation.route.route_id == recommended_route_id
                else "",
                t(language, "table.fastest"): t(language, "common.yes")
                if evaluation.route.route_id == fastest_route_id
                else "",
                t(language, "metrics.distance"): format_distance_km(
                    evaluation.route.metrics.distance_m
                ),
                t(language, "metrics.duration"): format_duration_minutes(
                    evaluation.route.metrics.duration_s
                ),
                t(language, "table.risk"): round(evaluation.glare_score, 1),
                t(language, "table.high_risk_time"): format_duration_minutes(
                    evaluation.high_risk_duration_s
                ),
                t(language, "table.high_risk_distance"): format_distance_km(
                    evaluation.high_risk_distance_m
                ),
                t(language, "table.peak_time"): peak_time,
                t(language, "table.approx_km"): peak_distance,
            }
        )
    return rows


def render_summary(
    recommended: RouteEvaluation,
    sun_position: SunPosition,
    trip_start_moment: datetime,
    language: str,
) -> None:
    peak_time, peak_distance = peak_risk_summary(
        recommended,
        trip_start_moment,
        language,
    )
    card_one, card_two, card_three, card_four = st.columns(4)
    card_one.metric(
        t(language, "metrics.distance"),
        format_distance_km(recommended.route.metrics.distance_m),
    )
    card_two.metric(
        t(language, "metrics.duration"),
        format_duration_minutes(recommended.route.metrics.duration_s),
    )
    card_three.metric(
        t(language, "metrics.high_risk_time"),
        format_duration_minutes(recommended.high_risk_duration_s),
    )
    card_four.metric(t(language, "metrics.peak_time"), peak_time)
    st.caption(
        t(
            language,
            "metrics.peak_point",
            peak_distance=peak_distance,
            azimuth=sun_position.azimuth_deg,
            elevation=sun_position.elevation_deg,
        )
    )
    _render_continuous_driving_notice(recommended.route.metrics.duration_s, language)


def render_comparison_table(result: AnalysisResult, language: str) -> None:
    recommended = result.ranked_routes[0]
    fastest = min(result.ranked_routes, key=lambda item: item.route.metrics.duration_s)
    route_column = t(language, "table.route")
    recommended_column = t(language, "table.recommended")
    fastest_column = t(language, "table.fastest")
    distance_column = t(language, "metrics.distance")
    duration_column = t(language, "metrics.duration")
    risk_column = t(language, "table.risk")
    high_risk_time_column = t(language, "table.high_risk_time")
    high_risk_distance_column = t(language, "table.high_risk_distance")
    peak_time_column = t(language, "table.peak_time")
    peak_distance_column = t(language, "table.approx_km")

    st.markdown('<div class="sunrouter-table-shell">', unsafe_allow_html=True)
    st.subheader(t(language, "analysis.comparison"))
    st.dataframe(
        comparison_rows(
            route_evaluations=result.ranked_routes,
            recommended_route_id=recommended.route.route_id,
            fastest_route_id=fastest.route.route_id,
            trip_start_moment=result.request.trip_moment,
            language=language,
        ),
        width="stretch",
        hide_index=True,
        column_config={
            route_column: st.column_config.TextColumn(route_column, width="small"),
            recommended_column: st.column_config.TextColumn(
                recommended_column,
                width="small",
            ),
            fastest_column: st.column_config.TextColumn(fastest_column, width="small"),
            distance_column: st.column_config.TextColumn(
                distance_column, width="small"
            ),
            duration_column: st.column_config.TextColumn(
                duration_column, width="small"
            ),
            risk_column: st.column_config.NumberColumn(risk_column, width="small"),
            high_risk_time_column: st.column_config.TextColumn(
                high_risk_time_column,
                width="medium",
            ),
            high_risk_distance_column: st.column_config.TextColumn(
                high_risk_distance_column,
                width="medium",
            ),
            peak_time_column: st.column_config.TextColumn(
                peak_time_column,
                width="small",
            ),
            peak_distance_column: st.column_config.TextColumn(
                peak_distance_column,
                width="medium",
            ),
        },
    )
    st.markdown("</div>", unsafe_allow_html=True)


def get_saved_analysis_result() -> AnalysisResult | None:
    result = st.session_state.get(ANALYSIS_RESULT_STATE_KEY)
    return result if isinstance(result, AnalysisResult) else None


def save_analysis_result(result: AnalysisResult) -> None:
    st.session_state[ANALYSIS_RESULT_STATE_KEY] = result


def get_saved_route_alternatives() -> RouteAlternativesResult | None:
    result = st.session_state.get(ROUTE_ALTERNATIVES_STATE_KEY)
    return result if isinstance(result, RouteAlternativesResult) else None


def save_route_alternatives(result: RouteAlternativesResult) -> None:
    st.session_state[ROUTE_ALTERNATIVES_STATE_KEY] = result
    fastest_id = fastest_route_id(result.routes)
    if fastest_id is not None:
        st.session_state[SELECTED_ROUTE_ID_STATE_KEY] = fastest_id
    st.session_state.pop(TIME_WINDOW_RESULT_STATE_KEY, None)
    st.session_state.pop(TIME_WINDOW_PARAMS_STATE_KEY, None)
    st.session_state.pop(DATE_RANGE_RESULT_STATE_KEY, None)
    st.session_state.pop(DATE_RANGE_PARAMS_STATE_KEY, None)
    st.session_state.pop(INSPECTED_CANDIDATE_KEY_STATE_KEY, None)
    st.session_state.pop(INSPECTED_RESULT_SIGNATURE_STATE_KEY, None)
    st.session_state.pop(DATE_RANGE_INSPECTED_CANDIDATE_KEY_STATE_KEY, None)
    st.session_state.pop(DATE_RANGE_INSPECTED_RESULT_SIGNATURE_STATE_KEY, None)
    st.session_state.pop(DATE_RANGE_FIXED_TIME_OFFSET_STATE_KEY, None)


def get_saved_time_window_result() -> RouteTimeWindowEvaluation | None:
    result = st.session_state.get(TIME_WINDOW_RESULT_STATE_KEY)
    return result if isinstance(result, RouteTimeWindowEvaluation) else None


def get_saved_time_window_params() -> TimeWindowEvaluationParams | None:
    params = st.session_state.get(TIME_WINDOW_PARAMS_STATE_KEY)
    return params if isinstance(params, TimeWindowEvaluationParams) else None


def get_saved_date_range_result() -> RouteDateRangeEvaluation | None:
    result = st.session_state.get(DATE_RANGE_RESULT_STATE_KEY)
    return result if isinstance(result, RouteDateRangeEvaluation) else None


def get_saved_date_range_params() -> DateRangeEvaluationParams | None:
    params = st.session_state.get(DATE_RANGE_PARAMS_STATE_KEY)
    return params if isinstance(params, DateRangeEvaluationParams) else None


def save_time_window_result(
    result: RouteTimeWindowEvaluation,
    params: TimeWindowEvaluationParams,
) -> None:
    st.session_state[TIME_WINDOW_RESULT_STATE_KEY] = result
    st.session_state[TIME_WINDOW_PARAMS_STATE_KEY] = params
    st.session_state.pop(INSPECTED_CANDIDATE_KEY_STATE_KEY, None)
    st.session_state.pop(INSPECTED_RESULT_SIGNATURE_STATE_KEY, None)


def save_date_range_result(
    result: RouteDateRangeEvaluation,
    params: DateRangeEvaluationParams,
) -> None:
    st.session_state[DATE_RANGE_RESULT_STATE_KEY] = result
    st.session_state[DATE_RANGE_PARAMS_STATE_KEY] = params
    st.session_state.pop(DATE_RANGE_INSPECTED_CANDIDATE_KEY_STATE_KEY, None)
    st.session_state.pop(DATE_RANGE_INSPECTED_RESULT_SIGNATURE_STATE_KEY, None)
    st.session_state.pop(DATE_RANGE_FIXED_TIME_OFFSET_STATE_KEY, None)


def clear_analysis_result() -> None:
    st.session_state.pop(ANALYSIS_RESULT_STATE_KEY, None)
    st.session_state.pop(ROUTE_ALTERNATIVES_STATE_KEY, None)
    st.session_state.pop(TIME_WINDOW_RESULT_STATE_KEY, None)
    st.session_state.pop(TIME_WINDOW_PARAMS_STATE_KEY, None)
    st.session_state.pop(DATE_RANGE_RESULT_STATE_KEY, None)
    st.session_state.pop(DATE_RANGE_PARAMS_STATE_KEY, None)
    st.session_state.pop(SELECTED_ROUTE_ID_STATE_KEY, None)
    st.session_state.pop(INSPECTED_CANDIDATE_KEY_STATE_KEY, None)
    st.session_state.pop(INSPECTED_RESULT_SIGNATURE_STATE_KEY, None)
    st.session_state.pop(DATE_RANGE_INSPECTED_CANDIDATE_KEY_STATE_KEY, None)
    st.session_state.pop(DATE_RANGE_INSPECTED_RESULT_SIGNATURE_STATE_KEY, None)


def _suggestion_key(suggestion: AddressSuggestion) -> tuple[str, float, float]:
    return (
        suggestion.label.casefold(),
        round(suggestion.coordinates.lat, 7),
        round(suggestion.coordinates.lon, 7),
    )


def remember_recent_suggestion(
    suggestion: AddressSuggestion, *, max_items: int = 8
) -> None:
    existing = st.session_state.get(RECENT_SUGGESTIONS_STATE_KEY, [])
    suggestions = [item for item in existing if isinstance(item, AddressSuggestion)]
    suggestion_key = _suggestion_key(suggestion)
    deduped = [item for item in suggestions if _suggestion_key(item) != suggestion_key]
    st.session_state[RECENT_SUGGESTIONS_STATE_KEY] = [suggestion, *deduped][:max_items]


def remember_recent_location(location: SelectedLocation) -> None:
    remember_recent_suggestion(
        AddressSuggestion(
            label=location.label,
            coordinates=location.coordinates,
        )
    )


def recent_suggestions_for_query(query: str, *, limit: int) -> list[AddressSuggestion]:
    clean_query = query.strip().casefold()
    existing = st.session_state.get(RECENT_SUGGESTIONS_STATE_KEY, [])
    suggestions = [item for item in existing if isinstance(item, AddressSuggestion)]
    if clean_query:
        suggestions = [
            item for item in suggestions if clean_query in item.label.casefold()
        ]
    return suggestions[:limit]


def merge_suggestions(
    local_suggestions: list[AddressSuggestion],
    remote_suggestions: list[AddressSuggestion],
    *,
    limit: int,
) -> list[AddressSuggestion]:
    merged: list[AddressSuggestion] = []
    seen: set[tuple[str, float, float]] = set()
    for suggestion in [*local_suggestions, *remote_suggestions]:
        key = _suggestion_key(suggestion)
        if key in seen:
            continue
        seen.add(key)
        merged.append(suggestion)
        if len(merged) >= limit:
            break
    return merged


def apply_picker_suggestion_selection(
    *,
    state_key: str,
    state: LocationPickerState,
    suggestion: AddressSuggestion,
) -> LocationPickerState:
    updated_state = apply_picker_suggestion_result(state, suggestion)
    st.session_state[state_key] = updated_state
    remember_recent_suggestion(suggestion)
    clear_analysis_result()
    return updated_state


def browser_timezone_from_streamlit() -> str | None:
    context = getattr(st, "context", None)
    timezone_name = getattr(context, "timezone", None)
    return timezone_name if isinstance(timezone_name, str) else None


def apply_automatic_timezone(
    *,
    origin_state: LocationPickerState | None,
    settings: Settings,
    browser_timezone: str | None,
    finder: CoordinateTimezoneFinder | None = None,
) -> ResolvedTimezone:
    resolved = resolve_automatic_timezone(
        origin=origin_state,
        browser_timezone=browser_timezone,
        configured_default_timezone=settings.default_timezone,
        finder=finder,
    )
    st.session_state[TIMEZONE_STATE_KEY] = resolved.name
    st.session_state[TIMEZONE_SOURCE_STATE_KEY] = resolved.source
    return resolved


def ensure_timezone_state(
    *,
    origin_state: LocationPickerState | None,
    settings: Settings,
    browser_timezone: str | None,
    finder: CoordinateTimezoneFinder | None = None,
) -> str:
    mode = st.session_state.get(TIMEZONE_MODE_STATE_KEY)
    timezone_name = st.session_state.get(TIMEZONE_STATE_KEY)
    if mode not in {TIMEZONE_MODE_AUTOMATIC, TIMEZONE_MODE_MANUAL}:
        mode = (
            TIMEZONE_MODE_MANUAL
            if is_valid_timezone_name(timezone_name)
            else TIMEZONE_MODE_AUTOMATIC
        )
        st.session_state[TIMEZONE_MODE_STATE_KEY] = mode

    if mode == TIMEZONE_MODE_MANUAL and is_valid_timezone_name(timezone_name):
        st.session_state[TIMEZONE_SOURCE_STATE_KEY] = "manual"
        return str(timezone_name)

    if mode == TIMEZONE_MODE_MANUAL:
        st.session_state[TIMEZONE_MODE_STATE_KEY] = TIMEZONE_MODE_AUTOMATIC

    return apply_automatic_timezone(
        origin_state=origin_state,
        settings=settings,
        browser_timezone=browser_timezone,
        finder=finder,
    ).name


def mark_timezone_manual() -> None:
    st.session_state[TIMEZONE_MODE_STATE_KEY] = TIMEZONE_MODE_MANUAL
    st.session_state[TIMEZONE_SOURCE_STATE_KEY] = "manual"


def restore_automatic_timezone(
    *,
    origin_state: LocationPickerState | None,
    settings: Settings,
    browser_timezone: str | None,
    finder: CoordinateTimezoneFinder | None = None,
) -> None:
    st.session_state[TIMEZONE_MODE_STATE_KEY] = TIMEZONE_MODE_AUTOMATIC
    apply_automatic_timezone(
        origin_state=origin_state,
        settings=settings,
        browser_timezone=browser_timezone,
        finder=finder,
    )


def apply_date_range_preset(*, preset: str, today: date) -> None:
    start_date, end_date = date_range_preset_dates(today, preset)
    st.session_state[DATE_RANGE_START_DATE_STATE_KEY] = start_date
    st.session_state[DATE_RANGE_END_DATE_STATE_KEY] = end_date


def swap_picker_states(
    *,
    origin_state: LocationPickerState,
    destination_state: LocationPickerState,
) -> tuple[LocationPickerState, LocationPickerState]:
    next_revision = max(origin_state.map_revision, destination_state.map_revision) + 1
    return (
        replace(destination_state, map_revision=next_revision),
        replace(origin_state, map_revision=next_revision),
    )


def current_picker_query_text(state: LocationPickerState, input_key: str) -> str:
    widget_value = st.session_state.get(f"{input_key}_{state.map_revision}")
    return widget_value if isinstance(widget_value, str) else state.query_text


def reverse_locations(
    *,
    origin_state: LocationPickerState,
    destination_state: LocationPickerState,
    settings: Settings,
    browser_timezone: str | None,
    finder: CoordinateTimezoneFinder | None = None,
) -> None:
    origin_state = replace(
        origin_state,
        query_text=current_picker_query_text(origin_state, "origin_query_input"),
    )
    destination_state = replace(
        destination_state,
        query_text=current_picker_query_text(
            destination_state,
            "destination_query_input",
        ),
    )
    new_origin_state, new_destination_state = swap_picker_states(
        origin_state=origin_state,
        destination_state=destination_state,
    )
    st.session_state[ORIGIN_PICKER_STATE_KEY] = new_origin_state
    st.session_state[DESTINATION_PICKER_STATE_KEY] = new_destination_state
    st.session_state[f"origin_query_input_{new_origin_state.map_revision}"] = (
        new_origin_state.query_text
    )
    st.session_state[
        f"destination_query_input_{new_destination_state.map_revision}"
    ] = new_destination_state.query_text
    clear_analysis_result()

    if st.session_state.get(TIMEZONE_MODE_STATE_KEY) != TIMEZONE_MODE_MANUAL:
        st.session_state[TIMEZONE_MODE_STATE_KEY] = TIMEZONE_MODE_AUTOMATIC
        apply_automatic_timezone(
            origin_state=new_origin_state,
            settings=settings,
            browser_timezone=browser_timezone,
            finder=finder,
        )


def ensure_picker_state(
    state_key: str,
    default_query: str,
    default_confirmed_location: SelectedLocation | None = None,
) -> LocationPickerState:
    state = st.session_state.get(state_key)
    if isinstance(state, LocationPickerState):
        return state

    if default_confirmed_location is None:
        state = create_picker_state(default_query, DEFAULT_MAP_CENTER)
    else:
        state = LocationPickerState(
            query_text=default_confirmed_location.label,
            provisional_result=None,
            map_center=default_confirmed_location.coordinates,
            confirmed_location=default_confirmed_location,
            map_revision=0,
        )
    st.session_state[state_key] = state
    return state


def default_picker_location(picker_kind: str) -> SelectedLocation:
    return (
        DEFAULT_ORIGIN_LOCATION
        if picker_kind == "origin"
        else DEFAULT_DESTINATION_LOCATION
    )


def extract_clicked_coordinates(map_data: object) -> Coordinates | None:
    if not isinstance(map_data, dict):
        return None
    last_clicked = map_data.get("last_clicked")
    if not isinstance(last_clicked, dict):
        return None

    lat = last_clicked.get("lat")
    lon = last_clicked.get("lng")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None

    return Coordinates(lat=float(lat), lon=float(lon))


def extract_selected_coordinates(
    *,
    map_data: object,
    state: LocationPickerState,
    picker_kind: str,
    language: str,
) -> Coordinates | None:
    clicked_coordinates = extract_clicked_coordinates(map_data)
    if clicked_coordinates is not None:
        return clicked_coordinates

    if not isinstance(map_data, dict):
        return None

    object_tooltip = map_data.get("last_object_clicked_tooltip")
    if not isinstance(object_tooltip, str):
        return None

    provisional_tooltip = t(language, f"map.{picker_kind}_provisional")
    if object_tooltip == provisional_tooltip and state.provisional_result is not None:
        return state.provisional_result.coordinates

    confirmed_tooltip = t(language, f"map.{picker_kind}_confirmed")
    if object_tooltip == confirmed_tooltip and state.confirmed_location is not None:
        return state.confirmed_location.coordinates

    return None


def build_analysis_result(
    request: AnalysisRequest,
    router: Router,
    settings: Settings,
    language: str,
) -> AnalysisResult:
    routes = router.get_routes(
        origin=request.origin.coordinates,
        destination=request.destination.coordinates,
        profile=settings.routing_profile,
    )
    if not routes:
        logger.warning(
            "Routing returned no routes for origin=%s destination=%s",
            request.origin.label,
            request.destination.label,
        )
        raise ValueError(t(language, "analysis.single_route"))

    from src.solar import get_sun_position

    sun_position = get_sun_position(request.trip_moment, request.origin.coordinates)
    ranked_routes = rank_routes(routes, request.trip_moment)
    explanation = explain_recommendation(
        ranked_routes[0],
        ranked_routes[1:],
        sun_position,
        language=language,
    )
    return AnalysisResult(
        request=request,
        sun_position=sun_position,
        ranked_routes=ranked_routes,
        explanation=explanation,
    )


def build_route_alternatives_result(
    request: AnalysisRequest,
    router: Router,
    settings: Settings,
    language: str,
) -> RouteAlternativesResult:
    routes = router.get_routes(
        origin=request.origin.coordinates,
        destination=request.destination.coordinates,
        profile=settings.routing_profile,
    )
    if not routes:
        logger.warning(
            "Routing returned no routes for origin=%s destination=%s",
            request.origin.label,
            request.destination.label,
        )
        raise ValueError(t(language, "analysis.no_routes"))

    return RouteAlternativesResult(
        origin=request.origin,
        destination=request.destination,
        routing_profile=settings.routing_profile,
        routes=routes,
    )


def render_information(language: str) -> None:
    with st.expander(t(language, "ui.info")):
        st.markdown(f"**{t(language, 'ui.what_is')}**")
        st.markdown(t(language, "ui.what_is_body"))
        st.markdown(f"**{t(language, 'ui.how_it_works')}**")
        st.markdown(t(language, "ui.how_it_works_body"))
        st.markdown(f"**{t(language, 'ui.risk_meaning')}**")
        st.markdown(t(language, "ui.risk_meaning_body"))
        st.markdown(f"**{t(language, 'ui.how_to_interpret')}**")
        st.markdown(t(language, "ui.how_to_interpret_body"))
        st.markdown(f"**{t(language, 'ui.limitations')}**")
        st.markdown(t(language, "ui.limitations_body"))


def picker_status_text(
    state: LocationPickerState,
    language: str,
) -> tuple[str, str]:
    confirmed = state.confirmed_location
    if confirmed is not None:
        if confirmed.label_source == "coordinates":
            return (
                "success",
                t(
                    language,
                    "picker.status.confirmed_coordinates",
                    label=confirmed.label,
                ),
            )
        return (
            "success",
            t(language, "picker.status.confirmed", label=confirmed.label),
        )
    if state.provisional_result is not None:
        return ("info", t(language, "picker.status.result_found"))
    return ("info", t(language, "picker.status.prompt"))


def resolve_picker_confirmation(
    *,
    state: LocationPickerState,
    query_text: str,
    clicked_coordinates: Coordinates,
    geocoder: Geocoder,
    picker_kind: str,
    language: str,
) -> tuple[LocationPickerState, str | None]:
    warning_message: str | None = None
    try:
        reverse_result = geocoder.reverse_geocode(clicked_coordinates)
    except ProviderError:
        logger.warning(
            "Reverse geocoding failed for %s picker at lat=%.5f lon=%.5f",
            picker_kind,
            clicked_coordinates.lat,
            clicked_coordinates.lon,
            exc_info=True,
        )
        reverse_result = None
        warning_message = t(language, "picker.reverse_geocode_warning")

    live_state = (
        state
        if query_text == state.query_text
        else replace(state, query_text=query_text)
    )
    updated_state = confirm_picker_location(
        live_state,
        clicked_coordinates,
        reverse_result,
    )
    return updated_state, warning_message


def resolve_picker_search(
    *,
    state: LocationPickerState,
    query_text: str,
    geocoder: Geocoder,
    picker_kind: str,
    language: str,
) -> tuple[LocationPickerState, str | None]:
    try:
        result = geocoder.geocode(query_text)
    except ProviderError:
        logger.warning(
            "Geocoding failed for %s picker with query=%s",
            picker_kind,
            query_text,
            exc_info=True,
        )
        return state, t(language, "picker.search_failed_warning")

    return apply_picker_search_result(state, query_text, result), None


def picker_suggestion_options(
    *,
    query: str,
    suggestion_provider: SuggestionProvider,
    settings: Settings,
    state_key: str,
    language: str,
) -> list[tuple[str, AddressSuggestion]]:
    local_suggestions = recent_suggestions_for_query(
        query,
        limit=settings.suggestion_max_results,
    )
    remote_suggestions: list[AddressSuggestion] = []
    if settings.suggestions_enabled and len(query.strip()) >= (
        settings.suggestion_min_query_length
    ):
        try:
            remote_suggestions = suggestion_provider.suggest(query)
        except ProviderError:
            logger.warning("Address suggestions failed for query=%s", query)
            st.session_state[f"{state_key}_suggestion_warning"] = t(
                language,
                "picker.suggestions_failed_warning",
            )

    return [
        (suggestion.label, suggestion)
        for suggestion in merge_suggestions(
            local_suggestions,
            remote_suggestions,
            limit=settings.suggestion_max_results,
        )
    ]


def render_picker_suggestions(
    *,
    picker_kind: str,
    state_key: str,
    state: LocationPickerState,
    settings: Settings,
    suggestion_provider: SuggestionProvider,
    language: str,
) -> LocationPickerState:
    if not settings.suggestions_enabled:
        return state
    if st_searchbox is None:
        st.caption(t(language, "picker.suggestions_unavailable"))
        return state

    def search_options(search_term: str) -> list[tuple[str, AddressSuggestion]]:
        return picker_suggestion_options(
            query=search_term,
            suggestion_provider=suggestion_provider,
            settings=settings,
            state_key=state_key,
            language=language,
        )

    selected = st_searchbox(
        search_options,
        placeholder=t(language, "picker.suggestions_placeholder"),
        key=f"{picker_kind}_suggestions_{state.map_revision}",
        debounce=settings.suggestion_debounce_ms,
        clear_on_submit=False,
        edit_after_submit="option",
    )
    if isinstance(selected, AddressSuggestion):
        already_selected = (
            state.provisional_result is not None
            and state.provisional_result.label == selected.label
            and state.provisional_result.coordinates == selected.coordinates
            and state.provisional_result.provider_id == selected.provider_id
        )
        if not already_selected:
            updated_state = apply_picker_suggestion_selection(
                state_key=state_key,
                state=state,
                suggestion=selected,
            )
            st.rerun()
            return updated_state

    return state


def render_picker(
    *,
    title: str,
    picker_kind: str,
    state_key: str,
    input_key: str,
    geocoder: Geocoder,
    suggestion_provider: SuggestionProvider,
    settings: Settings,
    language: str,
) -> LocationPickerState:
    state = ensure_picker_state(
        state_key,
        DEFAULT_ORIGIN_QUERY if picker_kind == "origin" else DEFAULT_DESTINATION_QUERY,
        default_picker_location(picker_kind),
    )

    widget_key = f"{input_key}_{state.map_revision}"
    if widget_key not in st.session_state:
        st.session_state[widget_key] = state.query_text

    st.subheader(title)
    state = render_picker_suggestions(
        picker_kind=picker_kind,
        state_key=state_key,
        state=state,
        settings=settings,
        suggestion_provider=suggestion_provider,
        language=language,
    )
    with st.form(f"{picker_kind}_search_form"):
        query_text = st.text_input(title, key=widget_key, label_visibility="collapsed")
        submitted = st.form_submit_button(t(language, "picker.search"), width="stretch")
    if submitted:
        if not query_text.strip():
            st.warning(t(language, "picker.search_empty_warning"))
        else:
            logger.info("Searching %s picker with query=%s", picker_kind, query_text)
            updated_state, error_message = resolve_picker_search(
                state=state,
                query_text=query_text,
                geocoder=geocoder,
                picker_kind=picker_kind,
                language=language,
            )
            st.session_state[state_key] = updated_state
            if error_message is not None:
                st.session_state[f"{state_key}_error"] = error_message
            clear_analysis_result()
            st.rerun()

    state = ensure_picker_state(
        state_key,
        DEFAULT_ORIGIN_QUERY if picker_kind == "origin" else DEFAULT_DESTINATION_QUERY,
        default_picker_location(picker_kind),
    )
    status_kind, status_message = picker_status_text(state, language)
    getattr(st, status_kind)(status_message)
    st.caption(t(language, "picker.caption"))

    picker_map = get_picker_map(
        map_center=state.map_center,
        provisional_result=state.provisional_result,
        confirmed_location=state.confirmed_location,
        picker_kind=picker_kind,
        language=language,
    )
    map_data = st_folium(
        picker_map,
        key=f"{picker_kind}_picker_map_{state.map_revision}",
        height=320,
        use_container_width=True,
        returned_objects=["last_clicked", "last_object_clicked_tooltip"],
    )
    clicked_coordinates = extract_selected_coordinates(
        map_data=map_data,
        state=state,
        picker_kind=picker_kind,
        language=language,
    )
    if clicked_coordinates is not None:
        confirmed = state.confirmed_location
        if confirmed is None or confirmed.coordinates != clicked_coordinates:
            logger.info(
                "Confirmed %s picker at lat=%.5f lon=%.5f",
                picker_kind,
                clicked_coordinates.lat,
                clicked_coordinates.lon,
            )
            updated_state, warning_message = resolve_picker_confirmation(
                state=state,
                query_text=query_text,
                clicked_coordinates=clicked_coordinates,
                geocoder=geocoder,
                picker_kind=picker_kind,
                language=language,
            )
            st.session_state[state_key] = updated_state
            if updated_state.confirmed_location is not None:
                remember_recent_location(updated_state.confirmed_location)
            if warning_message is not None:
                st.session_state[f"{state_key}_warning"] = warning_message
            clear_analysis_result()
            st.rerun()

    warning_state_key = f"{state_key}_warning"
    warning_message = st.session_state.pop(warning_state_key, None)
    if isinstance(warning_message, str):
        st.warning(warning_message)
    suggestion_warning_state_key = f"{state_key}_suggestion_warning"
    suggestion_warning_message = st.session_state.pop(
        suggestion_warning_state_key,
        None,
    )
    if isinstance(suggestion_warning_message, str):
        st.info(suggestion_warning_message)
    error_state_key = f"{state_key}_error"
    error_message = st.session_state.pop(error_state_key, None)
    if isinstance(error_message, str):
        st.error(error_message)

    return ensure_picker_state(
        state_key,
        DEFAULT_ORIGIN_QUERY if picker_kind == "origin" else DEFAULT_DESTINATION_QUERY,
        default_picker_location(picker_kind),
    )


def render_analysis(result: AnalysisResult, settings: Settings, language: str) -> None:
    recommended = result.ranked_routes[0]
    fastest = min(result.ranked_routes, key=lambda item: item.route.metrics.duration_s)
    has_alternatives = len(result.ranked_routes) > 1
    peak_time, peak_distance = peak_risk_summary(
        recommended,
        result.request.trip_moment,
        language,
    )

    st.subheader(t(language, "analysis.routes_proposed"))
    if has_alternatives:
        st.info(
            t(
                language,
                "analysis.routes_found",
                count=len(result.ranked_routes),
            )
        )
    else:
        st.info(t(language, "analysis.single_route"))

    route_map = get_route_map(
        origin=result.request.origin.coordinates,
        destination=result.request.destination.coordinates,
        evaluations=tuple(result.ranked_routes),
        recommended_route_id=recommended.route.route_id,
        language=language,
        trip_start_moment=result.request.trip_moment,
    )
    st_folium(
        route_map,
        use_container_width=True,
        height=460,
        key="route_map",
        returned_objects=[],
    )
    st.caption(t(language, "analysis.map_explanation"))

    st.subheader(
        t(language, "analysis.recommended_summary")
        if has_alternatives
        else t(language, "analysis.single_summary")
    )
    recommended_name = route_display_name(recommended, 1, language)
    st.markdown(
        (
            f'<div class="sunrouter-note"><strong>{recommended_name}</strong> '
            f"{t(language, 'analysis.recommendation_note', route_name=recommended_name)}</div>"
        ),
        unsafe_allow_html=True,
    )
    render_summary(
        recommended, result.sun_position, result.request.trip_moment, language
    )
    st.caption(
        t(
            language,
            "analysis.peak_caption",
            peak_time=peak_time,
            peak_distance=peak_distance,
        )
    )
    st.write(result.explanation)
    if has_alternatives and recommended.route.route_id != fastest.route.route_id:
        saved_minutes = (
            abs(recommended.route.metrics.duration_s - fastest.route.metrics.duration_s)
            / 60.0
        )
        st.info(t(language, "analysis.fastest_info", minutes=saved_minutes))

    with st.expander(t(language, "analysis.debug")):
        st.json(
            {
                "datetime": result.request.trip_moment.isoformat(),
                "timezone": result.request.timezone_name,
                "origin": result.request.origin.label,
                "destination": result.request.destination.label,
                "sun": {
                    "azimuth_deg": round(result.sun_position.azimuth_deg, 3),
                    "elevation_deg": round(result.sun_position.elevation_deg, 3),
                },
                "providers": {
                    "geocoder": settings.geocoder_base_url,
                    "reverse_geocoder": settings.reverse_geocoder_base_url,
                    "router": settings.router_base_url,
                    "profile": settings.routing_profile,
                },
                "route_scores": [
                    {
                        "route_id": item.route.route_id,
                        "distance_m": round(item.route.metrics.distance_m, 1),
                        "duration_s": round(item.route.metrics.duration_s, 1),
                        "glare_score": item.glare_score,
                        "aligned_distance_m": item.aligned_distance_m,
                        "high_risk_duration_s": item.high_risk_duration_s,
                        "high_risk_distance_m": item.high_risk_distance_m,
                        "peak_risk_time_offset_min": item.peak_risk_time_offset_min,
                        "peak_risk_distance_m": item.peak_risk_distance_m,
                        "peak_glare_score": item.peak_glare_score,
                        "peak_glare_category": item.peak_glare_category,
                        "peak_glare_coordinates": None
                        if item.peak_glare_coordinates is None
                        else {
                            "lat": item.peak_glare_coordinates.lat,
                            "lon": item.peak_glare_coordinates.lon,
                        },
                        "any_high_risk_segments": item.any_high_risk_segments,
                        "longest_high_glare_stretch": None
                        if item.longest_high_glare_stretch is None
                        else {
                            "duration_s": item.longest_high_glare_stretch.duration_s,
                            "distance_m": item.longest_high_glare_stretch.distance_m,
                            "start_offset_s": (
                                item.longest_high_glare_stretch.start_offset_s
                            ),
                            "end_offset_s": (
                                item.longest_high_glare_stretch.end_offset_s
                            ),
                            "max_glare_score": (
                                item.longest_high_glare_stretch.max_glare_score
                            ),
                        },
                    }
                    for item in result.ranked_routes
                ],
            }
        )


def route_alternatives_match_request(
    result: RouteAlternativesResult,
    request: AnalysisRequest | None,
    settings: Settings,
) -> bool:
    if request is None:
        return False
    return (
        result.origin == request.origin
        and result.destination == request.destination
        and result.routing_profile == settings.routing_profile
    )


def date_range_heatmap_spec(
    evaluation: RouteDateRangeEvaluation,
    *,
    language: str,
) -> dict[str, object]:
    rows = date_range_heatmap_rows(evaluation)
    best_rows = date_range_best_time_overlay_rows(evaluation)
    dst_rows = date_range_dst_annotation_rows(evaluation)
    return {
        "datasets": {
            "heatmap": rows,
            "best_times": best_rows,
            "dst_transitions": dst_rows,
        },
        "height": 380,
        "layer": [
            {
                "data": {"name": "heatmap"},
                "mark": {"type": "rect"},
                "encoding": {
                    "x": {
                        "field": "Date start",
                        "type": "temporal",
                        "title": "Date",
                    },
                    "x2": {"field": "Date end"},
                    "y": {
                        "field": "Requested time start minutes",
                        "type": "quantitative",
                        "title": date_range_heatmap_axis_label(
                            evaluation,
                            language,
                        ),
                        "axis": {
                            "labelExpr": (
                                "timeFormat(datetime(2000,0,1,"
                                "floor(datum.value/60),datum.value%60),'%H:%M')"
                            )
                        },
                    },
                    "y2": {"field": "Requested time end minutes"},
                    "color": {
                        "field": "Glare score",
                        "type": "quantitative",
                        "scale": {
                            "domain": [0, 100],
                            "range": [
                                "#f7fbff",
                                "#c7e9b4",
                                "#fee391",
                                "#fdae61",
                                "#d73027",
                            ],
                        },
                    },
                    "tooltip": [
                        {"field": "Date", "type": "nominal"},
                        {"field": "Requested time", "type": "nominal"},
                        {"field": "Calculated departure", "type": "nominal"},
                        {"field": "Calculated arrival", "type": "nominal"},
                        {"field": "Glare score", "type": "quantitative"},
                        {"field": "High-risk duration", "type": "nominal"},
                        {"field": "Peak glare", "type": "nominal"},
                        {"field": "UTC offset", "type": "nominal"},
                        {"field": "Evaluation source", "type": "nominal"},
                    ],
                },
            },
            {
                "data": {"name": "best_times"},
                "mark": {
                    "type": "line",
                    "point": True,
                    "strokeWidth": 2,
                    "color": "#2563eb",
                },
                "encoding": {
                    "x": {"field": "Sampled date", "type": "temporal"},
                    "y": {
                        "field": "Representative time minutes",
                        "type": "quantitative",
                    },
                    "tooltip": [
                        {"field": "Representative lowest-glare time"},
                        {"field": "Minimum glare score", "type": "quantitative"},
                        {"field": "Interval average score", "type": "quantitative"},
                    ],
                },
            },
            {
                "data": {"name": "dst_transitions"},
                "mark": {
                    "type": "rule",
                    "color": "#64748b",
                    "strokeDash": [4, 4],
                    "opacity": 0.7,
                },
                "encoding": {
                    "x": {"field": "Transition date", "type": "temporal"},
                    "tooltip": [{"field": "Label", "type": "nominal"}],
                },
            },
        ],
        "config": {"view": {"stroke": None}},
    }


def date_range_fixed_time_spec(
    evaluation: RouteDateRangeEvaluation,
    *,
    selected_time_offset_s: int,
) -> dict[str, object]:
    rows = date_range_fixed_time_chart_rows(evaluation, selected_time_offset_s)
    dst_rows = date_range_dst_annotation_rows(evaluation)
    return {
        "datasets": {
            "curve": rows,
            "dst_transitions": dst_rows,
        },
        "height": 260,
        "layer": [
            {
                "data": {"name": "curve"},
                "mark": {
                    "type": "line",
                    "point": True,
                    "strokeWidth": 2,
                    "color": "#0f766e",
                },
                "encoding": {
                    "x": {
                        "field": "Sampled date",
                        "type": "temporal",
                        "title": "Date",
                    },
                    "y": {
                        "field": "Glare score",
                        "type": "quantitative",
                        "title": "Glare score",
                        "scale": {"domain": [0, 100]},
                    },
                    "detail": {"field": "Series"},
                    "tooltip": [
                        {"field": "Date", "type": "nominal"},
                        {"field": "Requested time", "type": "nominal"},
                        {"field": "Calculated departure", "type": "nominal"},
                        {"field": "Calculated arrival", "type": "nominal"},
                        {"field": "Glare score", "type": "quantitative"},
                        {"field": "High-risk duration", "type": "nominal"},
                        {"field": "Peak glare", "type": "nominal"},
                        {"field": "UTC offset", "type": "nominal"},
                        {"field": "Evaluation source", "type": "nominal"},
                    ],
                },
            },
            {
                "data": {"name": "dst_transitions"},
                "mark": {
                    "type": "rule",
                    "color": "#64748b",
                    "strokeDash": [4, 4],
                    "opacity": 0.7,
                },
                "encoding": {
                    "x": {"field": "Transition date", "type": "temporal"},
                    "tooltip": [{"field": "Label", "type": "nominal"}],
                },
            },
        ],
        "config": {"view": {"stroke": None}},
    }


def render_time_window_result(
    *,
    route_result: RouteAlternativesResult,
    evaluation: RouteTimeWindowEvaluation,
    params: TimeWindowEvaluationParams,
    language: str,
) -> None:
    recommended = evaluation.recommended_candidate
    selected_route = recommended.route_evaluation.route
    title_key = (
        "time_window.result_title_departure"
        if evaluation.search_mode == "departure"
        else "time_window.result_title_arrival"
    )

    st.subheader(t(language, title_key))
    st.caption(t(language, "time_window.best_day_caption"))
    st.caption(
        t(
            language,
            "time_window.estimate_caption",
            timezone=params.timezone_name,
            increment=int(evaluation.increment.total_seconds() / 60),
        )
    )
    metric_one, metric_two, metric_three, metric_four, metric_five = st.columns(5)
    metric_one.metric(
        t(language, "time_window.recommended_departure"),
        _format_trip_endpoint(
            recommended.departure_time,
            recommended.departure_time,
            recommended.arrival_time,
        ),
    )
    metric_two.metric(
        t(language, "time_window.expected_arrival"),
        _format_trip_endpoint(
            recommended.arrival_time,
            recommended.departure_time,
            recommended.arrival_time,
        ),
    )
    metric_three.metric(
        t(language, "time_window.overall_glare"),
        f"{recommended.glare_score:.1f}",
    )
    metric_four.metric(
        t(language, "time_window.high_risk_minutes"),
        format_duration_minutes(recommended.high_risk_duration_s),
    )
    metric_five.metric(
        t(language, "time_window.trip_duration"),
        format_duration_minutes(selected_route.metrics.duration_s),
    )
    _render_continuous_driving_notice(selected_route.metrics.duration_s, language)

    st.markdown(
        '<div class="sunrouter-table-shell">',
        unsafe_allow_html=True,
    )
    st.subheader(t(language, "time_window.glare_chart"))
    st.line_chart(glare_chart_rows(evaluation), x="Time", y="Glare score")
    st.subheader(t(language, "time_window.candidate_results"))
    st.dataframe(
        candidate_result_rows(evaluation, language),
        width="stretch",
        hide_index=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

    candidate_options = [
        candidate_key(candidate) for candidate in evaluation.candidates
    ]
    recommended_key = candidate_key(recommended)
    signature = time_window_result_signature(params)
    if st.session_state.get(INSPECTED_RESULT_SIGNATURE_STATE_KEY) != signature:
        st.session_state[INSPECTED_RESULT_SIGNATURE_STATE_KEY] = signature
        st.session_state[INSPECTED_CANDIDATE_KEY_STATE_KEY] = recommended_key

    selected_candidate_key = st.selectbox(
        t(language, "time_window.inspect_candidate"),
        options=candidate_options,
        format_func=lambda value: candidate_choice_label(
            find_candidate_by_key(evaluation, value),
            evaluation.search_mode,
            is_recommended=value == recommended_key,
        ),
        key=INSPECTED_CANDIDATE_KEY_STATE_KEY,
    )
    inspected_candidate = find_candidate_by_key(evaluation, selected_candidate_key)
    peak_time, peak_distance = peak_risk_summary(
        inspected_candidate.route_evaluation,
        inspected_candidate.departure_time,
        language,
    )
    st.caption(
        t(
            language,
            "time_window.inspect_caption",
            departure=_format_trip_endpoint(
                inspected_candidate.departure_time,
                inspected_candidate.departure_time,
                inspected_candidate.arrival_time,
            ),
            arrival=_format_trip_endpoint(
                inspected_candidate.arrival_time,
                inspected_candidate.departure_time,
                inspected_candidate.arrival_time,
            ),
            peak_time=peak_time,
            peak_distance=peak_distance,
        )
    )

    route_map = get_route_map(
        origin=route_result.origin.coordinates,
        destination=route_result.destination.coordinates,
        evaluations=(inspected_candidate.route_evaluation,),
        recommended_route_id=selected_route.route_id,
        language=language,
        trip_start_moment=inspected_candidate.departure_time,
    )
    st_folium(
        route_map,
        use_container_width=True,
        height=420,
        key=f"inspected_route_map_{signature}_{selected_candidate_key}",
        returned_objects=[],
    )
    st.caption(t(language, "analysis.map_explanation"))


def render_date_range_result(
    *,
    route_result: RouteAlternativesResult,
    evaluation: RouteDateRangeEvaluation,
    params: DateRangeEvaluationParams,
    language: str,
) -> None:
    recommended = evaluation.recommended_candidate
    selected_route = recommended.route_evaluation.route
    result_label_key = (
        "date_range.exact_label" if evaluation.exact else "date_range.adaptive_label"
    )

    st.subheader(t(language, "date_range.result_title"))
    st.caption(t(language, "date_range.best_trip_caption"))
    st.info(
        t(
            language,
            result_label_key,
            candidates=evaluation.unique_evaluations,
            date_resolution=evaluation.final_date_resolution_days,
            time_resolution=int(evaluation.final_time_resolution.total_seconds() / 60),
            budget=evaluation.request.evaluation_budget,
            budget_outcome=t(
                language,
                f"date_range.budget_{evaluation.budget_outcome}",
            ),
        )
    )
    if not evaluation.exact:
        st.caption(t(language, "date_range.adaptive_explanation"))

    metric_one, metric_two, metric_three, metric_four = st.columns(4)
    metric_one.metric(
        t(language, "date_range.recommended_date"),
        recommended.requested_time.strftime("%Y-%m-%d"),
    )
    metric_two.metric(
        t(language, "time_window.recommended_departure"),
        _format_trip_endpoint(
            recommended.departure_time,
            recommended.departure_time,
            recommended.arrival_time,
        ),
    )
    metric_three.metric(
        t(language, "time_window.expected_arrival"),
        _format_trip_endpoint(
            recommended.arrival_time,
            recommended.departure_time,
            recommended.arrival_time,
        ),
    )
    metric_four.metric(
        t(language, "time_window.overall_glare"),
        f"{recommended.glare_score:.1f}",
    )

    detail_one, detail_two, detail_three, detail_four = st.columns(4)
    detail_one.metric(
        t(language, "time_window.high_risk_minutes"),
        format_duration_minutes(recommended.high_risk_duration_s),
    )
    detail_two.metric(
        t(language, "time_window.trip_duration"),
        format_duration_minutes(selected_route.metrics.duration_s),
    )
    _render_continuous_driving_notice(selected_route.metrics.duration_s, language)
    route_index = route_result.routes.index(selected_route) + 1
    detail_three.metric(
        t(language, "date_range.route_used"),
        time_window_route_display_name(selected_route, route_index, language),
    )
    detail_four.metric(t(language, "plan.timezone"), params.timezone_name)

    signature = date_range_result_signature(params)

    st.markdown(
        '<div class="sunrouter-table-shell">',
        unsafe_allow_html=True,
    )
    st.subheader(t(language, "date_range.alternatives"))
    st.dataframe(
        date_range_top_candidate_rows(evaluation, language),
        width="stretch",
        hide_index=True,
    )
    grid = evaluation.visualization_grid
    rendering_started_at = perf_counter()
    if grid is not None and grid.cells:
        st.subheader(date_range_heatmap_title(evaluation, language))
        st.vega_lite_chart(
            date_range_heatmap_spec(evaluation, language=language),
            width="stretch",
        )
        st.caption(t(language, "date_range.heatmap_explanation"))
        st.caption(t(language, "date_range.best_time_overlay_caption"))
        st.caption(date_range_visualization_caption(evaluation, language))

        time_offsets = date_range_visualization_time_offsets(evaluation)
        default_time_offset = date_range_default_fixed_time_offset(evaluation)
        if default_time_offset not in time_offsets and time_offsets:
            default_time_offset = time_offsets[0]
        if (
            st.session_state.get(DATE_RANGE_INSPECTED_RESULT_SIGNATURE_STATE_KEY)
            != signature
        ):
            st.session_state[DATE_RANGE_FIXED_TIME_OFFSET_STATE_KEY] = (
                default_time_offset
            )
        selected_time_offset = st.selectbox(
            t(language, "date_range.fixed_time_select"),
            options=time_offsets,
            format_func=time_offset_label,
            key=DATE_RANGE_FIXED_TIME_OFFSET_STATE_KEY,
        )
        st.subheader(
            date_range_fixed_time_title(
                evaluation,
                selected_time_offset,
                language,
            )
        )
        st.vega_lite_chart(
            date_range_fixed_time_spec(
                evaluation,
                selected_time_offset_s=selected_time_offset,
            ),
            width="stretch",
        )
        st.caption(t(language, "date_range.fixed_time_caption"))
    else:
        st.info(t(language, "date_range.visualization_empty"))

    dst_caption = date_range_dst_transition_caption(evaluation, language)
    if dst_caption is not None:
        st.caption(dst_caption)
    rendering_time_s = perf_counter() - rendering_started_at
    if grid is not None:
        st.caption(
            date_range_visualization_performance_caption(
                evaluation,
                language,
                rendering_time_s=rendering_time_s,
            )
        )
    st.markdown("</div>", unsafe_allow_html=True)

    candidates = date_range_candidate_options(evaluation)
    candidate_options = [candidate_key(candidate) for candidate in candidates]
    recommended_key = candidate_key(recommended)
    ranks = {
        candidate_key(candidate): rank
        for rank, candidate in enumerate(candidates, start=1)
    }
    if (
        st.session_state.get(DATE_RANGE_INSPECTED_RESULT_SIGNATURE_STATE_KEY)
        != signature
    ):
        st.session_state[DATE_RANGE_INSPECTED_RESULT_SIGNATURE_STATE_KEY] = signature
        st.session_state[DATE_RANGE_INSPECTED_CANDIDATE_KEY_STATE_KEY] = recommended_key

    selected_candidate_key = st.selectbox(
        t(language, "date_range.inspect_candidate"),
        options=candidate_options,
        format_func=lambda value: date_range_candidate_choice_label(
            find_date_range_candidate_by_key(evaluation, value),
            evaluation.request.search_mode,
            rank=ranks[value],
            is_recommended=value == recommended_key,
        ),
        key=DATE_RANGE_INSPECTED_CANDIDATE_KEY_STATE_KEY,
    )
    inspected_candidate = find_date_range_candidate_by_key(
        evaluation,
        selected_candidate_key,
    )
    peak_time, peak_distance = peak_risk_summary(
        inspected_candidate.route_evaluation,
        inspected_candidate.departure_time,
        language,
    )
    st.caption(
        t(
            language,
            "time_window.inspect_caption",
            departure=format_datetime_with_zone(inspected_candidate.departure_time),
            arrival=format_datetime_with_zone(inspected_candidate.arrival_time),
            peak_time=peak_time,
            peak_distance=peak_distance,
        )
    )

    route_map = get_route_map(
        origin=route_result.origin.coordinates,
        destination=route_result.destination.coordinates,
        evaluations=(inspected_candidate.route_evaluation,),
        recommended_route_id=selected_route.route_id,
        language=language,
        trip_start_moment=inspected_candidate.departure_time,
    )
    st_folium(
        route_map,
        use_container_width=True,
        height=420,
        key=f"date_range_route_map_{signature}_{selected_candidate_key}",
        returned_objects=[],
    )
    st.caption(t(language, "analysis.map_explanation"))

    with st.expander(t(language, "date_range.diagnostics")):
        st.subheader(t(language, "date_range.evaluated_candidates_chart"))
        st.scatter_chart(
            date_range_evaluated_candidate_chart_rows(evaluation),
            x="Requested datetime",
            y="Glare score",
            color="Candidate marker",
            size="Marker size",
        )
        st.caption(date_range_evaluated_candidates_caption(language))

        st.subheader(date_range_overview_title(evaluation))
        st.scatter_chart(
            date_range_overview_chart_rows(evaluation),
            x="Sampled date",
            y="Best sampled glare score",
            size="Candidates sampled on date",
        )
        st.caption(date_range_overview_caption(evaluation, language))

        st.dataframe(
            date_range_candidate_sample_rows(evaluation, language),
            width="stretch",
            hide_index=True,
        )
        large_change_rows = date_range_large_change_rows(evaluation)
        if large_change_rows:
            st.subheader(t(language, "date_range.large_changes"))
            st.dataframe(
                large_change_rows,
                width="stretch",
                hide_index=True,
            )
        st.json(
            {
                "strategy": evaluation.search_strategy,
                "unique_evaluations": evaluation.unique_evaluations,
                "candidate_count_at_final_resolution": (
                    evaluation.diagnostics.candidate_count_at_final_resolution
                ),
                "final_date_resolution_days": evaluation.final_date_resolution_days,
                "final_time_resolution_minutes": int(
                    evaluation.final_time_resolution.total_seconds() / 60
                ),
                "budget_outcome": evaluation.budget_outcome,
                "refinement_rounds": evaluation.diagnostics.refinement_rounds,
                "retained_basin_count": evaluation.diagnostics.retained_basin_count,
                "ambiguous_wall_times": evaluation.diagnostics.ambiguous_wall_times,
                "nonexistent_wall_times_adjusted": (
                    evaluation.diagnostics.nonexistent_wall_times_adjusted
                ),
                "visualization_grid": None
                if evaluation.visualization_grid is None
                else date_range_grid_debug_summary(evaluation.visualization_grid),
            }
        )


def render_date_range_planner(
    *,
    selected_route: Route,
    route_result: RouteAlternativesResult,
    settings: Settings,
    browser_timezone: str | None,
    language: str,
    today: date,
) -> None:
    st.subheader(t(language, "date_range.controls_title"))
    st.caption(t(language, "date_range.controls_caption"))

    preset_columns = st.columns(3)
    preset_specs = [
        ("next_7_days", "date_range.preset_next_7"),
        ("next_30_days", "date_range.preset_next_30"),
        ("this_summer", "date_range.preset_summer"),
    ]
    for column, (preset, label_key) in zip(preset_columns, preset_specs, strict=True):
        with column:
            st.button(
                t(language, label_key),
                key=f"date_range_preset_{preset}",
                width="stretch",
                on_click=apply_date_range_preset,
                kwargs={"preset": preset, "today": today},
            )

    controls_row_one = st.columns([1, 1, 1.15])
    with controls_row_one[0]:
        start_date = st.date_input(
            t(language, "date_range.start_date"),
            key=DATE_RANGE_START_DATE_STATE_KEY,
        )
    with controls_row_one[1]:
        end_date = st.date_input(
            t(language, "date_range.end_date"),
            key=DATE_RANGE_END_DATE_STATE_KEY,
        )
    with controls_row_one[2]:
        search_mode_value = st.radio(
            t(language, "time_window.mode"),
            options=["departure", "arrival"],
            format_func=lambda value: t(language, f"time_window.mode_{value}"),
            key=DATE_RANGE_MODE_STATE_KEY,
            horizontal=True,
        )
        search_mode = cast(RouteTimeSearchMode, search_mode_value)

    controls_row_two = st.columns([1, 1, 1.3])
    with controls_row_two[0]:
        earliest_time = st.time_input(
            t(language, "date_range.earliest_daily_time"),
            key=DATE_RANGE_EARLIEST_TIME_STATE_KEY,
        )
    with controls_row_two[1]:
        latest_time = st.time_input(
            t(language, "date_range.latest_daily_time"),
            key=DATE_RANGE_LATEST_TIME_STATE_KEY,
        )
    with controls_row_two[2]:
        timezone_name = st.selectbox(
            t(language, "plan.timezone"),
            options=supported_timezones(),
            key=TIMEZONE_STATE_KEY,
            on_change=mark_timezone_manual,
        )
        timezone_mode = st.session_state.get(TIMEZONE_MODE_STATE_KEY)
        if timezone_mode == TIMEZONE_MODE_MANUAL:
            st.button(
                t(language, "plan.use_origin_timezone"),
                key="date_range_use_origin_timezone_button",
                width="stretch",
                on_click=restore_automatic_timezone,
                kwargs={
                    "origin_state": LocationPickerState(
                        query_text=route_result.origin.label,
                        provisional_result=None,
                        map_center=route_result.origin.coordinates,
                        confirmed_location=route_result.origin,
                        map_revision=0,
                    ),
                    "settings": settings,
                    "browser_timezone": browser_timezone,
                },
            )
            st.caption(t(language, "plan.timezone_manual_caption"))
        else:
            source_key = st.session_state.get(TIMEZONE_SOURCE_STATE_KEY, "default")
            st.caption(t(language, f"plan.timezone_auto_{source_key}"))
        st.caption(t(language, "plan.timezone_origin_mvp"))

    evaluation_error: str | None = None
    submitted = st.button(
        t(language, "date_range.evaluate"),
        type="primary",
        width="stretch",
    )
    if submitted:
        try:
            params = DateRangeEvaluationParams(
                route_id=selected_route.route_id,
                search_mode=search_mode,
                start_date=start_date,
                end_date=end_date,
                daily_earliest_time=earliest_time,
                daily_latest_time=latest_time,
                timezone_name=timezone_name,
            )
            logger.info(
                "Evaluating date range route=%s mode=%s start=%s end=%s "
                "earliest=%s latest=%s timezone=%s",
                selected_route.route_id,
                search_mode,
                start_date.isoformat(),
                end_date.isoformat(),
                earliest_time.isoformat(),
                latest_time.isoformat(),
                timezone_name,
            )
            with st.spinner(t(language, "date_range.evaluating")):
                save_date_range_result(
                    evaluate_route_date_range(
                        selected_route,
                        start_date,
                        end_date,
                        earliest_time,
                        latest_time,
                        search_mode=search_mode,
                        timezone_name=timezone_name,
                    ),
                    params,
                )
        except ValueError as exc:
            logger.info("Invalid date-range controls: %s", exc)
            evaluation_error = str(exc)
        except Exception as exc:
            logger.exception("Date-range evaluation failed")
            evaluation_error = str(exc)

    if evaluation_error is not None:
        st.error(evaluation_error)

    saved_evaluation = get_saved_date_range_result()
    saved_params = get_saved_date_range_params()
    if saved_evaluation is None or saved_params is None:
        st.info(t(language, "date_range.empty_result"))
        return
    if not date_range_params_match_current(
        saved_params,
        route_id=selected_route.route_id,
        search_mode=search_mode,
        start_date=start_date,
        end_date=end_date,
        daily_earliest_time=earliest_time,
        daily_latest_time=latest_time,
        timezone_name=timezone_name,
    ):
        st.info(t(language, "date_range.needs_refresh"))
        return

    render_date_range_result(
        route_result=route_result,
        evaluation=saved_evaluation,
        params=saved_params,
        language=language,
    )


def render_time_window_planner(
    *,
    route_result: RouteAlternativesResult,
    settings: Settings,
    browser_timezone: str | None,
    language: str,
) -> None:
    has_alternatives = len(route_result.routes) > 1
    st.subheader(t(language, "analysis.routes_proposed"))
    if has_alternatives:
        st.info(
            t(
                language,
                "analysis.routes_found",
                count=len(route_result.routes),
            )
        )
    else:
        st.info(t(language, "analysis.single_route"))

    route_labels = route_choice_labels(route_result.routes, language)
    route_ids = list(route_labels)
    selected_route_id = st.session_state.get(SELECTED_ROUTE_ID_STATE_KEY)
    if find_route_by_id(route_result.routes, selected_route_id) is None:
        default_route_id = fastest_route_id(route_result.routes)
        if default_route_id is not None:
            st.session_state[SELECTED_ROUTE_ID_STATE_KEY] = default_route_id

    selected_route_id = st.selectbox(
        t(language, "time_window.route_select"),
        options=route_ids,
        format_func=lambda route_id: route_labels[route_id],
        key=SELECTED_ROUTE_ID_STATE_KEY,
    )
    selected_route = find_route_by_id(route_result.routes, selected_route_id)
    if selected_route is None:
        st.error(t(language, "time_window.route_missing"))
        return

    st.caption(
        t(
            language,
            "time_window.selected_route_caption",
            route_name=time_window_route_display_name(
                selected_route,
                route_ids.index(selected_route.route_id) + 1,
                language,
            ),
            distance=format_distance_km(selected_route.metrics.distance_m),
            duration=format_duration_minutes(selected_route.metrics.duration_s),
        )
    )

    st.subheader(t(language, "time_window.controls_title"))
    search_scope = st.radio(
        t(language, "search_scope.label"),
        options=["single_day", "date_range"],
        format_func=lambda value: t(language, f"search_scope.{value}"),
        key=SEARCH_SCOPE_STATE_KEY,
        horizontal=True,
    )
    if search_scope == "date_range":
        render_date_range_planner(
            selected_route=selected_route,
            route_result=route_result,
            settings=settings,
            browser_timezone=browser_timezone,
            language=language,
            today=datetime.now(
                ZoneInfo(str(st.session_state[TIMEZONE_STATE_KEY]))
            ).date(),
        )
        return

    controls_row_one = st.columns([1.15, 0.95, 1.3])
    with controls_row_one[0]:
        search_mode_value = st.radio(
            t(language, "time_window.mode"),
            options=["departure", "arrival"],
            format_func=lambda value: t(language, f"time_window.mode_{value}"),
            key=WINDOW_MODE_STATE_KEY,
            horizontal=True,
        )
        search_mode = cast(RouteTimeSearchMode, search_mode_value)
    with controls_row_one[1]:
        trip_date = st.date_input(t(language, "plan.date"), key=TRIP_DATE_STATE_KEY)
    with controls_row_one[2]:
        timezone_name = st.selectbox(
            t(language, "plan.timezone"),
            options=supported_timezones(),
            key=TIMEZONE_STATE_KEY,
            on_change=mark_timezone_manual,
        )
        timezone_mode = st.session_state.get(TIMEZONE_MODE_STATE_KEY)
        if timezone_mode == TIMEZONE_MODE_MANUAL:
            st.button(
                t(language, "plan.use_origin_timezone"),
                key="use_origin_timezone_button",
                width="stretch",
                on_click=restore_automatic_timezone,
                kwargs={
                    "origin_state": LocationPickerState(
                        query_text=route_result.origin.label,
                        provisional_result=None,
                        map_center=route_result.origin.coordinates,
                        confirmed_location=route_result.origin,
                        map_revision=0,
                    ),
                    "settings": settings,
                    "browser_timezone": browser_timezone,
                },
            )
            st.caption(t(language, "plan.timezone_manual_caption"))
        else:
            source_key = st.session_state.get(TIMEZONE_SOURCE_STATE_KEY, "default")
            st.caption(t(language, f"plan.timezone_auto_{source_key}"))
        st.caption(t(language, "plan.timezone_origin_mvp"))

    controls_row_two = st.columns([1, 1])
    with controls_row_two[0]:
        earliest_time = st.time_input(
            t(language, "time_window.earliest_time"),
            key=WINDOW_EARLIEST_TIME_STATE_KEY,
        )
    with controls_row_two[1]:
        latest_time = st.time_input(
            t(language, "time_window.latest_time"),
            key=WINDOW_LATEST_TIME_STATE_KEY,
        )

    evaluation_error: str | None = None
    submitted = st.button(
        t(language, "time_window.evaluate"),
        type="primary",
        width="stretch",
    )
    if submitted:
        try:
            earliest_moment, latest_moment = build_time_window(
                trip_date,
                earliest_time,
                latest_time,
                timezone_name,
            )
            params = TimeWindowEvaluationParams(
                route_id=selected_route.route_id,
                search_mode=search_mode,
                trip_date=trip_date,
                earliest_time=earliest_time,
                latest_time=latest_time,
                timezone_name=timezone_name,
            )
            logger.info(
                "Evaluating route=%s mode=%s earliest=%s latest=%s",
                selected_route.route_id,
                search_mode,
                earliest_moment.isoformat(),
                latest_moment.isoformat(),
            )
            save_time_window_result(
                evaluate_route_time_window(
                    selected_route,
                    earliest_moment,
                    latest_moment,
                    search_mode=search_mode,
                ),
                params,
            )
        except ValueError as exc:
            logger.info("Invalid time-window controls: %s", exc)
            evaluation_error = str(exc)

    if evaluation_error is not None:
        st.error(evaluation_error)

    saved_evaluation = get_saved_time_window_result()
    saved_params = get_saved_time_window_params()
    if saved_evaluation is None or saved_params is None:
        st.info(t(language, "time_window.empty_result"))
        return
    if not time_window_params_match_current(
        saved_params,
        route_id=selected_route.route_id,
        search_mode=search_mode,
        trip_date=trip_date,
        earliest_time=earliest_time,
        latest_time=latest_time,
        timezone_name=timezone_name,
    ):
        st.info(t(language, "time_window.needs_refresh"))
        return

    render_time_window_result(
        route_result=route_result,
        evaluation=saved_evaluation,
        params=saved_params,
        language=language,
    )


def main() -> None:
    st.set_page_config(page_title=t("es", "ui.page_title"), layout="wide")
    inject_app_styles()
    get_language_code()

    header_left, header_right = st.columns([5, 1.3])
    with header_left:
        st.title(t("es", "ui.page_title"))
    with header_right:
        language = render_language_toggle()

    st.markdown(
        f"""
        <div class="sunrouter-shell">
            <strong>{t(language, "ui.hero_title")}</strong><br>
            {t(language, "ui.hero_body")}
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.warning(t(language, "ui.advisory"))

    try:
        settings = load_settings()
    except ConfigError as exc:
        st.error(f"Configuration error: {exc}")
        st.stop()

    configure_logging(settings.log_level)
    geocoder = get_geocoder(settings)
    suggestion_provider = get_suggestion_provider(settings)
    router = get_router(settings)

    now = datetime.now(ZoneInfo(settings.default_timezone))
    if TRIP_DATE_STATE_KEY not in st.session_state:
        st.session_state[TRIP_DATE_STATE_KEY] = now.date()
    if TRIP_TIME_STATE_KEY not in st.session_state:
        st.session_state[TRIP_TIME_STATE_KEY] = time(hour=7, minute=0)
    if WINDOW_MODE_STATE_KEY not in st.session_state:
        st.session_state[WINDOW_MODE_STATE_KEY] = "departure"
    if WINDOW_EARLIEST_TIME_STATE_KEY not in st.session_state:
        st.session_state[WINDOW_EARLIEST_TIME_STATE_KEY] = time(hour=6, minute=30)
    if WINDOW_LATEST_TIME_STATE_KEY not in st.session_state:
        st.session_state[WINDOW_LATEST_TIME_STATE_KEY] = time(hour=8, minute=30)
    if SEARCH_SCOPE_STATE_KEY not in st.session_state:
        st.session_state[SEARCH_SCOPE_STATE_KEY] = "single_day"
    if DATE_RANGE_START_DATE_STATE_KEY not in st.session_state:
        st.session_state[DATE_RANGE_START_DATE_STATE_KEY] = now.date()
    if DATE_RANGE_END_DATE_STATE_KEY not in st.session_state:
        st.session_state[DATE_RANGE_END_DATE_STATE_KEY] = now.date() + timedelta(days=6)
    if DATE_RANGE_MODE_STATE_KEY not in st.session_state:
        st.session_state[DATE_RANGE_MODE_STATE_KEY] = "departure"
    if DATE_RANGE_EARLIEST_TIME_STATE_KEY not in st.session_state:
        st.session_state[DATE_RANGE_EARLIEST_TIME_STATE_KEY] = time(hour=6, minute=30)
    if DATE_RANGE_LATEST_TIME_STATE_KEY not in st.session_state:
        st.session_state[DATE_RANGE_LATEST_TIME_STATE_KEY] = time(hour=8, minute=30)

    render_information(language)

    left_panel, right_panel = st.columns([1, 1])
    right_panel_container = right_panel.container()

    origin_state = ensure_picker_state(
        ORIGIN_PICKER_STATE_KEY,
        DEFAULT_ORIGIN_QUERY,
        DEFAULT_ORIGIN_LOCATION,
    )
    destination_state = ensure_picker_state(
        DESTINATION_PICKER_STATE_KEY,
        DEFAULT_DESTINATION_QUERY,
        DEFAULT_DESTINATION_LOCATION,
    )
    browser_timezone = browser_timezone_from_streamlit()
    ensure_timezone_state(
        origin_state=origin_state,
        settings=settings,
        browser_timezone=browser_timezone,
    )

    current_request = build_analysis_request(
        origin_state,
        destination_state,
        trip_date=st.session_state[TRIP_DATE_STATE_KEY],
        trip_time=st.session_state[WINDOW_EARLIEST_TIME_STATE_KEY],
        timezone_name=st.session_state[TIMEZONE_STATE_KEY],
    )

    generation_error: str | None = None
    with left_panel:
        st.subheader(t(language, "plan.title"))
        st.caption(t(language, "plan.caption"))
        submitted = st.button(
            t(language, "ui.generate_routes"),
            key="generate_routes_button",
            type="primary",
            width="stretch",
            disabled=not can_generate_routes(origin_state, destination_state),
        )

    if submitted and current_request is not None:
        try:
            logger.info(
                "Generating route alternatives for origin=%s destination=%s",
                current_request.origin.label,
                current_request.destination.label,
            )
            save_route_alternatives(
                build_route_alternatives_result(
                    current_request,
                    router,
                    settings,
                    language,
                )
            )
            st.rerun()
        except (ProviderError, ValueError) as exc:
            logger.exception("Route generation failed")
            generation_error = str(exc)

    with left_panel:
        if generation_error is not None:
            st.error(generation_error)

        route_result = get_saved_route_alternatives()
        if route_result is None:
            st.info(t(language, "analysis.empty_result"))
        elif not route_alternatives_match_request(
            route_result,
            current_request,
            settings,
        ):
            st.info(t(language, "analysis.needs_refresh"))
        else:
            render_time_window_planner(
                route_result=route_result,
                settings=settings,
                browser_timezone=browser_timezone,
                language=language,
            )

    with right_panel_container:
        origin_state = render_picker(
            title=t(language, "picker.origin"),
            picker_kind="origin",
            state_key=ORIGIN_PICKER_STATE_KEY,
            input_key="origin_query_input",
            geocoder=geocoder,
            suggestion_provider=suggestion_provider,
            settings=settings,
            language=language,
        )
        st.button(
            t(language, "picker.reverse_locations"),
            key="reverse_locations_button",
            width="stretch",
            on_click=reverse_locations,
            kwargs={
                "origin_state": origin_state,
                "destination_state": destination_state,
                "settings": settings,
                "browser_timezone": browser_timezone,
            },
        )
        destination_state = render_picker(
            title=t(language, "picker.destination"),
            picker_kind="destination",
            state_key=DESTINATION_PICKER_STATE_KEY,
            input_key="destination_query_input",
            geocoder=geocoder,
            suggestion_provider=suggestion_provider,
            settings=settings,
            language=language,
        )


if __name__ == "__main__":
    main()
