from __future__ import annotations

from datetime import datetime, time

from streamlit.testing.v1 import AppTest

import app
from src.models import (
    AnalysisRequest,
    AnalysisResult,
    Coordinates,
    LocationPickerState,
    Route,
    RouteEvaluation,
    RouteMetrics,
    SelectedLocation,
    SunPosition,
)


def make_selected_location(label: str, lat: float, lon: float) -> SelectedLocation:
    return SelectedLocation(
        coordinates=Coordinates(lat=lat, lon=lon),
        label=label,
        label_source="reverse_geocode",
    )


def make_analysis_result() -> AnalysisResult:
    origin = make_selected_location("Madrid, Community of Madrid, Spain", 40.4168, -3.7038)
    destination = make_selected_location("Burgos, Castile and Leon, Spain", 42.3439, -3.6969)
    route = Route(
        route_id="route-1",
        geometry=[
            origin.coordinates,
            Coordinates(lat=41.3000, lon=-3.7000),
            destination.coordinates,
        ],
        metrics=RouteMetrics(distance_m=240000.0, duration_s=9000.0),
    )
    evaluation = RouteEvaluation(
        route=route,
        glare_score=24.5,
        total_length_m=240000.0,
        peak_segment_score=310.0,
        aligned_distance_m=60000.0,
        dominant_bearing_deg=10.0,
    )
    request = AnalysisRequest(
        origin=origin,
        destination=destination,
        trip_moment=datetime.fromisoformat("2026-03-18T09:00:00+01:00"),
        timezone_name="Europe/Madrid",
    )
    return AnalysisResult(
        request=request,
        sun_position=SunPosition(azimuth_deg=120.0, elevation_deg=18.0),
        ranked_routes=[evaluation],
        explanation="Esta ruta reduce ligeramente el deslumbramiento evitando tramos largos orientados hacia el sol.",
    )


def test_saved_analysis_result_survives_rerun_when_picker_state_matches_request() -> None:
    result = make_analysis_result()
    at = AppTest.from_file("app.py")
    at.session_state[app.ANALYSIS_RESULT_STATE_KEY] = result
    at.session_state[app.ORIGIN_PICKER_STATE_KEY] = LocationPickerState(
        query_text="Madrid, Spain",
        provisional_result=None,
        map_center=result.request.origin.coordinates,
        confirmed_location=result.request.origin,
        map_revision=0,
    )
    at.session_state[app.DESTINATION_PICKER_STATE_KEY] = LocationPickerState(
        query_text="Burgos, Spain",
        provisional_result=None,
        map_center=result.request.destination.coordinates,
        confirmed_location=result.request.destination,
        map_revision=0,
    )
    at.session_state[app.TRIP_DATE_STATE_KEY] = result.request.trip_moment.date()
    at.session_state[app.TRIP_TIME_STATE_KEY] = time(hour=9, minute=0)
    at.session_state[app.TIMEZONE_STATE_KEY] = "Europe/Madrid"

    at.run()

    subheaders = [item.value for item in at.subheader]
    infos = [item.value for item in at.info]

    assert "Ruta recomendada" in subheaders
    assert "Mapa de rutas" in subheaders
    assert "Comparativa de rutas" in subheaders
    assert not any("vuelve a generar" in item.lower() for item in infos)
