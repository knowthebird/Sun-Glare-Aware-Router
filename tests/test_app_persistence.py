from __future__ import annotations

from datetime import datetime, time

from streamlit.testing.v1 import AppTest

import app
from src.geocoding import Geocoder
from src.models import (
    AddressSuggestion,
    AnalysisRequest,
    AnalysisResult,
    Coordinates,
    GeocodeResult,
    LocationPickerState,
    Route,
    RouteEvaluation,
    RouteHighGlareStretch,
    RouteMetrics,
    RouteSegmentRisk,
    SelectedLocation,
    SunPosition,
)
from src.route_time_search import evaluate_route_time_window
from src.utils import ProviderError


class ReverseFailingGeocoder(Geocoder):
    def geocode(self, query: str) -> None:
        raise AssertionError("This test should not call geocode")

    def reverse_geocode(self, coordinates: Coordinates) -> None:
        raise ProviderError("ssl failure")


class SearchFailingGeocoder(Geocoder):
    def geocode(self, query: str) -> None:
        raise ProviderError("ssl failure")

    def reverse_geocode(self, coordinates: Coordinates) -> None:
        raise AssertionError("This test should not call reverse_geocode")


class FailingSuggestionProvider:
    def suggest(self, query: str) -> list[AddressSuggestion]:
        raise ProviderError("suggestion failure")


class RecordingGeocoder(Geocoder):
    def __init__(self) -> None:
        self.queries: list[str] = []

    def geocode(self, query: str) -> GeocodeResult:
        self.queries.append(query)
        return GeocodeResult(
            label="Madrid, Community of Madrid, Spain",
            coordinates=Coordinates(lat=40.4168, lon=-3.7038),
        )

    def reverse_geocode(self, coordinates: Coordinates) -> None:
        raise AssertionError("This test should not call reverse_geocode")


def make_selected_location(label: str, lat: float, lon: float) -> SelectedLocation:
    return SelectedLocation(
        coordinates=Coordinates(lat=lat, lon=lon),
        label=label,
        label_source="reverse_geocode",
    )


def make_suggestion_settings() -> app.Settings:
    return app.Settings(
        geocoder_provider="nominatim",
        geocoder_base_url="https://example.com/search",
        reverse_geocoder_base_url="https://example.com/reverse",
        geocoder_min_interval_s=0.0,
        suggestions_enabled=True,
        suggestion_provider="photon",
        suggestion_endpoint_url="https://example.com/api",
        suggestion_min_query_length=3,
        suggestion_max_results=5,
        suggestion_min_interval_s=0.0,
        suggestion_debounce_ms=350,
        router_provider="osrm",
        router_base_url="https://example.com/route/v1",
        router_min_interval_s=0.0,
        routing_profile="driving",
        user_agent="sunrouter-tests",
        http_timeout_s=1.0,
        cache_ttl_s=0.0,
        max_alternatives=3,
        default_timezone="UTC",
        log_level="INFO",
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
    segment_risk = RouteSegmentRisk(
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
    evaluation = RouteEvaluation(
        route=route,
        glare_score=24.5,
        total_length_m=240000.0,
        peak_segment_score=42.0,
        aligned_distance_m=60000.0,
        dominant_bearing_deg=10.0,
        high_risk_distance_m=42000.0,
        high_risk_duration_s=1500.0,
        peak_risk_time_offset_min=38.0,
        peak_risk_distance_m=60000.0,
        peak_risk_coordinates=segment_risk.midpoint_coordinates,
        peak_glare_segment=segment_risk,
        peak_glare_coordinates=segment_risk.midpoint_coordinates,
        peak_glare_score=42.0,
        peak_glare_category="high",
        longest_high_glare_stretch=RouteHighGlareStretch(
            start_coordinates=origin.coordinates,
            end_coordinates=Coordinates(lat=41.3000, lon=-3.7000),
            start_offset_s=0.0,
            end_offset_s=4500.0,
            duration_s=4500.0,
            distance_m=120000.0,
            start_distance_m=0.0,
            end_distance_m=120000.0,
            max_glare_score=42.0,
            peak_segment=segment_risk,
            segments=[segment_risk],
        ),
        any_high_risk_segments=True,
        segment_risks=[segment_risk],
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


def test_saved_time_window_result_survives_rerun_when_picker_state_matches_request() -> (
    None
):
    result = make_analysis_result()
    route = result.ranked_routes[0].route
    window_result = evaluate_route_time_window(
        route,
        datetime.fromisoformat("2026-03-18T08:00:00-04:00"),
        datetime.fromisoformat("2026-03-18T08:20:00-04:00"),
        search_mode="departure",
        sun_position_at=lambda moment, coordinates: SunPosition(
            azimuth_deg=90.0,
            elevation_deg=-5.0,
        ),
    )
    at = AppTest.from_file("app.py")
    at.session_state[app.ROUTE_ALTERNATIVES_STATE_KEY] = app.RouteAlternativesResult(
        origin=result.request.origin,
        destination=result.request.destination,
        routing_profile="driving",
        routes=[route],
    )
    at.session_state[app.TIME_WINDOW_RESULT_STATE_KEY] = window_result
    at.session_state[app.TIME_WINDOW_PARAMS_STATE_KEY] = app.TimeWindowEvaluationParams(
        route_id=route.route_id,
        search_mode="departure",
        trip_date=datetime.fromisoformat("2026-03-18T08:00:00-04:00").date(),
        earliest_time=time(hour=8, minute=0),
        latest_time=time(hour=8, minute=20),
        timezone_name="America/New_York",
    )
    at.session_state[app.SELECTED_ROUTE_ID_STATE_KEY] = route.route_id
    at.session_state[app.WINDOW_MODE_STATE_KEY] = "departure"
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
    at.session_state[app.TRIP_DATE_STATE_KEY] = datetime.fromisoformat(
        "2026-03-18T08:00:00-04:00"
    ).date()
    at.session_state[app.WINDOW_EARLIEST_TIME_STATE_KEY] = time(hour=8, minute=0)
    at.session_state[app.WINDOW_LATEST_TIME_STATE_KEY] = time(hour=8, minute=20)
    at.session_state[app.TIMEZONE_STATE_KEY] = "America/New_York"

    at.run()

    subheaders = [item.value for item in at.subheader]
    infos = [item.value for item in at.info]

    assert "Proposed routes" in subheaders
    assert "Best estimated departure time" in subheaders
    assert "Complete candidate results" in subheaders
    assert not any("get route alternatives again" in item.lower() for item in infos)


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
            "Duración": "2 hr 30 min",
            "Riesgo": 24.5,
            "Tiempo con riesgo alto": "25 min",
            "Distancia con riesgo alto": "42.0 km",
            "Hora del pico": "09:38",
            "KM del pico": "60.0 km",
        }
    ]


def test_peak_risk_summary_uses_clock_time_and_kilometer() -> None:
    result = make_analysis_result()

    summary = app.peak_risk_summary(
        result.ranked_routes[0],
        result.request.trip_moment,
    )

    assert summary == ("09:38", "60.0 km")


def test_resolve_picker_confirmation_falls_back_when_reverse_geocoding_fails() -> None:
    initial_state = LocationPickerState(
        query_text="Calle Mayor 1, Madrid",
        provisional_result=None,
        map_center=Coordinates(lat=40.4168, lon=-3.7038),
        confirmed_location=None,
        map_revision=4,
    )
    clicked_coordinates = Coordinates(lat=40.4162, lon=-3.7041)

    updated_state, warning_message = app.resolve_picker_confirmation(
        state=initial_state,
        query_text=initial_state.query_text,
        clicked_coordinates=clicked_coordinates,
        geocoder=ReverseFailingGeocoder(),
        picker_kind="origin",
        language="es",
    )

    assert updated_state.confirmed_location is not None
    assert updated_state.confirmed_location.coordinates == clicked_coordinates
    assert updated_state.confirmed_location.label == "Calle Mayor 1, Madrid"
    assert updated_state.confirmed_location.label_source == "query_text"
    assert updated_state.map_revision == 5
    assert warning_message is not None
    assert "No se pudo obtener" in warning_message


def test_resolve_picker_search_keeps_previous_state_when_geocoding_fails() -> None:
    initial_state = LocationPickerState(
        query_text="Madrid, Spain",
        provisional_result=None,
        map_center=Coordinates(lat=40.4168, lon=-3.7038),
        confirmed_location=None,
        map_revision=2,
    )

    updated_state, error_message = app.resolve_picker_search(
        state=initial_state,
        query_text="Madrid, Spain",
        geocoder=SearchFailingGeocoder(),
        picker_kind="origin",
        language="es",
    )

    assert updated_state == initial_state
    assert error_message is not None
    assert "No se pudo buscar" in error_message


def test_existing_explicit_search_flow_still_uses_configured_geocoder() -> None:
    initial_state = LocationPickerState(
        query_text="Madrid",
        provisional_result=None,
        map_center=Coordinates(lat=40.4168, lon=-3.7038),
        confirmed_location=None,
        map_revision=2,
    )
    geocoder = RecordingGeocoder()

    updated_state, error_message = app.resolve_picker_search(
        state=initial_state,
        query_text="Madrid airport",
        geocoder=geocoder,
        picker_kind="origin",
        language="en",
    )

    assert geocoder.queries == ["Madrid airport"]
    assert error_message is None
    assert updated_state.query_text == "Madrid airport"
    assert updated_state.provisional_result is not None
    assert updated_state.provisional_result.label.startswith("Madrid")


def test_suggestion_selection_updates_picker_state_and_invalidates_analysis() -> None:
    for key in list(app.st.session_state.keys()):
        del app.st.session_state[key]
    initial_state = LocationPickerState(
        query_text="Madrid",
        provisional_result=None,
        map_center=Coordinates(lat=40.4168, lon=-3.7038),
        confirmed_location=make_selected_location("Old Madrid", 40.4168, -3.7038),
        map_revision=2,
    )
    app.st.session_state[app.ANALYSIS_RESULT_STATE_KEY] = make_analysis_result()
    app.st.session_state[app.ROUTE_ALTERNATIVES_STATE_KEY] = "stale routes"
    app.st.session_state[app.TIME_WINDOW_RESULT_STATE_KEY] = "stale glare"
    app.st.session_state[app.DATE_RANGE_RESULT_STATE_KEY] = "stale date range"
    suggestion = AddressSuggestion(
        label="Madrid-Barajas Airport, Madrid, Spain",
        coordinates=Coordinates(lat=40.4983, lon=-3.5676),
        provider_id="W:456",
    )

    updated_state = app.apply_picker_suggestion_selection(
        state_key=app.ORIGIN_PICKER_STATE_KEY,
        state=initial_state,
        suggestion=suggestion,
    )

    assert updated_state.query_text == suggestion.label
    assert updated_state.provisional_result is not None
    assert updated_state.provisional_result.provider_id == "W:456"
    assert updated_state.map_center == suggestion.coordinates
    assert updated_state.confirmed_location is None
    assert app.ORIGIN_PICKER_STATE_KEY in app.st.session_state
    assert app.ANALYSIS_RESULT_STATE_KEY not in app.st.session_state
    assert app.ROUTE_ALTERNATIVES_STATE_KEY not in app.st.session_state
    assert app.TIME_WINDOW_RESULT_STATE_KEY not in app.st.session_state
    assert app.DATE_RANGE_RESULT_STATE_KEY not in app.st.session_state
    assert app.st.session_state[app.RECENT_SUGGESTIONS_STATE_KEY] == [suggestion]


def test_confirmed_locations_are_available_as_recent_local_suggestions() -> None:
    for key in list(app.st.session_state.keys()):
        del app.st.session_state[key]
    location = make_selected_location("Confirmed Warrenton", 38.7135, -77.7953)

    app.remember_recent_location(location)

    suggestions = app.recent_suggestions_for_query("warr", limit=5)
    assert suggestions == [
        AddressSuggestion(
            label="Confirmed Warrenton",
            coordinates=location.coordinates,
        )
    ]


def test_local_suggestions_survive_remote_provider_failure() -> None:
    for key in list(app.st.session_state.keys()):
        del app.st.session_state[key]
    suggestion = AddressSuggestion(
        label="Confirmed Warrenton",
        coordinates=Coordinates(lat=38.7135, lon=-77.7953),
    )
    app.remember_recent_suggestion(suggestion)

    options = app.picker_suggestion_options(
        query="warr",
        suggestion_provider=FailingSuggestionProvider(),
        settings=make_suggestion_settings(),
        state_key=app.ORIGIN_PICKER_STATE_KEY,
        language="en",
    )

    assert options == [(suggestion.label, suggestion)]
    assert app.st.session_state[
        f"{app.ORIGIN_PICKER_STATE_KEY}_suggestion_warning"
    ].startswith("Suggestions are unavailable")


def test_extract_selected_coordinates_accepts_click_on_provisional_marker() -> None:
    provisional_coordinates = Coordinates(lat=40.4168, lon=-3.7038)
    state = LocationPickerState(
        query_text="Madrid, Spain",
        provisional_result=app.GeocodeResult(
            label="Madrid, Comunidad de Madrid, España",
            coordinates=provisional_coordinates,
        ),
        map_center=provisional_coordinates,
        confirmed_location=None,
        map_revision=1,
    )

    selected = app.extract_selected_coordinates(
        map_data={
            "last_clicked": None,
            "last_object_clicked_tooltip": "Origen provisional",
        },
        state=state,
        picker_kind="origin",
        language="es",
    )

    assert selected == provisional_coordinates
