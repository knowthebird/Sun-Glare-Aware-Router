from __future__ import annotations

from datetime import date, time

from src.models import (
    AnalysisRequest,
    Coordinates,
    GeocodeResult,
    LocationPickerState,
    SelectedLocation,
)
from src.solar import resolve_local_datetime
from src.utils import format_coordinates_label


def create_picker_state(
    default_query: str, default_center: Coordinates
) -> LocationPickerState:
    return LocationPickerState(
        query_text=default_query,
        provisional_result=None,
        map_center=default_center,
        confirmed_location=None,
        map_revision=0,
    )


def apply_picker_search_result(
    state: LocationPickerState,
    query_text: str,
    geocoded_result: GeocodeResult | None,
) -> LocationPickerState:
    return LocationPickerState(
        query_text=query_text,
        provisional_result=geocoded_result,
        map_center=geocoded_result.coordinates
        if geocoded_result is not None
        else state.map_center,
        confirmed_location=None,
        map_revision=state.map_revision + 1,
    )


def confirm_picker_location(
    state: LocationPickerState,
    clicked_coordinates: Coordinates,
    reverse_result: GeocodeResult | None,
) -> LocationPickerState:
    if reverse_result is not None:
        confirmed_location = SelectedLocation(
            coordinates=clicked_coordinates,
            label=reverse_result.label,
            label_source="reverse_geocode",
        )
    elif state.query_text.strip():
        confirmed_location = SelectedLocation(
            coordinates=clicked_coordinates,
            label=state.query_text.strip(),
            label_source="query_text",
        )
    else:
        confirmed_location = SelectedLocation(
            coordinates=clicked_coordinates,
            label=format_coordinates_label(clicked_coordinates),
            label_source="coordinates",
        )

    return LocationPickerState(
        query_text=confirmed_location.label,
        provisional_result=state.provisional_result,
        map_center=clicked_coordinates,
        confirmed_location=confirmed_location,
        map_revision=state.map_revision + 1,
    )


def can_generate_routes(
    origin: LocationPickerState, destination: LocationPickerState
) -> bool:
    return (
        origin.confirmed_location is not None
        and destination.confirmed_location is not None
    )


def build_analysis_request(
    origin: LocationPickerState,
    destination: LocationPickerState,
    trip_date: date,
    trip_time: time,
    timezone_name: str,
) -> AnalysisRequest | None:
    if origin.confirmed_location is None or destination.confirmed_location is None:
        return None

    return AnalysisRequest(
        origin=origin.confirmed_location,
        destination=destination.confirmed_location,
        trip_moment=resolve_local_datetime(trip_date, trip_time, timezone_name),
        timezone_name=timezone_name,
    )
