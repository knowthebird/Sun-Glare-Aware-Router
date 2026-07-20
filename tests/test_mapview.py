from __future__ import annotations

from datetime import datetime
import re

import app
from src.mapview import build_route_map, glare_level_for_score
from src.models import (
    Coordinates,
    LocationPickerState,
    Route,
    RouteEvaluation,
    RouteHighGlareStretch,
    RouteMetrics,
    RouteSegmentRisk,
    SunPosition,
)


def test_build_route_map_renders_segment_glare_categories_and_legend() -> None:
    origin = Coordinates(lat=40.4168, lon=-3.7038)
    point_one = Coordinates(lat=40.9000, lon=-3.7000)
    point_two = Coordinates(lat=41.2000, lon=-3.7100)
    point_three = Coordinates(lat=41.6000, lon=-3.7200)
    point_four = Coordinates(lat=42.0000, lon=-3.7100)
    destination = Coordinates(lat=42.3439, lon=-3.6969)
    route = Route(
        route_id="route-1",
        geometry=[origin, point_one, point_two, point_three, point_four, destination],
        metrics=RouteMetrics(distance_m=240000.0, duration_s=9000.0),
    )
    segment_points = [
        (origin, point_one, 0.0),
        (point_one, point_two, 12.0),
        (point_two, point_three, 25.0),
        (point_three, point_four, 42.0),
        (point_four, destination, 72.0),
    ]
    segment_risks = [
        RouteSegmentRisk(
            start_coordinates=start,
            end_coordinates=end,
            midpoint_coordinates=Coordinates(
                lat=(start.lat + end.lat) / 2,
                lon=(start.lon + end.lon) / 2,
            ),
            segment_length_m=48000.0,
            estimated_duration_s=1800.0,
            start_offset_s=index * 1800.0,
            midpoint_offset_s=(index * 1800.0) + 900.0,
            bearing_deg=0.0,
            angle_difference_deg=15.0 + index,
            sun_position=SunPosition(
                azimuth_deg=115.0,
                elevation_deg=12.0 + index,
            ),
            glare_score=score,
        )
        for index, (start, end, score) in enumerate(segment_points)
    ]
    evaluation = RouteEvaluation(
        route=route,
        glare_score=24.5,
        total_length_m=240000.0,
        peak_segment_score=72.0,
        aligned_distance_m=60000.0,
        dominant_bearing_deg=15.0,
        high_risk_distance_m=42000.0,
        high_risk_duration_s=1500.0,
        peak_risk_time_offset_min=38.0,
        peak_risk_coordinates=point_four,
        peak_glare_segment=segment_risks[-1],
        peak_glare_coordinates=point_four,
        peak_glare_score=72.0,
        peak_glare_category="severe",
        longest_high_glare_stretch=RouteHighGlareStretch(
            start_coordinates=point_three,
            end_coordinates=destination,
            start_offset_s=5400.0,
            end_offset_s=9000.0,
            duration_s=3600.0,
            distance_m=96000.0,
            start_distance_m=144000.0,
            end_distance_m=240000.0,
            max_glare_score=72.0,
            peak_segment=segment_risks[-1],
            segments=segment_risks[-2:],
        ),
        any_high_risk_segments=True,
        segment_risks=segment_risks,
    )

    route_map = build_route_map(
        origin=origin,
        destination=destination,
        evaluations=[evaluation],
        recommended_route_id="route-1",
        language="en",
        trip_start_moment=datetime.fromisoformat("2026-03-18T07:00:00-04:00"),
    )

    rendered = route_map.get_root().render()

    assert "Glare level" in rendered
    assert "Peak glare" in rendered
    assert "Longest high-glare stretch" in rendered
    assert (
        "This is the strongest instantaneous glare predicted along the route."
        in rendered
    )
    for label in ["Minimal", "Low", "Moderate", "High", "Severe"]:
        assert label in rendered
    for color in ["#2563EB", "#14B8A6", "#FACC15", "#F97316", "#DC2626"]:
        assert color in rendered
    assert "Estimated time:" in rendered
    assert "Sun elevation:" in rendered
    assert "Sun azimuth" in rendered
    assert "Vehicle heading" in rendered
    assert "Sun-route difference:" in rendered
    assert re.search(r"07:1[0-9]", rendered)


def test_build_route_map_shows_multi_day_segment_timestamps() -> None:
    origin = Coordinates(lat=40.0, lon=-74.0)
    midpoint = Coordinates(lat=39.0, lon=-100.0)
    destination = Coordinates(lat=37.0, lon=-122.0)
    route = Route(
        route_id="route-1",
        geometry=[origin, midpoint, destination],
        metrics=RouteMetrics(distance_m=4_500_000.0, duration_s=50 * 60 * 60),
    )
    segment_risks = [
        RouteSegmentRisk(
            start_coordinates=origin,
            end_coordinates=midpoint,
            midpoint_coordinates=Coordinates(lat=39.5, lon=-87.0),
            segment_length_m=2_250_000.0,
            estimated_duration_s=25 * 60 * 60,
            start_offset_s=0.0,
            midpoint_offset_s=12.5 * 60 * 60,
            bearing_deg=270.0,
            angle_difference_deg=20.0,
            sun_position=SunPosition(azimuth_deg=270.0, elevation_deg=10.0),
            glare_score=50.0,
        ),
        RouteSegmentRisk(
            start_coordinates=midpoint,
            end_coordinates=destination,
            midpoint_coordinates=Coordinates(lat=38.0, lon=-111.0),
            segment_length_m=2_250_000.0,
            estimated_duration_s=25 * 60 * 60,
            start_offset_s=25 * 60 * 60,
            midpoint_offset_s=37.5 * 60 * 60,
            bearing_deg=270.0,
            angle_difference_deg=20.0,
            sun_position=SunPosition(azimuth_deg=270.0, elevation_deg=10.0),
            glare_score=50.0,
        ),
    ]
    evaluation = RouteEvaluation(
        route=route,
        glare_score=50.0,
        total_length_m=4_500_000.0,
        peak_segment_score=50.0,
        aligned_distance_m=4_500_000.0,
        peak_glare_segment=segment_risks[1],
        peak_glare_coordinates=segment_risks[1].midpoint_coordinates,
        peak_glare_score=50.0,
        peak_glare_category="high",
        any_high_risk_segments=True,
        segment_risks=segment_risks,
    )

    route_map = build_route_map(
        origin=origin,
        destination=destination,
        evaluations=[evaluation],
        recommended_route_id="route-1",
        language="en",
        trip_start_moment=datetime.fromisoformat("2026-07-19T08:00:00+00:00"),
    )

    rendered = route_map.get_root().render()

    assert "2026-07-19 20:30 UTC" in rendered
    assert "2026-07-20 21:30 UTC" in rendered


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

    assert '"dashArray": "8 10"' in rendered
    assert "#60A5FA" in rendered
    assert "#F8FAFC" in rendered


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
    assert "Glare level" in rendered


def test_build_route_map_labels_peak_honestly_when_no_segment_is_high_risk() -> None:
    origin = Coordinates(lat=40.4168, lon=-3.7038)
    midpoint = Coordinates(lat=41.1, lon=-3.7)
    destination = Coordinates(lat=42.3439, lon=-3.6969)
    route = Route(
        route_id="route-1",
        geometry=[origin, midpoint, destination],
        metrics=RouteMetrics(distance_m=240000.0, duration_s=9000.0),
        metadata={"route_index": 1},
    )
    segment = RouteSegmentRisk(
        start_coordinates=origin,
        end_coordinates=midpoint,
        midpoint_coordinates=Coordinates(lat=40.7584, lon=-3.7019),
        segment_length_m=120000.0,
        estimated_duration_s=4500.0,
        start_offset_s=0.0,
        midpoint_offset_s=2250.0,
        bearing_deg=0.0,
        angle_difference_deg=25.0,
        sun_position=SunPosition(azimuth_deg=25.0, elevation_deg=28.0),
        glare_score=28.0,
    )
    evaluation = RouteEvaluation(
        route=route,
        glare_score=14.0,
        total_length_m=240000.0,
        peak_segment_score=28.0,
        aligned_distance_m=120000.0,
        peak_risk_time_offset_min=37.5,
        peak_risk_distance_m=60000.0,
        peak_risk_coordinates=segment.midpoint_coordinates,
        peak_glare_segment=segment,
        peak_glare_coordinates=segment.midpoint_coordinates,
        peak_glare_score=28.0,
        peak_glare_category="moderate",
        any_high_risk_segments=False,
        segment_risks=[segment],
    )

    route_map = build_route_map(
        origin=origin,
        destination=destination,
        evaluations=[evaluation],
        recommended_route_id="route-1",
        language="en",
    )

    rendered = route_map.get_root().render()

    assert "Highest estimated glare" in rendered
    assert (
        "No route segment reached the high-glare threshold for this trip." in rendered
    )
    assert "Longest high-glare stretch" not in rendered


def test_glare_level_boundaries_are_anchored_to_high_risk_threshold() -> None:
    assert glare_level_for_score(0.0).key == "minimal"
    assert glare_level_for_score(5.0).key == "low"
    assert glare_level_for_score(20.0).key == "moderate"
    assert glare_level_for_score(35.0).key == "high"
    assert glare_level_for_score(65.0).key == "severe"


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


def test_picker_map_factory_returns_fresh_maps_for_interactive_rerenders() -> None:
    state = LocationPickerState(
        query_text="Madrid, Spain",
        provisional_result=None,
        map_center=Coordinates(lat=40.4168, lon=-3.7038),
        confirmed_location=None,
        map_revision=0,
    )

    map_one = app.get_picker_map(
        map_center=state.map_center,
        provisional_result=state.provisional_result,
        confirmed_location=state.confirmed_location,
        picker_kind="origin",
        language="es",
    )
    map_two = app.get_picker_map(
        map_center=state.map_center,
        provisional_result=state.provisional_result,
        confirmed_location=state.confirmed_location,
        picker_kind="origin",
        language="es",
    )

    assert map_one is not map_two
    assert map_one.get_name() != map_two.get_name()
