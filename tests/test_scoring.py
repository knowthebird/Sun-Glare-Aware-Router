from src.models import Coordinates, Route, RouteMetrics, SunPosition
from src.scoring import evaluate_route, glare_alignment_factor, rank_routes


def make_route(name: str, geometry: list[Coordinates]) -> Route:
    return Route(
        route_id=name,
        geometry=geometry,
        metrics=RouteMetrics(distance_m=1000.0, duration_s=600.0),
    )


def test_glare_alignment_factor_favors_sun_facing_segments() -> None:
    aligned = glare_alignment_factor(0.0)
    perpendicular = glare_alignment_factor(90.0)
    opposite = glare_alignment_factor(180.0)

    assert aligned == 1.0
    assert 0.0 < perpendicular < aligned
    assert opposite == 0.0


def test_evaluate_route_returns_zero_glare_at_night() -> None:
    route = make_route(
        "eastbound",
        [Coordinates(lat=0.0, lon=0.0), Coordinates(lat=0.0, lon=0.01)],
    )
    sun = SunPosition(azimuth_deg=90.0, elevation_deg=-5.0)

    result = evaluate_route(route, sun)

    assert result.glare_score == 0.0
    assert result.total_length_m > 0.0


def test_evaluate_route_normalizes_scores_between_zero_and_one_hundred() -> None:
    eastbound = make_route(
        "eastbound",
        [Coordinates(lat=0.0, lon=0.0), Coordinates(lat=0.0, lon=0.02)],
    )
    northbound = make_route(
        "northbound",
        [Coordinates(lat=0.0, lon=0.0), Coordinates(lat=0.02, lon=0.0)],
    )
    sun = SunPosition(azimuth_deg=90.0, elevation_deg=10.0)

    east_result = evaluate_route(eastbound, sun)
    north_result = evaluate_route(northbound, sun)

    assert 0.0 <= east_result.glare_score <= 100.0
    assert 0.0 <= north_result.glare_score <= 100.0
    assert east_result.glare_score > north_result.glare_score


def test_rank_routes_returns_empty_list_for_missing_routes() -> None:
    sun = SunPosition(azimuth_deg=90.0, elevation_deg=15.0)

    assert rank_routes([], sun) == []


def test_evaluate_route_handles_missing_geometry() -> None:
    route = make_route("missing", [])
    sun = SunPosition(azimuth_deg=90.0, elevation_deg=15.0)

    result = evaluate_route(route, sun)

    assert result.glare_score == 0.0
    assert result.total_length_m == 0.0
