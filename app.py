from __future__ import annotations

from dataclasses import replace
from datetime import datetime, time
import logging
from zoneinfo import ZoneInfo

import streamlit as st
from streamlit_folium import st_folium

from src.config import Settings, load_settings, supported_timezones
from src.geocoding import Geocoder, build_geocoder
from src.mapview import build_picker_map, build_route_map
from src.models import AnalysisRequest, AnalysisResult, Coordinates, LocationPickerState
from src.pickers import (
    apply_picker_search_result,
    build_analysis_request,
    can_generate_routes,
    confirm_picker_location,
    create_picker_state,
)
from src.routing import Router, build_router
from src.scoring import explain_recommendation, rank_routes
from src.utils import ProviderError, configure_logging, format_distance_km, format_duration_minutes

ANALYSIS_RESULT_STATE_KEY = "sunrouter_analysis_result"
ORIGIN_PICKER_STATE_KEY = "sunrouter_origin_picker_state"
DESTINATION_PICKER_STATE_KEY = "sunrouter_destination_picker_state"
TRIP_DATE_STATE_KEY = "sunrouter_trip_date"
TRIP_TIME_STATE_KEY = "sunrouter_trip_time"
TIMEZONE_STATE_KEY = "sunrouter_timezone"
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


def comparison_rows(route_evaluations: list, recommended_route_id: str, fastest_route_id: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, evaluation in enumerate(route_evaluations, start=1):
        rows.append(
            {
                "Ruta": f"Opción {index}",
                "Recomendada": "Sí" if evaluation.route.route_id == recommended_route_id else "",
                "Más rápida": "Sí" if evaluation.route.route_id == fastest_route_id else "",
                "Distancia": format_distance_km(evaluation.route.metrics.distance_m),
                "Duración": format_duration_minutes(evaluation.route.metrics.duration_s),
                "Glare risk": round(evaluation.glare_score, 1),
            }
        )
    return rows


def render_summary(recommended, sun_position) -> None:
    card_one, card_two, card_three = st.columns(3)
    card_one.metric("Distancia", format_distance_km(recommended.route.metrics.distance_m))
    card_two.metric("Duración", format_duration_minutes(recommended.route.metrics.duration_s))
    card_three.metric("Glare risk", f"{recommended.glare_score:.1f} / 100")
    st.caption(
        f"Azimut solar: {sun_position.azimuth_deg:.1f} deg | "
        f"Elevación solar: {sun_position.elevation_deg:.1f} deg"
    )


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


def build_analysis_result(
    request: AnalysisRequest,
    router: Router,
    settings: Settings,
) -> AnalysisResult:
    routes = router.get_routes(
        origin=request.origin.coordinates,
        destination=request.destination.coordinates,
        profile=settings.routing_profile,
    )
    if not routes:
        logger.warning("Routing returned no routes for origin=%s destination=%s", request.origin.label, request.destination.label)
        raise ValueError("El proveedor de rutas no ha devuelto rutas candidatas para este trayecto.")

    from src.solar import get_sun_position

    sun_position = get_sun_position(request.trip_moment, request.origin.coordinates)
    ranked_routes = rank_routes(routes, sun_position)
    explanation = explain_recommendation(ranked_routes[0], ranked_routes[1:], sun_position)
    return AnalysisResult(
        request=request,
        sun_position=sun_position,
        ranked_routes=ranked_routes,
        explanation=explanation,
    )


def render_information() -> None:
    with st.expander("Información"):
        st.markdown("**Qué es**")
        st.markdown(
            "Esta herramienta compara varias rutas y estima cuál reduce más la probabilidad de conducir con el sol de frente."
        )
        st.markdown("**Cómo funciona**")
        st.markdown(
            "Primero buscas una zona aproximada para origen y destino. Después haces clic en el punto exacto en cada mapa. "
            "Con esos dos puntos, la app calcula el sol para la fecha y la hora elegidas y compara rutas posibles."
        )
        st.markdown("**Qué es el glare risk**")
        st.markdown(
            "`Glare risk` es una puntuación de 0 a 100 que estima cuánto puede alinearse tu trayecto con la dirección del sol, "
            "sobre todo cuando el sol está bajo."
        )
        st.markdown("**Cómo interpretar el resultado**")
        st.markdown(
            "Cuanto más baja sea la puntuación, menor es la probabilidad de llevar el sol de frente durante más tiempo."
        )
        st.markdown("**Limitaciones**")
        st.markdown(
            "Es una heurística útil, no una garantía de seguridad. No considera tráfico, edificios, árboles, meteorología ni todos los cambios del sol durante la ruta."
        )


def picker_status_text(state: LocationPickerState) -> tuple[str, str]:
    confirmed = state.confirmed_location
    if confirmed is not None:
        if confirmed.label_source == "coordinates":
            return "success", f"Punto confirmado en {confirmed.label}"
        return "success", f"Punto confirmado: {confirmed.label}"
    if state.provisional_result is not None:
        return "info", "Resultado encontrado. Haz clic en el punto exacto del mapa para confirmarlo."
    return "info", "Escribe una zona aproximada y luego haz clic en el punto exacto."


def render_picker(
    *,
    title: str,
    picker_kind: str,
    state_key: str,
    input_key: str,
    button_key: str,
    geocoder: Geocoder,
) -> LocationPickerState:
    state = ensure_picker_state(state_key, DEFAULT_ORIGIN_QUERY if picker_kind == "origin" else DEFAULT_DESTINATION_QUERY)

    widget_key = f"{input_key}_{state.map_revision}"
    if widget_key not in st.session_state:
        st.session_state[widget_key] = state.query_text

    st.subheader(title)
    query_text = st.text_input(title, key=widget_key, label_visibility="collapsed")
    if st.button("Buscar", key=button_key, width="stretch"):
        if not query_text.strip():
            st.warning("Introduce una dirección aproximada antes de buscar.")
        else:
            logger.info("Searching %s picker with query=%s", picker_kind, query_text)
            result = geocoder.geocode(query_text)
            st.session_state[state_key] = apply_picker_search_result(state, query_text, result)
            clear_analysis_result()
            st.rerun()

    state = ensure_picker_state(state_key, DEFAULT_ORIGIN_QUERY if picker_kind == "origin" else DEFAULT_DESTINATION_QUERY)
    status_kind, status_message = picker_status_text(state)
    getattr(st, status_kind)(status_message)
    st.caption("Busca una zona aproximada y luego haz clic en el punto exacto.")

    picker_map = build_picker_map(state, picker_kind)
    map_data = st_folium(
        picker_map,
        key=f"{picker_kind}_picker_map_{state.map_revision}",
        height=360,
        use_container_width=True,
        returned_objects=["last_clicked"],
    )
    clicked_coordinates = extract_clicked_coordinates(map_data)
    if clicked_coordinates is not None:
        confirmed = state.confirmed_location
        if confirmed is None or confirmed.coordinates != clicked_coordinates:
            logger.info("Confirmed %s picker at lat=%.5f lon=%.5f", picker_kind, clicked_coordinates.lat, clicked_coordinates.lon)
            reverse_result = geocoder.reverse_geocode(clicked_coordinates)
            live_state = state if query_text == state.query_text else replace(state, query_text=query_text)
            updated_state = confirm_picker_location(live_state, clicked_coordinates, reverse_result)
            st.session_state[state_key] = updated_state
            clear_analysis_result()
            st.rerun()

    return ensure_picker_state(state_key, DEFAULT_ORIGIN_QUERY if picker_kind == "origin" else DEFAULT_DESTINATION_QUERY)


def render_analysis(result: AnalysisResult, settings: Settings) -> None:
    recommended = result.ranked_routes[0]
    fastest = min(result.ranked_routes, key=lambda item: item.route.metrics.duration_s)

    st.subheader("Ruta recomendada")
    render_summary(recommended, result.sun_position)
    st.write(result.explanation)
    if recommended.route.route_id != fastest.route.route_id:
        saved_minutes = (recommended.route.metrics.duration_s - fastest.route.metrics.duration_s) / 60.0
        st.info(
            f"La alternativa más rápida tarda {abs(saved_minutes):.1f} minutos menos, "
            "pero tiene un glare risk mayor."
        )

    route_map = build_route_map(
        origin=result.request.origin.coordinates,
        destination=result.request.destination.coordinates,
        evaluations=result.ranked_routes,
        recommended_route_id=recommended.route.route_id,
    )
    st.subheader("Mapa de rutas")
    st_folium(
        route_map,
        use_container_width=True,
        height=520,
        key="route_map",
        returned_objects=[],
    )

    st.subheader("Comparativa de rutas")
    st.dataframe(
        comparison_rows(
            route_evaluations=result.ranked_routes,
            recommended_route_id=recommended.route.route_id,
            fastest_route_id=fastest.route.route_id,
        ),
        width="stretch",
        hide_index=True,
    )

    with st.expander("Debug details"):
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
                    }
                    for item in result.ranked_routes
                ],
            }
        )


def main() -> None:
    st.set_page_config(page_title="Sun Glare Aware Router", layout="wide")
    st.title("Sun-Glare-Aware Router")
    st.caption("Selecciona origen y destino en el mapa y compara rutas con menor probabilidad de sol de frente.")

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

    render_information()

    controls_col1, controls_col2, controls_col3, controls_col4 = st.columns([1, 1, 1, 1])
    with controls_col1:
        trip_date = st.date_input("Fecha", key=TRIP_DATE_STATE_KEY)
    with controls_col2:
        trip_time = st.time_input("Hora", key=TRIP_TIME_STATE_KEY)
    with controls_col3:
        timezone_name = st.selectbox("Zona horaria", options=supported_timezones(), key=TIMEZONE_STATE_KEY)

    origin_col, destination_col = st.columns(2)
    with origin_col:
        origin_state = render_picker(
            title="Origen",
            picker_kind="origin",
            state_key=ORIGIN_PICKER_STATE_KEY,
            input_key="origin_query_input",
            button_key="origin_search_button",
            geocoder=geocoder,
        )
    with destination_col:
        destination_state = render_picker(
            title="Destino",
            picker_kind="destination",
            state_key=DESTINATION_PICKER_STATE_KEY,
            input_key="destination_query_input",
            button_key="destination_search_button",
            geocoder=geocoder,
        )

    current_request = build_analysis_request(
        origin_state,
        destination_state,
        trip_date=trip_date,
        trip_time=trip_time,
        timezone_name=timezone_name,
    )

    with controls_col4:
        submitted = st.button(
            "Generar rutas",
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
            save_analysis_result(build_analysis_result(current_request, router, settings))
            st.rerun()
        except (ProviderError, ValueError) as exc:
            logger.exception("Route generation failed")
            st.error(str(exc))
            return

    saved_result = get_saved_analysis_result()
    if saved_result is None:
        st.info("Confirma origen y destino en los mapas y luego pulsa Generar rutas.")
        return

    if current_request is None or saved_result.request != current_request:
        st.info("La selección o la configuración ha cambiado. Vuelve a generar las rutas.")
        return

    render_analysis(saved_result, settings)


if __name__ == "__main__":
    main()
