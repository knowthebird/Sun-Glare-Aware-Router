from __future__ import annotations

from dataclasses import replace

import streamlit as st

import app
from src.config import Settings
from src.models import Coordinates, GeocodeResult, LocationPickerState, SelectedLocation
from src.timezones import resolve_automatic_timezone


class StaticTimezoneFinder:
    def timezone_at(self, *, lat: float, lng: float) -> str | None:
        if lat > 35.0:
            return "America/New_York"
        return "America/Los_Angeles"


class InvalidTimezoneFinder:
    def timezone_at(self, *, lat: float, lng: float) -> str | None:
        return "Invalid/Zone"


def make_settings(default_timezone: str = "UTC") -> Settings:
    return Settings(
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
        default_timezone=default_timezone,
        log_level="INFO",
    )


def make_picker_state(
    *,
    query: str,
    label: str,
    lat: float,
    lon: float,
    map_revision: int,
) -> LocationPickerState:
    coordinates = Coordinates(lat=lat, lon=lon)
    return LocationPickerState(
        query_text=query,
        provisional_result=GeocodeResult(
            label=f"Provisional {label}",
            coordinates=Coordinates(lat=lat + 0.01, lon=lon + 0.01),
        ),
        map_center=coordinates,
        confirmed_location=SelectedLocation(
            coordinates=coordinates,
            label=label,
            label_source="reverse_geocode",
        ),
        map_revision=map_revision,
    )


def clear_streamlit_session_state() -> None:
    for key in list(st.session_state.keys()):
        del st.session_state[key]


def without_revision(state: LocationPickerState) -> LocationPickerState:
    return replace(state, map_revision=0)


def test_complete_origin_destination_state_reversal() -> None:
    origin = make_picker_state(
        query="origin typed",
        label="Origin Label",
        lat=40.7128,
        lon=-74.0060,
        map_revision=2,
    )
    destination = make_picker_state(
        query="destination typed",
        label="Destination Label",
        lat=34.0522,
        lon=-118.2437,
        map_revision=5,
    )

    new_origin, new_destination = app.swap_picker_states(
        origin_state=origin,
        destination_state=destination,
    )

    assert without_revision(new_origin) == without_revision(destination)
    assert without_revision(new_destination) == without_revision(origin)
    assert new_origin.map_revision == 6
    assert new_destination.map_revision == 6


def test_reversing_twice_restores_original_location_values() -> None:
    origin = make_picker_state(
        query="origin typed",
        label="Origin Label",
        lat=40.7128,
        lon=-74.0060,
        map_revision=2,
    )
    destination = make_picker_state(
        query="destination typed",
        label="Destination Label",
        lat=34.0522,
        lon=-118.2437,
        map_revision=5,
    )

    reversed_origin, reversed_destination = app.swap_picker_states(
        origin_state=origin,
        destination_state=destination,
    )
    restored_origin, restored_destination = app.swap_picker_states(
        origin_state=reversed_origin,
        destination_state=reversed_destination,
    )

    assert without_revision(restored_origin) == without_revision(origin)
    assert without_revision(restored_destination) == without_revision(destination)


def test_reversal_invalidates_analysis_results() -> None:
    clear_streamlit_session_state()
    origin = make_picker_state(
        query="origin typed",
        label="Origin Label",
        lat=40.7128,
        lon=-74.0060,
        map_revision=0,
    )
    destination = make_picker_state(
        query="destination typed",
        label="Destination Label",
        lat=34.0522,
        lon=-118.2437,
        map_revision=0,
    )
    for key in (
        app.ANALYSIS_RESULT_STATE_KEY,
        app.ROUTE_ALTERNATIVES_STATE_KEY,
        app.TIME_WINDOW_RESULT_STATE_KEY,
        app.TIME_WINDOW_PARAMS_STATE_KEY,
        app.DATE_RANGE_RESULT_STATE_KEY,
        app.DATE_RANGE_PARAMS_STATE_KEY,
        app.SELECTED_ROUTE_ID_STATE_KEY,
        app.INSPECTED_CANDIDATE_KEY_STATE_KEY,
        app.INSPECTED_RESULT_SIGNATURE_STATE_KEY,
        app.DATE_RANGE_INSPECTED_CANDIDATE_KEY_STATE_KEY,
        app.DATE_RANGE_INSPECTED_RESULT_SIGNATURE_STATE_KEY,
    ):
        st.session_state[key] = "stale"
    st.session_state[app.TIMEZONE_MODE_STATE_KEY] = app.TIMEZONE_MODE_MANUAL
    st.session_state[app.TIMEZONE_STATE_KEY] = "Europe/Madrid"

    app.reverse_locations(
        origin_state=origin,
        destination_state=destination,
        settings=make_settings(),
        browser_timezone="America/Chicago",
    )

    assert st.session_state[app.ORIGIN_PICKER_STATE_KEY].query_text == (
        destination.query_text
    )
    for key in (
        app.ANALYSIS_RESULT_STATE_KEY,
        app.ROUTE_ALTERNATIVES_STATE_KEY,
        app.TIME_WINDOW_RESULT_STATE_KEY,
        app.TIME_WINDOW_PARAMS_STATE_KEY,
        app.DATE_RANGE_RESULT_STATE_KEY,
        app.DATE_RANGE_PARAMS_STATE_KEY,
        app.SELECTED_ROUTE_ID_STATE_KEY,
        app.INSPECTED_CANDIDATE_KEY_STATE_KEY,
        app.INSPECTED_RESULT_SIGNATURE_STATE_KEY,
        app.DATE_RANGE_INSPECTED_CANDIDATE_KEY_STATE_KEY,
        app.DATE_RANGE_INSPECTED_RESULT_SIGNATURE_STATE_KEY,
    ):
        assert key not in st.session_state


def test_reversal_preserves_live_entered_search_text() -> None:
    clear_streamlit_session_state()
    origin = make_picker_state(
        query="saved origin",
        label="Origin Label",
        lat=40.7128,
        lon=-74.0060,
        map_revision=2,
    )
    destination = make_picker_state(
        query="saved destination",
        label="Destination Label",
        lat=34.0522,
        lon=-118.2437,
        map_revision=5,
    )
    st.session_state["origin_query_input_2"] = "unsent origin edit"
    st.session_state["destination_query_input_5"] = "unsent destination edit"
    st.session_state[app.TIMEZONE_MODE_STATE_KEY] = app.TIMEZONE_MODE_MANUAL
    st.session_state[app.TIMEZONE_STATE_KEY] = "Europe/Madrid"

    app.reverse_locations(
        origin_state=origin,
        destination_state=destination,
        settings=make_settings(),
        browser_timezone="America/Chicago",
    )

    new_origin = st.session_state[app.ORIGIN_PICKER_STATE_KEY]
    new_destination = st.session_state[app.DESTINATION_PICKER_STATE_KEY]

    assert new_origin.query_text == "unsent destination edit"
    assert new_destination.query_text == "unsent origin edit"
    assert st.session_state[f"origin_query_input_{new_origin.map_revision}"] == (
        "unsent destination edit"
    )
    assert st.session_state[
        f"destination_query_input_{new_destination.map_revision}"
    ] == ("unsent origin edit")


def test_timezone_inferred_from_confirmed_origin_coordinates() -> None:
    origin = make_picker_state(
        query="New York",
        label="New York",
        lat=40.7128,
        lon=-74.0060,
        map_revision=0,
    )

    resolved = resolve_automatic_timezone(
        origin=origin,
        browser_timezone="America/Chicago",
        configured_default_timezone="UTC",
        finder=StaticTimezoneFinder(),
    )

    assert resolved.name == "America/New_York"
    assert resolved.source == "origin"


def test_browser_timezone_fallback_without_confirmed_origin() -> None:
    origin = LocationPickerState(
        query_text="unconfirmed",
        provisional_result=None,
        map_center=Coordinates(lat=0.0, lon=0.0),
        confirmed_location=None,
        map_revision=0,
    )

    resolved = resolve_automatic_timezone(
        origin=origin,
        browser_timezone="America/Chicago",
        configured_default_timezone="UTC",
        finder=StaticTimezoneFinder(),
    )

    assert resolved.name == "America/Chicago"
    assert resolved.source == "browser"


def test_configured_timezone_fallback_when_origin_and_browser_are_unavailable() -> None:
    resolved = resolve_automatic_timezone(
        origin=None,
        browser_timezone=None,
        configured_default_timezone="Europe/Madrid",
        finder=StaticTimezoneFinder(),
    )

    assert resolved.name == "Europe/Madrid"
    assert resolved.source == "default"


def test_manual_timezone_override_survives_origin_changes() -> None:
    clear_streamlit_session_state()
    origin = make_picker_state(
        query="Los Angeles",
        label="Los Angeles",
        lat=34.0522,
        lon=-118.2437,
        map_revision=0,
    )
    st.session_state[app.TIMEZONE_MODE_STATE_KEY] = app.TIMEZONE_MODE_MANUAL
    st.session_state[app.TIMEZONE_STATE_KEY] = "Europe/Madrid"

    timezone_name = app.ensure_timezone_state(
        origin_state=origin,
        settings=make_settings(default_timezone="UTC"),
        browser_timezone="America/Chicago",
        finder=StaticTimezoneFinder(),
    )

    assert timezone_name == "Europe/Madrid"
    assert st.session_state[app.TIMEZONE_MODE_STATE_KEY] == app.TIMEZONE_MODE_MANUAL


def test_restoring_automatic_timezone_selection() -> None:
    clear_streamlit_session_state()
    origin = make_picker_state(
        query="Los Angeles",
        label="Los Angeles",
        lat=34.0522,
        lon=-118.2437,
        map_revision=0,
    )
    st.session_state[app.TIMEZONE_MODE_STATE_KEY] = app.TIMEZONE_MODE_MANUAL
    st.session_state[app.TIMEZONE_STATE_KEY] = "Europe/Madrid"

    app.restore_automatic_timezone(
        origin_state=origin,
        settings=make_settings(default_timezone="UTC"),
        browser_timezone="America/Chicago",
        finder=StaticTimezoneFinder(),
    )

    assert st.session_state[app.TIMEZONE_MODE_STATE_KEY] == app.TIMEZONE_MODE_AUTOMATIC
    assert st.session_state[app.TIMEZONE_STATE_KEY] == "America/Los_Angeles"
    assert st.session_state[app.TIMEZONE_SOURCE_STATE_KEY] == "origin"


def test_reversal_updates_automatic_timezone_from_new_origin() -> None:
    clear_streamlit_session_state()
    origin = make_picker_state(
        query="New York",
        label="New York",
        lat=40.7128,
        lon=-74.0060,
        map_revision=0,
    )
    destination = make_picker_state(
        query="Los Angeles",
        label="Los Angeles",
        lat=34.0522,
        lon=-118.2437,
        map_revision=0,
    )
    st.session_state[app.TIMEZONE_MODE_STATE_KEY] = app.TIMEZONE_MODE_AUTOMATIC
    st.session_state[app.TIMEZONE_STATE_KEY] = "America/New_York"

    app.reverse_locations(
        origin_state=origin,
        destination_state=destination,
        settings=make_settings(default_timezone="UTC"),
        browser_timezone="America/Chicago",
        finder=StaticTimezoneFinder(),
    )

    assert st.session_state[app.ORIGIN_PICKER_STATE_KEY].confirmed_location == (
        destination.confirmed_location
    )
    assert st.session_state[app.TIMEZONE_STATE_KEY] == "America/Los_Angeles"
    assert st.session_state[app.TIMEZONE_SOURCE_STATE_KEY] == "origin"


def test_invalid_browser_timezone_uses_configured_fallback() -> None:
    resolved = resolve_automatic_timezone(
        origin=None,
        browser_timezone="Invalid/Zone",
        configured_default_timezone="Europe/Madrid",
        finder=InvalidTimezoneFinder(),
    )

    assert resolved.name == "Europe/Madrid"
    assert resolved.source == "default"
