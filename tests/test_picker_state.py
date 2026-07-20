from __future__ import annotations

from datetime import date, time

from src.models import (
    AddressSuggestion,
    Coordinates,
    GeocodeResult,
    LocationPickerState,
    SelectedLocation,
)
from src.pickers import (
    apply_picker_search_result,
    apply_picker_suggestion_result,
    build_analysis_request,
    can_generate_routes,
    confirm_picker_location,
    create_picker_state,
)
from src.utils import format_coordinates_label


def test_search_result_sets_provisional_result_and_clears_confirmation() -> None:
    default_center = Coordinates(lat=40.4168, lon=-3.7038)
    previous = LocationPickerState(
        query_text="Madrid, Spain",
        provisional_result=None,
        map_center=default_center,
        confirmed_location=SelectedLocation(
            coordinates=default_center,
            label="Madrid",
            label_source="reverse_geocode",
        ),
        map_revision=2,
    )
    geocoded = GeocodeResult(
        label="Gran Via, Madrid, Spain",
        coordinates=Coordinates(lat=40.4203, lon=-3.7058),
    )

    updated = apply_picker_search_result(previous, "Gran Via, Madrid", geocoded)

    assert updated.query_text == "Gran Via, Madrid"
    assert updated.provisional_result == geocoded
    assert updated.map_center == geocoded.coordinates
    assert updated.confirmed_location is None
    assert updated.map_revision == 3


def test_search_without_result_keeps_state_coherent() -> None:
    default_center = Coordinates(lat=40.4168, lon=-3.7038)
    state = create_picker_state("Madrid, Spain", default_center)

    updated = apply_picker_search_result(state, "Unknown place", None)

    assert updated.query_text == "Unknown place"
    assert updated.provisional_result is None
    assert updated.map_center == default_center
    assert updated.confirmed_location is None
    assert updated.map_revision == 1


def test_suggestion_selection_sets_provisional_result_and_keeps_provider_id() -> None:
    default_center = Coordinates(lat=40.4168, lon=-3.7038)
    previous = LocationPickerState(
        query_text="Madrid, Spain",
        provisional_result=None,
        map_center=default_center,
        confirmed_location=SelectedLocation(
            coordinates=default_center,
            label="Madrid",
            label_source="reverse_geocode",
        ),
        map_revision=2,
    )
    suggestion = AddressSuggestion(
        label="Gran Via, Madrid, Spain",
        coordinates=Coordinates(lat=40.4203, lon=-3.7058),
        provider_id="W:123",
    )

    updated = apply_picker_suggestion_result(previous, suggestion)

    assert updated.query_text == suggestion.label
    assert updated.provisional_result == GeocodeResult(
        label=suggestion.label,
        coordinates=suggestion.coordinates,
        provider_id="W:123",
    )
    assert updated.map_center == suggestion.coordinates
    assert updated.confirmed_location is None
    assert updated.map_revision == 3


def test_confirm_picker_location_prefers_reverse_geocoded_label() -> None:
    default_center = Coordinates(lat=40.4168, lon=-3.7038)
    state = create_picker_state("Madrid, Spain", default_center)
    clicked = Coordinates(lat=40.4170, lon=-3.7036)
    reverse_result = GeocodeResult(
        label="Puerta del Sol, Madrid, Spain", coordinates=clicked
    )

    updated = confirm_picker_location(state, clicked, reverse_result)

    assert updated.confirmed_location is not None
    assert updated.confirmed_location.label == "Puerta del Sol, Madrid, Spain"
    assert updated.confirmed_location.label_source == "reverse_geocode"
    assert updated.query_text == "Puerta del Sol, Madrid, Spain"
    assert updated.map_center == clicked
    assert updated.map_revision == 1


def test_confirm_picker_location_falls_back_to_query_or_coordinates() -> None:
    default_center = Coordinates(lat=40.4168, lon=-3.7038)
    state = create_picker_state("Zona centro Madrid", default_center)
    clicked = Coordinates(lat=40.4170, lon=-3.7036)

    updated = confirm_picker_location(state, clicked, None)

    assert updated.confirmed_location is not None
    assert updated.confirmed_location.label == "Zona centro Madrid"
    assert updated.confirmed_location.label_source == "query_text"
    assert updated.query_text == "Zona centro Madrid"
    assert updated.map_revision == 1
    assert format_coordinates_label(clicked) == "40.41700, -3.70360"


def test_confirm_picker_location_uses_typed_query_when_reverse_geocoding_fails() -> (
    None
):
    default_center = Coordinates(lat=40.4168, lon=-3.7038)
    state = LocationPickerState(
        query_text="Calle Princesa 1, Madrid",
        provisional_result=None,
        map_center=default_center,
        confirmed_location=None,
        map_revision=2,
    )
    clicked = Coordinates(lat=40.4240, lon=-3.7142)

    updated = confirm_picker_location(state, clicked, None)

    assert updated.confirmed_location is not None
    assert updated.confirmed_location.label == "Calle Princesa 1, Madrid"
    assert updated.query_text == "Calle Princesa 1, Madrid"
    assert updated.map_revision == 3


def test_generate_routes_requires_both_confirmed_points() -> None:
    center = Coordinates(lat=40.4168, lon=-3.7038)
    origin = create_picker_state("Madrid, Spain", center)
    destination = create_picker_state("Burgos, Spain", center)

    assert can_generate_routes(origin, destination) is False

    origin = confirm_picker_location(origin, center, None)
    assert can_generate_routes(origin, destination) is False

    destination = confirm_picker_location(
        destination, Coordinates(lat=42.3439, lon=-3.6969), None
    )
    assert can_generate_routes(origin, destination) is True


def test_build_analysis_request_uses_confirmed_locations() -> None:
    origin = confirm_picker_location(
        create_picker_state("Madrid, Spain", Coordinates(lat=40.4168, lon=-3.7038)),
        Coordinates(lat=40.4168, lon=-3.7038),
        None,
    )
    destination = confirm_picker_location(
        create_picker_state("Burgos, Spain", Coordinates(lat=42.3439, lon=-3.6969)),
        Coordinates(lat=42.3439, lon=-3.6969),
        None,
    )

    request = build_analysis_request(
        origin,
        destination,
        trip_date=date(2026, 3, 18),
        trip_time=time(9, 0),
        timezone_name="Europe/Madrid",
    )

    assert request is not None
    assert request.origin.coordinates.lat == 40.4168
    assert request.destination.coordinates.lat == 42.3439
    assert request.timezone_name == "Europe/Madrid"
