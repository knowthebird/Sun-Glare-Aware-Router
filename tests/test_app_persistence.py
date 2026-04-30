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
    RouteSegmentRisk,
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
    origin = make_selected_location(
        "Madrid, Community of Madrid, Spain",
        40.4168,
        -3.7038,
    )
    destination = make_selected_location(
        "Burgos, Castile and Leon, Spain",
        42.3439,
        -3.6969,
    )
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
        high_risk_distance_m=42000.0,
        high_risk_duration_s=1500.0,
        peak_risk_time_offset_min=38.0,
        peak_risk_distance_m=60000.0,
        peak_risk_coordinates=Coordinates(lat=41.3000, lon=-3.7000),
        segment_risks=[
            RouteSegmentRisk(
                start_coordinates=origin.coordinates,
                end_coordinates=Coordinates(lat=41.3000, lon=-3.7000),
                midpoint_coordinates=Coordinates(lat=40.8584, lon=-3.7019),
                segment_length_m=120000.0,
                estimated_duration_s=4500.0,
                start_offset_s=0.0,
                midpoint_offset_s=2250.0,
                bearing_deg=0.0,
                angle_difference_deg=30.0,
                sun_position=SunPosition(azimuth_deg=120.0, elevation_deg=18.0),
                glare_score=42.0,
            )
        ],
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


def test_saved_analysis_result_survives_rerun_when_picker_state_matches_request() -> (
    None
):
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

    assert "Rutas propuestas" in subheaders
    assert "Resumen de la ruta analizada" in subheaders
    assert "Comparativa de rutas" in subheaders
    assert not any("vuelve a generar" in item.lower() for item in infos)


def test_comparison_rows_include_peak_time_and_distance() -> None:
    result = make_analysis_result()

    rows = app.comparison_rows(
        route_evaluations=result.ranked_routes,
        recommended_route_id="route-1",
        fastest_route_id="route-1",
        trip_start_moment=result.request.trip_moment,
    )

    assert rows == [
        {
            "Ruta": "Opción 1",
            "Recomendada": "Sí",
            "Más rápida": "Sí",
            "Distancia": "240.0 km",
            "Duración": "2h 30m",
            "Riesgo": 24.5,
            "Tiempo con riesgo alto": "25 min",
            "Distancia con riesgo alto": "42.0 km",
            "Hora más delicada": "09:38",
            "KM del punto de mayor riesgo": "60.0 km",
        }
    ]


def test_peak_risk_summary_uses_clock_time_and_kilometer() -> None:
    result = make_analysis_result()

    summary = app.peak_risk_summary(
        result.ranked_routes[0],
        result.request.trip_moment,
    )

    assert summary == ("09:38", "60.0 km")
