from __future__ import annotations

from dataclasses import replace
from datetime import datetime, time, timedelta
import logging
from zoneinfo import ZoneInfo

import folium
import streamlit as st
from streamlit_folium import st_folium

from src.config import Settings, load_settings, supported_timezones
from src.geocoding import Geocoder, build_geocoder
from src.i18n import t
from src.mapview import build_picker_map, build_route_map
from src.models import (
    AnalysisRequest,
    AnalysisResult,
    Coordinates,
    GeocodeResult,
    LocationPickerState,
    RouteEvaluation,
    SelectedLocation,
    SunPosition,
)
from src.pickers import (
    apply_picker_search_result,
    build_analysis_request,
    can_generate_routes,
    confirm_picker_location,
    create_picker_state,
)
from src.routing import Router, build_router
from src.scoring import explain_recommendation, rank_routes
from src.utils import (
    ProviderError,
    configure_logging,
    format_distance_km,
    format_duration_minutes,
)

ANALYSIS_RESULT_STATE_KEY = "sunrouter_analysis_result"
ORIGIN_PICKER_STATE_KEY = "sunrouter_origin_picker_state"
DESTINATION_PICKER_STATE_KEY = "sunrouter_destination_picker_state"
TRIP_DATE_STATE_KEY = "sunrouter_trip_date"
TRIP_TIME_STATE_KEY = "sunrouter_trip_time"
TIMEZONE_STATE_KEY = "sunrouter_timezone"
LANGUAGE_STATE_KEY = "sunrouter_language"
LANGUAGE_WIDGET_STATE_KEY = "sunrouter_language_widget"
DEFAULT_ORIGIN_QUERY = "Madrid, Spain"
DEFAULT_DESTINATION_QUERY = "Burgos, Spain"
DEFAULT_MAP_CENTER = Coordinates(lat=40.4168, lon=-3.7038)

logger = logging.getLogger("sunrouter.app")


@st.cache_resource
def get_geocoder(settings: Settings) -> Geocoder:
    return build_geocoder(settings)


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
) -> folium.Map:
    return build_route_map(
        origin=origin,
        destination=destination,
        evaluations=list(evaluations),
        recommended_route_id=recommended_route_id,
        language=language,
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
        st.session_state[LANGUAGE_STATE_KEY] = "es"
    if LANGUAGE_WIDGET_STATE_KEY not in st.session_state:
        st.session_state[LANGUAGE_WIDGET_STATE_KEY] = "ES"
    return str(st.session_state[LANGUAGE_STATE_KEY])


def render_language_toggle() -> str:
    if LANGUAGE_WIDGET_STATE_KEY not in st.session_state:
        st.session_state[LANGUAGE_WIDGET_STATE_KEY] = "ES"
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


def peak_risk_summary(
    evaluation: RouteEvaluation,
    trip_start_moment: datetime,
    language: str = "es",
) -> tuple[str, str]:
    if evaluation.peak_risk_time_offset_min is None:
        return (t(language, "common.no_peak"), "-")

    peak_time = (
        trip_start_moment + timedelta(minutes=evaluation.peak_risk_time_offset_min)
    ).strftime("%H:%M")
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


def clear_analysis_result() -> None:
    st.session_state.pop(ANALYSIS_RESULT_STATE_KEY, None)


def ensure_picker_state(state_key: str, default_query: str) -> LocationPickerState:
    state = st.session_state.get(state_key)
    if isinstance(state, LocationPickerState):
        return state

    state = create_picker_state(default_query, DEFAULT_MAP_CENTER)
    st.session_state[state_key] = state
    return state


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


def render_picker(
    *,
    title: str,
    picker_kind: str,
    state_key: str,
    input_key: str,
    geocoder: Geocoder,
    language: str,
) -> LocationPickerState:
    state = ensure_picker_state(
        state_key,
        DEFAULT_ORIGIN_QUERY if picker_kind == "origin" else DEFAULT_DESTINATION_QUERY,
    )

    widget_key = f"{input_key}_{state.map_revision}"
    if widget_key not in st.session_state:
        st.session_state[widget_key] = state.query_text

    st.subheader(title)
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
            if warning_message is not None:
                st.session_state[f"{state_key}_warning"] = warning_message
            clear_analysis_result()
            st.rerun()

    warning_state_key = f"{state_key}_warning"
    warning_message = st.session_state.pop(warning_state_key, None)
    if isinstance(warning_message, str):
        st.warning(warning_message)
    error_state_key = f"{state_key}_error"
    error_message = st.session_state.pop(error_state_key, None)
    if isinstance(error_message, str):
        st.error(error_message)

    return ensure_picker_state(
        state_key,
        DEFAULT_ORIGIN_QUERY if picker_kind == "origin" else DEFAULT_DESTINATION_QUERY,
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
    )
    st_folium(
        route_map,
        use_container_width=True,
        height=460,
        key="route_map",
        returned_objects=[],
    )

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
                    }
                    for item in result.ranked_routes
                ],
            }
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

    settings = load_settings()
    configure_logging(settings.log_level)
    geocoder = get_geocoder(settings)
    router = get_router(settings)

    now = datetime.now(ZoneInfo(settings.default_timezone))
    if TRIP_DATE_STATE_KEY not in st.session_state:
        st.session_state[TRIP_DATE_STATE_KEY] = now.date()
    if TRIP_TIME_STATE_KEY not in st.session_state:
        st.session_state[TRIP_TIME_STATE_KEY] = time(hour=9, minute=0)
    if TIMEZONE_STATE_KEY not in st.session_state:
        st.session_state[TIMEZONE_STATE_KEY] = settings.default_timezone

    render_information(language)

    left_panel, right_panel = st.columns([1, 1])
    right_panel_container = right_panel.container()

    origin_state = ensure_picker_state(ORIGIN_PICKER_STATE_KEY, DEFAULT_ORIGIN_QUERY)
    destination_state = ensure_picker_state(
        DESTINATION_PICKER_STATE_KEY,
        DEFAULT_DESTINATION_QUERY,
    )

    current_request = build_analysis_request(
        origin_state,
        destination_state,
        trip_date=st.session_state[TRIP_DATE_STATE_KEY],
        trip_time=st.session_state[TRIP_TIME_STATE_KEY],
        timezone_name=st.session_state[TIMEZONE_STATE_KEY],
    )

    generation_error: str | None = None
    with left_panel:
        st.subheader(t(language, "plan.title"))
        st.caption(t(language, "plan.caption"))
        controls_col1, controls_col2, controls_col3 = st.columns([0.9, 0.9, 1.2])
        with controls_col1:
            trip_date = st.date_input(t(language, "plan.date"), key=TRIP_DATE_STATE_KEY)
        with controls_col2:
            trip_time = st.time_input(t(language, "plan.time"), key=TRIP_TIME_STATE_KEY)
        with controls_col3:
            timezone_name = st.selectbox(
                t(language, "plan.timezone"),
                options=supported_timezones(),
                key=TIMEZONE_STATE_KEY,
            )

        current_request = build_analysis_request(
            origin_state,
            destination_state,
            trip_date=trip_date,
            trip_time=trip_time,
            timezone_name=timezone_name,
        )
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
                "Generating routes for origin=%s destination=%s datetime=%s",
                current_request.origin.label,
                current_request.destination.label,
                current_request.trip_moment.isoformat(),
            )
            save_analysis_result(
                build_analysis_result(current_request, router, settings, language)
            )
            st.rerun()
        except (ProviderError, ValueError) as exc:
            logger.exception("Route generation failed")
            generation_error = str(exc)

    saved_result_to_render: AnalysisResult | None = None
    with left_panel:
        if generation_error is not None:
            st.error(generation_error)

        saved_result = get_saved_analysis_result()
        if saved_result is None:
            st.info(t(language, "analysis.empty_result"))
        elif current_request is None or saved_result.request != current_request:
            st.info(t(language, "analysis.needs_refresh"))
        else:
            render_analysis(saved_result, settings, language)
            saved_result_to_render = saved_result

    with right_panel_container:
        origin_state = render_picker(
            title=t(language, "picker.origin"),
            picker_kind="origin",
            state_key=ORIGIN_PICKER_STATE_KEY,
            input_key="origin_query_input",
            geocoder=geocoder,
            language=language,
        )
        destination_state = render_picker(
            title=t(language, "picker.destination"),
            picker_kind="destination",
            state_key=DESTINATION_PICKER_STATE_KEY,
            input_key="destination_query_input",
            geocoder=geocoder,
            language=language,
        )

    if saved_result_to_render is not None:
        render_comparison_table(saved_result_to_render, language)


if __name__ == "__main__":
    main()
