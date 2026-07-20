from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import html
from typing import cast

import folium
from branca.element import Element, Figure

from src.i18n import t
from src.models import (
    Coordinates,
    LocationPickerState,
    RouteEvaluation,
    RouteHighGlareStretch,
    RouteSegmentRisk,
)
from src.scoring import HIGH_RISK_SEGMENT_THRESHOLD
from src.utils import format_datetime_with_zone, format_elapsed_duration

ROUTE_COLORS = [
    "#2DD4BF",
    "#60A5FA",
    "#F87171",
    "#C084FC",
    "#FBBF24",
    "#22D3EE",
]

HIGH_RISK_SCORE = HIGH_RISK_SEGMENT_THRESHOLD * 100.0


@dataclass(frozen=True)
class GlareLevel:
    key: str
    minimum_score: float
    color: str


GLARE_LEVELS: tuple[GlareLevel, ...] = (
    GlareLevel("minimal", 0.0, "#2563EB"),
    GlareLevel("low", 5.0, "#14B8A6"),
    GlareLevel("moderate", 20.0, "#FACC15"),
    GlareLevel("high", HIGH_RISK_SCORE, "#F97316"),
    GlareLevel("severe", 65.0, "#DC2626"),
)


def _to_lat_lon_pairs(points: list[Coordinates]) -> list[tuple[float, float]]:
    return [(point.lat, point.lon) for point in points]


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


def glare_level_for_score(score: float) -> GlareLevel:
    selected = GLARE_LEVELS[0]
    for level in GLARE_LEVELS:
        if score >= level.minimum_score:
            selected = level
    return selected


def _level_upper_bound(index: int) -> float | None:
    next_index = index + 1
    if next_index >= len(GLARE_LEVELS):
        return None
    return GLARE_LEVELS[next_index].minimum_score


def _format_legend_range(index: int) -> str:
    level = GLARE_LEVELS[index]
    upper_bound = _level_upper_bound(index)
    if upper_bound is None:
        return f"{level.minimum_score:.0f}+"
    if level.minimum_score <= 0.0:
        return f"0-{upper_bound:.0f}"
    return f"{level.minimum_score:.0f}-{upper_bound:.0f}"


def _format_segment_time(
    segment: RouteSegmentRisk,
    trip_start_moment: datetime | None,
    language: str,
) -> str:
    return _format_time_at_offset(
        segment.midpoint_offset_s, trip_start_moment, language
    )


def _format_time_at_offset(
    offset_s: float,
    trip_start_moment: datetime | None,
    language: str,
) -> str:
    if trip_start_moment is None:
        return t(
            language,
            "map.segment_elapsed_time",
            duration=format_elapsed_duration(offset_s),
        )
    if trip_start_moment.tzinfo is None or trip_start_moment.utcoffset() is None:
        segment_time = trip_start_moment + timedelta(seconds=offset_s)
    else:
        segment_time = (
            trip_start_moment.astimezone(UTC) + timedelta(seconds=offset_s)
        ).astimezone(trip_start_moment.tzinfo)
    return format_datetime_with_zone(segment_time)


def _format_duration(duration_s: float) -> str:
    return format_elapsed_duration(duration_s)


def _format_distance(distance_m: float) -> str:
    return f"{distance_m / 1000.0:.1f} km"


def _segment_tooltip(
    segment: RouteSegmentRisk,
    trip_start_moment: datetime | None,
    language: str,
) -> folium.Tooltip:
    level = glare_level_for_score(segment.glare_score)
    return folium.Tooltip(
        t(
            language,
            "map.segment_tooltip",
            level=t(language, f"map.glare_level.{level.key}"),
            score=segment.glare_score,
            time=_format_segment_time(segment, trip_start_moment, language),
            elevation=segment.sun_position.elevation_deg,
            angle=segment.angle_difference_deg,
        ),
        sticky=True,
    )


def _peak_glare_popup(
    evaluation: RouteEvaluation,
    trip_start_moment: datetime | None,
    language: str,
) -> folium.Popup:
    segment = evaluation.peak_glare_segment
    if segment is None:
        return folium.Popup(t(language, "map.no_estimated_glare"), max_width=320)

    level = glare_level_for_score(segment.glare_score)
    heading = (
        t(language, "map.peak_glare")
        if evaluation.any_high_risk_segments
        else t(language, "map.highest_estimated_glare")
    )

    rows = [
        (t(language, "map.popup.score"), f"{segment.glare_score:.1f}/100"),
        (
            t(language, "map.popup.category"),
            t(language, f"map.glare_level.{level.key}"),
        ),
        (
            t(language, "map.popup.time"),
            _format_segment_time(segment, trip_start_moment, language),
        ),
        (
            t(language, "map.popup.sun_elevation"),
            f"{segment.sun_position.elevation_deg:.1f}°",
        ),
        (
            t(language, "map.popup.sun_azimuth"),
            f"{segment.sun_position.azimuth_deg:.1f}°",
        ),
        (t(language, "map.popup.vehicle_heading"), f"{segment.bearing_deg:.1f}°"),
        (
            t(language, "map.popup.angular_difference"),
            f"{segment.angle_difference_deg:.1f}°",
        ),
    ]
    row_html = "".join(
        f"<tr><th>{html.escape(label)}</th><td>{html.escape(value)}</td></tr>"
        for label, value in rows
    )
    explanation_key = (
        "map.peak_glare_explanation"
        if evaluation.any_high_risk_segments
        else "map.highest_estimated_glare_explanation"
    )
    popup_html = f"""
        <div class="sunrouter-map-popup">
            <strong>{html.escape(heading)}</strong>
            <table>{row_html}</table>
            <p>{html.escape(t(language, explanation_key))}</p>
        </div>
    """
    return folium.Popup(popup_html, max_width=360)


def _map_pin_icon(label: str, *, color: str, border_color: str) -> folium.DivIcon:
    return folium.DivIcon(
        icon_size=(190, 32),
        icon_anchor=(14, 28),
        html=f"""
        <div style="display:flex;align-items:center;gap:6px;
                    font:700 12px/1.2 Arial,sans-serif;white-space:nowrap;
                    filter:drop-shadow(0 2px 6px rgba(15,23,42,.35));">
            <span style="box-sizing:border-box;width:18px;height:18px;border-radius:999px;
                         background:{html.escape(color)};border:3px solid #ffffff;
                         outline:2px solid {html.escape(border_color)};display:inline-block;"></span>
            <span style="background:#ffffff;color:#0f172a;border:1px solid rgba(15,23,42,.24);
                         border-radius:6px;padding:4px 6px;">
                {html.escape(label)}
            </span>
        </div>
        """,
    )


def _stretch_tooltip(
    stretch: RouteHighGlareStretch,
    trip_start_moment: datetime | None,
    language: str,
) -> folium.Tooltip:
    return folium.Tooltip(
        t(
            language,
            "map.longest_stretch_tooltip",
            duration=_format_duration(stretch.duration_s),
            distance=_format_distance(stretch.distance_m),
            start=_format_time_at_offset(
                stretch.start_offset_s,
                trip_start_moment,
                language,
            ),
            end=_format_time_at_offset(
                stretch.end_offset_s, trip_start_moment, language
            ),
            score=stretch.max_glare_score,
        ),
        sticky=True,
    )


def _add_longest_stretch_highlight(
    route_map: folium.Map,
    evaluation: RouteEvaluation,
    language: str,
    trip_start_moment: datetime | None,
) -> None:
    stretch = evaluation.longest_high_glare_stretch
    if stretch is None or not stretch.segments:
        return

    stretch_points = [stretch.segments[0].start_coordinates]
    stretch_points.extend(segment.end_coordinates for segment in stretch.segments)
    folium.PolyLine(
        _to_lat_lon_pairs(stretch_points),
        color="#111827",
        weight=13,
        opacity=0.42,
        dash_array="5 8",
        line_cap="round",
        line_join="round",
        tooltip=_stretch_tooltip(stretch, trip_start_moment, language),
    ).add_to(route_map)

    if len(stretch.segments) > 1:
        label_segment = stretch.peak_segment
        folium.Marker(
            [
                label_segment.midpoint_coordinates.lat,
                label_segment.midpoint_coordinates.lon,
            ],
            icon=folium.DivIcon(
                icon_size=(190, 26),
                icon_anchor=(10, 24),
                html=f"""
                <div style="background:#111827;color:#ffffff;border:1px solid #ffffff;
                            border-radius:6px;font:700 11px/1.2 Arial,sans-serif;
                            padding:4px 6px;white-space:nowrap;
                            box-shadow:0 2px 8px rgba(15,23,42,.28);">
                    {html.escape(t(language, "map.longest_high_glare_stretch"))}
                </div>
                """,
            ),
            tooltip=_stretch_tooltip(stretch, trip_start_moment, language),
        ).add_to(route_map)


def _add_peak_glare_marker(
    route_map: folium.Map,
    evaluation: RouteEvaluation,
    language: str,
    trip_start_moment: datetime | None,
) -> None:
    segment = evaluation.peak_glare_segment
    coordinates = evaluation.peak_glare_coordinates
    if segment is None or coordinates is None:
        return

    marker_label = (
        t(language, "map.peak_glare")
        if evaluation.any_high_risk_segments
        else t(language, "map.highest_estimated_glare")
    )
    folium.Marker(
        [coordinates.lat, coordinates.lon],
        icon=_map_pin_icon(
            marker_label,
            color="#F97316" if evaluation.any_high_risk_segments else "#FACC15",
            border_color="#7C2D12",
        ),
        tooltip=marker_label,
        popup=_peak_glare_popup(evaluation, trip_start_moment, language),
    ).add_to(route_map)


def _install_no_high_glare_message(route_map: folium.Map, language: str) -> None:
    root = cast(Figure, route_map.get_root())
    root.html.add_child(
        Element(
            f"""
            <div class="sunrouter-no-high-glare">
                {html.escape(t(language, "map.no_high_glare_threshold"))}
            </div>
            <style>
            .sunrouter-no-high-glare {{
                position: fixed;
                right: 18px;
                bottom: 24px;
                z-index: 9999;
                background: rgba(255, 255, 255, 0.94);
                border: 1px solid rgba(15, 23, 42, 0.16);
                border-radius: 8px;
                box-shadow: 0 8px 18px rgba(15, 23, 42, 0.18);
                color: #0f172a;
                font: 12px/1.35 Arial, sans-serif;
                max-width: 260px;
                padding: 9px 10px;
            }}
            </style>
            """
        )
    )


def _install_glare_legend(route_map: folium.Map, language: str) -> None:
    rows = []
    for index, level in enumerate(GLARE_LEVELS):
        label = t(language, f"map.glare_level.{level.key}")
        rows.append(
            f"""
            <div class="sunrouter-glare-legend-row">
                <span class="sunrouter-glare-swatch" style="background:{level.color};"></span>
                <span>{html.escape(label)} ({html.escape(_format_legend_range(index))})</span>
            </div>
            """
        )

    root = cast(Figure, route_map.get_root())
    root.html.add_child(
        Element(
            f"""
            <div class="sunrouter-glare-legend" aria-label="{html.escape(t(language, "map.legend_title"))}">
                <div class="sunrouter-glare-legend-title">{html.escape(t(language, "map.legend_title"))}</div>
                {"".join(rows)}
            </div>
            <style>
            .sunrouter-glare-legend {{
                position: fixed;
                left: 18px;
                bottom: 24px;
                z-index: 9999;
                background: rgba(255, 255, 255, 0.94);
                border: 1px solid rgba(15, 23, 42, 0.16);
                border-radius: 8px;
                box-shadow: 0 8px 18px rgba(15, 23, 42, 0.22);
                color: #0f172a;
                font: 12px/1.35 Arial, sans-serif;
                min-width: 150px;
                padding: 9px 10px;
            }}
            .sunrouter-glare-legend-title {{
                font-weight: 700;
                margin-bottom: 6px;
            }}
            .sunrouter-glare-legend-row {{
                align-items: center;
                display: flex;
                gap: 7px;
                margin: 4px 0;
                white-space: nowrap;
            }}
            .sunrouter-glare-swatch {{
                border: 1px solid rgba(15, 23, 42, 0.22);
                border-radius: 999px;
                display: inline-block;
                height: 11px;
                width: 22px;
            }}
            </style>
            """
        )
    )


def _add_selected_route_segments(
    route_map: folium.Map,
    evaluation: RouteEvaluation,
    route_points: list[tuple[float, float]],
    route_name: str,
    language: str,
    trip_start_moment: datetime | None,
) -> None:
    folium.PolyLine(
        route_points,
        color="#F8FAFC",
        weight=9,
        opacity=0.88,
        line_cap="round",
        line_join="round",
        tooltip=t(
            language,
            "map.route_tooltip",
            route_name=route_name,
            distance_km=evaluation.route.metrics.distance_m / 1000.0,
            risk=evaluation.glare_score,
        ),
    ).add_to(route_map)

    _add_longest_stretch_highlight(
        route_map,
        evaluation,
        language,
        trip_start_moment,
    )

    for segment in evaluation.segment_risks:
        level = glare_level_for_score(segment.glare_score)
        folium.PolyLine(
            _to_lat_lon_pairs([segment.start_coordinates, segment.end_coordinates]),
            color=level.color,
            weight=6,
            opacity=0.96,
            line_cap="round",
            line_join="round",
            tooltip=_segment_tooltip(segment, trip_start_moment, language),
        ).add_to(route_map)

    if not evaluation.segment_risks:
        folium.PolyLine(
            route_points,
            color=glare_level_for_score(evaluation.glare_score).color,
            weight=6,
            opacity=0.96,
            line_cap="round",
            line_join="round",
            tooltip=t(
                language,
                "map.route_tooltip",
                route_name=route_name,
                distance_km=evaluation.route.metrics.distance_m / 1000.0,
                risk=evaluation.glare_score,
            ),
        ).add_to(route_map)


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
    trip_start_moment: datetime | None = None,
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
        if is_recommended:
            _add_selected_route_segments(
                route_map,
                evaluation,
                route_points,
                route_name,
                language,
                trip_start_moment,
            )
        else:
            folium.PolyLine(
                route_points,
                color=route_color,
                weight=3,
                opacity=0.65,
                dash_array="8 10",
                line_cap="round",
                line_join="round",
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

        _install_glare_legend(route_map, language)
        if not evaluation.any_high_risk_segments:
            _install_no_high_glare_message(route_map, language)
        _add_peak_glare_marker(
            route_map,
            evaluation,
            language,
            trip_start_moment,
        )

    route_map.fit_bounds(bounds)
    _install_ctrl_wheel_zoom(route_map)
    return route_map
