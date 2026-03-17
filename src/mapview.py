from __future__ import annotations

import folium

from src.models import Coordinates, LocationPickerState, RouteEvaluation


def _to_lat_lon_pairs(points: list[Coordinates]) -> list[tuple[float, float]]:
    return [(point.lat, point.lon) for point in points]


def build_picker_map(
    picker_state: LocationPickerState,
    picker_kind: str,
) -> folium.Map:
    route_map = folium.Map(
        location=[picker_state.map_center.lat, picker_state.map_center.lon],
        zoom_start=13,
        tiles="OpenStreetMap",
    )

    provisional_result = picker_state.provisional_result
    if provisional_result is not None:
        folium.Marker(
            [provisional_result.coordinates.lat, provisional_result.coordinates.lon],
            tooltip=f"{picker_kind.capitalize()} provisional",
            icon=folium.Icon(color="blue", icon="search"),
        ).add_to(route_map)

    confirmed = picker_state.confirmed_location
    if confirmed is not None:
        folium.Marker(
            [confirmed.coordinates.lat, confirmed.coordinates.lon],
            tooltip=f"{picker_kind.capitalize()} confirmado",
            icon=folium.Icon(color="green" if picker_kind == "origin" else "red", icon="ok"),
        ).add_to(route_map)

    return route_map


def build_route_map(
    origin: Coordinates,
    destination: Coordinates,
    evaluations: list[RouteEvaluation],
    recommended_route_id: str | None,
) -> folium.Map:
    map_center = [(origin.lat + destination.lat) / 2.0, (origin.lon + destination.lon) / 2.0]
    route_map = folium.Map(location=map_center, zoom_start=12, tiles="OpenStreetMap")

    folium.Marker(
        [origin.lat, origin.lon],
        tooltip="Origin",
        icon=folium.Icon(color="green", icon="play"),
    ).add_to(route_map)
    folium.Marker(
        [destination.lat, destination.lon],
        tooltip="Destination",
        icon=folium.Icon(color="red", icon="flag"),
    ).add_to(route_map)

    bounds: list[tuple[float, float]] = [(origin.lat, origin.lon), (destination.lat, destination.lon)]
    for evaluation in evaluations:
        is_recommended = evaluation.route.route_id == recommended_route_id
        route_points = _to_lat_lon_pairs(evaluation.route.geometry)
        bounds.extend(route_points)
        folium.PolyLine(
            route_points,
            color="#0F766E" if is_recommended else "#94A3B8",
            weight=6 if is_recommended else 4,
            opacity=0.95 if is_recommended else 0.65,
            tooltip=(
                f"{evaluation.route.route_id}: "
                f"{evaluation.route.metrics.distance_m / 1000.0:.1f} km, "
                f"glare {evaluation.glare_score:.1f}"
            ),
        ).add_to(route_map)

    route_map.fit_bounds(bounds)
    return route_map
