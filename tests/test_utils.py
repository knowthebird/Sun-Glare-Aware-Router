from src.models import Coordinates
from src.utils import angular_difference_degrees, calculate_bearing


def test_calculate_bearing_cardinal_directions() -> None:
    origin = Coordinates(lat=0.0, lon=0.0)

    north = calculate_bearing(origin, Coordinates(lat=1.0, lon=0.0))
    east = calculate_bearing(origin, Coordinates(lat=0.0, lon=1.0))
    south = calculate_bearing(origin, Coordinates(lat=-1.0, lon=0.0))
    west = calculate_bearing(origin, Coordinates(lat=0.0, lon=-1.0))

    assert north == 0.0
    assert east == 90.0
    assert south == 180.0
    assert west == 270.0


def test_angular_difference_wraps_around_zero() -> None:
    assert angular_difference_degrees(350.0, 10.0) == 20.0
    assert angular_difference_degrees(10.0, 350.0) == 20.0
    assert angular_difference_degrees(90.0, 270.0) == 180.0
