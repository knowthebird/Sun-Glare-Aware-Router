from __future__ import annotations

from src.mapview import build_route_map
from src.models import (
    Coordinates,
    Route,
    RouteEvaluation,
    RouteMetrics,
    RouteSegmentRisk,
    SunPosition,
)


def test_build_route_map_highlights_peak_risk_segment() -> None:
    origin = Coordinates(lat=40.4168, lon=-3.7038)
    midpoint = Coordinates(lat=40.9000, lon=-3.7000)
    destination = Coordinates(lat=42.3439, lon=-3.6969)
    route = Route(
        route_id="route-1",
        geometry=[origin, midpoint, destination],
        metrics=RouteMetrics(distance_m=240000.0, duration_s=9000.0),
    )
    evaluation = RouteEvaluation(
        route=route,
        glare_score=24.5,
        total_length_m=240000.0,
        peak_segment_score=310.0,
        aligned_distance_m=60000.0,
        dominant_bearing_deg=15.0,
        high_risk_distance_m=42000.0,
        high_risk_duration_s=1500.0,
        peak_risk_time_offset_min=38.0,
        peak_risk_coordinates=midpoint,
        segment_risks=[
            RouteSegmentRisk(
                start_coordinates=origin,
                end_coordinates=midpoint,
                midpoint_coordinates=Coordinates(lat=40.6584, lon=-3.7019),
                segment_length_m=120000.0,
                estimated_duration_s=4500.0,
                start_offset_s=0.0,
                midpoint_offset_s=2250.0,
                bearing_deg=0.0,
                angle_difference_deg=15.0,
                sun_position=SunPosition(azimuth_deg=115.0, elevation_deg=12.0),
                glare_score=62.0,
            ),
            RouteSegmentRisk(
                start_coordinates=midpoint,
                end_coordinates=destination,
                midpoint_coordinates=Coordinates(lat=41.6219, lon=-3.69845),
                segment_length_m=120000.0,
                estimated_duration_s=4500.0,
                start_offset_s=4500.0,
                midpoint_offset_s=6750.0,
                bearing_deg=0.0,
                angle_difference_deg=55.0,
                sun_position=SunPosition(azimuth_deg=130.0, elevation_deg=20.0),
                glare_score=18.0,
            ),
        ],
    )

    route_map = build_route_map(
        origin=origin,
        destination=destination,
        evaluations=[evaluation],
        recommended_route_id="route-1",
    )

    rendered = route_map.get_root().render()

    assert "Pico de riesgo" in rendered
    assert "Tramo de mayor riesgo" in rendered


def test_build_route_map_labels_multiple_options() -> None:
    origin = Coordinates(lat=40.4168, lon=-3.7038)
    destination = Coordinates(lat=42.3439, lon=-3.6969)
    route_one = Route(
        route_id="route-1",
        geometry=[origin, Coordinates(lat=41.1, lon=-3.7), destination],
        metrics=RouteMetrics(distance_m=240000.0, duration_s=9000.0),
        metadata={"route_index": 1},
    )
    route_two = Route(
        route_id="route-2",
        geometry=[origin, Coordinates(lat=41.2, lon=-3.8), destination],
        metrics=RouteMetrics(distance_m=245000.0, duration_s=9100.0),
        metadata={"route_index": 2},
    )
    evaluation_one = RouteEvaluation(
        route=route_one,
        glare_score=24.5,
        total_length_m=240000.0,
        peak_segment_score=310.0,
        aligned_distance_m=60000.0,
    )
    evaluation_two = RouteEvaluation(
        route=route_two,
        glare_score=30.0,
        total_length_m=245000.0,
        peak_segment_score=350.0,
        aligned_distance_m=70000.0,
    )

    route_map = build_route_map(
        origin=origin,
        destination=destination,
        evaluations=[evaluation_one, evaluation_two],
        recommended_route_id="route-1",
    )

    rendered = route_map.get_root().render()

    assert "Opción 1" in rendered
    assert "Opción 2" in rendered


def test_build_route_map_uses_distinct_styles_for_recommended_and_alternatives() -> (
    None
):
    origin = Coordinates(lat=40.4168, lon=-3.7038)
    destination = Coordinates(lat=42.3439, lon=-3.6969)
    route_one = Route(
        route_id="route-1",
        geometry=[origin, Coordinates(lat=41.1, lon=-3.7), destination],
        metrics=RouteMetrics(distance_m=240000.0, duration_s=9000.0),
        metadata={"route_index": 1},
    )
    route_two = Route(
        route_id="route-2",
        geometry=[origin, Coordinates(lat=41.2, lon=-3.8), destination],
        metrics=RouteMetrics(distance_m=245000.0, duration_s=9100.0),
        metadata={"route_index": 2},
    )
    evaluation_one = RouteEvaluation(
        route=route_one,
        glare_score=24.5,
        total_length_m=240000.0,
        peak_segment_score=310.0,
        aligned_distance_m=60000.0,
    )
    evaluation_two = RouteEvaluation(
        route=route_two,
        glare_score=30.0,
        total_length_m=245000.0,
        peak_segment_score=350.0,
        aligned_distance_m=70000.0,
    )

    route_map = build_route_map(
        origin=origin,
        destination=destination,
        evaluations=[evaluation_one, evaluation_two],
        recommended_route_id="route-1",
    )

    rendered = route_map.get_root().render()

    assert '"weight": 7' in rendered
    assert '"weight": 3' in rendered
    assert '"dashArray": "8 10"' in rendered
    assert "#2DD4BF" in rendered


def test_build_route_map_can_render_english_labels() -> None:
    origin = Coordinates(lat=40.4168, lon=-3.7038)
    destination = Coordinates(lat=42.3439, lon=-3.6969)
    route = Route(
        route_id="route-1",
        geometry=[origin, Coordinates(lat=41.1, lon=-3.7), destination],
        metrics=RouteMetrics(distance_m=240000.0, duration_s=9000.0),
        metadata={"route_index": 1},
    )
    evaluation = RouteEvaluation(
        route=route,
        glare_score=24.5,
        total_length_m=240000.0,
        peak_segment_score=310.0,
        aligned_distance_m=60000.0,
    )

    route_map = build_route_map(
        origin=origin,
        destination=destination,
        evaluations=[evaluation],
        recommended_route_id="route-1",
        language="en",
    )

    rendered = route_map.get_root().render()

    assert "Origin" in rendered
    assert "Destination" in rendered
    assert "Option 1" in rendered


def test_build_route_map_requires_ctrl_for_mousewheel_zoom() -> None:
    origin = Coordinates(lat=40.4168, lon=-3.7038)
    destination = Coordinates(lat=42.3439, lon=-3.6969)
    route = Route(
        route_id="route-1",
        geometry=[origin, Coordinates(lat=41.1, lon=-3.7), destination],
        metrics=RouteMetrics(distance_m=240000.0, duration_s=9000.0),
        metadata={"route_index": 1},
    )
    evaluation = RouteEvaluation(
        route=route,
        glare_score=24.5,
        total_length_m=240000.0,
        peak_segment_score=310.0,
        aligned_distance_m=60000.0,
    )

    route_map = build_route_map(
        origin=origin,
        destination=destination,
        evaluations=[evaluation],
        recommended_route_id="route-1",
    )

    rendered = route_map.get_root().render()

    assert '"scrollWheelZoom": false' in rendered
    assert "event.ctrlKey" in rendered
