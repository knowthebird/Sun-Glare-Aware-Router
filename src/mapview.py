from __future__ import annotations

import folium
from branca.element import Element, Figure
from typing import cast

from src.i18n import t
from src.models import (
    Coordinates,
    LocationPickerState,
    RouteEvaluation,
    RouteSegmentRisk,
)

ROUTE_COLORS = [
    "#2DD4BF",
    "#60A5FA",
    "#F87171",
    "#C084FC",
    "#FBBF24",
    "#22D3EE",
]


def _to_lat_lon_pairs(points: list[Coordinates]) -> list[tuple[float, float]]:
    return [(point.lat, point.lon) for point in points]


def _peak_segment(segment_risks: list[RouteSegmentRisk]) -> RouteSegmentRisk | None:
    if not segment_risks:
        return None
    return max(segment_risks, key=lambda item: item.glare_score)


def _install_ctrl_wheel_zoom(route_map: folium.Map) -> None:
    map_name = route_map.get_name()
    root = cast(Figure, route_map.get_root())
    root.script.add_child(
        Element(
            f"""
            <script>
            (function() {{
                const mapInstance = {map_name};
                mapInstance.scrollWheelZoom.disable();
                const container = mapInstance.getContainer();
                container.addEventListener("wheel", function(event) {{
                    if (event.ctrlKey) {{
                        mapInstance.scrollWheelZoom.enable();
                    }} else {{
                        mapInstance.scrollWheelZoom.disable();
                    }}
                }}, {{ passive: true }});
                container.addEventListener("mouseleave", function() {{
                    mapInstance.scrollWheelZoom.disable();
                }});
            }})();
            </script>
            """
        )
    )


def _route_display_name(
    evaluation: RouteEvaluation, fallback_index: int, language: str
) -> str:
    route_index = evaluation.route.metadata.get("route_index")
    if isinstance(route_index, int) and route_index > 0:
        return t(language, "common.option", index=route_index)
    return t(language, "common.option", index=fallback_index)


def build_picker_map(
    picker_state: LocationPickerState,
    picker_kind: str,
    language: str = "es",
) -> folium.Map:
    route_map = folium.Map(
        location=[picker_state.map_center.lat, picker_state.map_center.lon],
        zoom_start=13,
        tiles="OpenStreetMap",
        scroll_wheel_zoom=False,
    )

    provisional_result = picker_state.provisional_result
    if provisional_result is not None:
        folium.Marker(
            [provisional_result.coordinates.lat, provisional_result.coordinates.lon],
            tooltip=t(language, f"map.{picker_kind}_provisional"),
            icon=folium.Icon(color="blue", icon="search"),
        ).add_to(route_map)

    confirmed = picker_state.confirmed_location
    if confirmed is not None:
        folium.Marker(
            [confirmed.coordinates.lat, confirmed.coordinates.lon],
            tooltip=t(language, f"map.{picker_kind}_confirmed"),
            icon=folium.Icon(
                color="green" if picker_kind == "origin" else "red", icon="ok"
            ),
        ).add_to(route_map)

    _install_ctrl_wheel_zoom(route_map)
    return route_map


def build_route_map(
    origin: Coordinates,
    destination: Coordinates,
    evaluations: list[RouteEvaluation],
    recommended_route_id: str | None,
    language: str = "es",
) -> folium.Map:
    map_center = [
        (origin.lat + destination.lat) / 2.0,
        (origin.lon + destination.lon) / 2.0,
    ]
    route_map = folium.Map(
        location=map_center,
        zoom_start=12,
        tiles="OpenStreetMap",
        scroll_wheel_zoom=False,
    )

    folium.Marker(
        [origin.lat, origin.lon],
        tooltip=t(language, "map.origin"),
        icon=folium.Icon(color="green", icon="play"),
    ).add_to(route_map)
    folium.Marker(
        [destination.lat, destination.lon],
        tooltip=t(language, "map.destination"),
        icon=folium.Icon(color="red", icon="flag"),
    ).add_to(route_map)

    bounds: list[tuple[float, float]] = [
        (origin.lat, origin.lon),
        (destination.lat, destination.lon),
    ]
    for index, evaluation in enumerate(evaluations, start=1):
        is_recommended = evaluation.route.route_id == recommended_route_id
        route_name = _route_display_name(evaluation, index, language)
        route_points = _to_lat_lon_pairs(evaluation.route.geometry)
        route_color = ROUTE_COLORS[(index - 1) % len(ROUTE_COLORS)]
        bounds.extend(route_points)
        folium.PolyLine(
            route_points,
            color=route_color,
            weight=7 if is_recommended else 3,
            opacity=0.95 if is_recommended else 0.75,
            dash_array=None if is_recommended else "8 10",
            tooltip=t(
                language,
                "map.route_tooltip",
                route_name=route_name,
                distance_km=evaluation.route.metrics.distance_m / 1000.0,
                risk=evaluation.glare_score,
            ),
        ).add_to(route_map)

        if not is_recommended:
            continue

        peak_segment = _peak_segment(evaluation.segment_risks)
        if peak_segment is not None:
            folium.PolyLine(
                _to_lat_lon_pairs(
                    [peak_segment.start_coordinates, peak_segment.end_coordinates]
                ),
                color="#F97316",
                weight=8,
                opacity=0.95,
                tooltip=t(
                    language,
                    "map.high_risk_segment",
                    score=peak_segment.glare_score,
                ),
            ).add_to(route_map)

        if evaluation.peak_risk_coordinates is not None:
            folium.CircleMarker(
                [
                    evaluation.peak_risk_coordinates.lat,
                    evaluation.peak_risk_coordinates.lon,
                ],
                radius=7,
                color="#F59E0B",
                fill=True,
                fill_color="#FBBF24",
                fill_opacity=0.95,
                tooltip=t(language, "map.peak_risk"),
            ).add_to(route_map)

    route_map.fit_bounds(bounds)
    _install_ctrl_wheel_zoom(route_map)
    return route_map
