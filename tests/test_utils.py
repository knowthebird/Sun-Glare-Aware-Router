from src.models import Coordinates
import pytest

from src.utils import (
    angular_difference_degrees,
    calculate_bearing,
    format_duration_minutes,
)


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


@pytest.mark.parametrize(
    ("duration_s", "expected"),
    [
        (45 * 60, "45 min"),
        (2 * 60 * 60, "2 hr"),
        ((26 * 60 * 60) + (30 * 60), "26 hr 30 min"),
        ((50 * 60 * 60) + (15 * 60), "2 days 2 hr 15 min"),
    ],
)
def test_format_duration_preserves_elapsed_days(
    duration_s: float,
    expected: str,
) -> None:
    assert format_duration_minutes(duration_s) == expected


def test_format_duration_rejects_negative_elapsed_time() -> None:
    with pytest.raises(ValueError, match="duration"):
        format_duration_minutes(-1.0)
