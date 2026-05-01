from dataclasses import dataclass

from src.http_client import SystemSSLContextAdapter
from src.geocoding import NominatimGeocoder
from src.models import Coordinates
from src.routing import OSRMRouter


@dataclass
class FakeResponse:
    payload: object
    status_code: int = 200

    def json(self) -> object:
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class FakeSession:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get(
        self,
        url: str,
        *,
        params: dict[str, object],
        timeout: float,
        headers: dict[str, str],
    ) -> FakeResponse:
        self.calls.append(
            (
                url,
                {
                    "params": params,
                    "timeout": timeout,
                    "headers": headers,
                },
            )
        )
        return FakeResponse(self.payload)


class SequenceFakeSession:
    def __init__(self, payloads: list[object]) -> None:
        self.payloads = payloads
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get(
        self,
        url: str,
        *,
        params: dict[str, object],
        timeout: float,
        headers: dict[str, str],
    ) -> FakeResponse:
        self.calls.append(
            (
                url,
                {
                    "params": params,
                    "timeout": timeout,
                    "headers": headers,
                },
            )
        )
        index = min(len(self.calls) - 1, len(self.payloads) - 1)
        return FakeResponse(self.payloads[index])


def test_nominatim_geocoder_returns_first_result() -> None:
    session = FakeSession(
        [
            {
                "display_name": "Madrid, Community of Madrid, Spain",
                "lat": "40.4168",
                "lon": "-3.7038",
            }
        ]
    )
    geocoder = NominatimGeocoder(
        base_url="https://example.test/search",
        reverse_base_url="https://example.test/reverse",
        user_agent="sun-router-test",
        timeout_s=5.0,
        session=session,
    )

    result = geocoder.geocode("Madrid")

    assert result is not None
    assert result.label.startswith("Madrid")
    assert result.coordinates == Coordinates(lat=40.4168, lon=-3.7038)


def test_nominatim_geocoder_returns_none_when_empty() -> None:
    geocoder = NominatimGeocoder(
        base_url="https://example.test/search",
        reverse_base_url="https://example.test/reverse",
        user_agent="sun-router-test",
        timeout_s=5.0,
        session=FakeSession([]),
    )

    assert geocoder.geocode("Nowhere") is None


def test_nominatim_reverse_geocoder_returns_result() -> None:
    session = FakeSession(
        {
            "display_name": "Puerta del Sol, Madrid, Spain",
            "lat": "40.4169",
            "lon": "-3.7035",
        }
    )
    geocoder = NominatimGeocoder(
        base_url="https://example.test/search",
        reverse_base_url="https://example.test/reverse",
        user_agent="sun-router-test",
        timeout_s=5.0,
        session=session,
    )

    result = geocoder.reverse_geocode(Coordinates(lat=40.4169, lon=-3.7035))

    assert result is not None
    assert result.label.startswith("Puerta del Sol")
    assert result.coordinates == Coordinates(lat=40.4169, lon=-3.7035)


def test_default_provider_sessions_use_system_ssl_context() -> None:
    geocoder = NominatimGeocoder(
        base_url="https://example.test/search",
        reverse_base_url="https://example.test/reverse",
        user_agent="sun-router-test",
        timeout_s=5.0,
    )
    router = OSRMRouter(
        base_url="https://example.test/route/v1",
        user_agent="sun-router-test",
        timeout_s=5.0,
        max_alternatives=2,
    )

    assert isinstance(
        geocoder.session.get_adapter("https://example.test"),
        SystemSSLContextAdapter,
    )
    assert isinstance(
        router.session.get_adapter("https://example.test"),
        SystemSSLContextAdapter,
    )


def test_osrm_router_parses_geojson_routes() -> None:
    session = FakeSession(
        {
            "routes": [
                {
                    "distance": 1200.0,
                    "duration": 600.0,
                    "geometry": {"coordinates": [[-3.7, 40.4], [-3.69, 40.41]]},
                },
                {
                    "distance": 1300.0,
                    "duration": 650.0,
                    "geometry": {"coordinates": [[-3.7, 40.4], [-3.68, 40.42]]},
                },
            ]
        }
    )
    router = OSRMRouter(
        base_url="https://example.test/route/v1",
        user_agent="sun-router-test",
        timeout_s=5.0,
        max_alternatives=2,
        session=session,
    )

    routes = router.get_routes(
        origin=Coordinates(lat=40.4, lon=-3.7),
        destination=Coordinates(lat=40.42, lon=-3.68),
        profile="driving",
    )

    assert len(routes) == 2
    assert routes[0].metrics.distance_m == 1200.0
    assert routes[0].geometry[0] == Coordinates(lat=40.4, lon=-3.7)
    assert routes[1].geometry[-1] == Coordinates(lat=40.42, lon=-3.68)


def test_osrm_router_requests_fallback_candidates_when_primary_has_one_route() -> None:
    session = SequenceFakeSession(
        [
            {
                "routes": [
                    {
                        "distance": 1200.0,
                        "duration": 600.0,
                        "geometry": {
                            "coordinates": [[-3.7, 40.4], [-3.69, 40.41]],
                        },
                    }
                ]
            },
            {
                "routes": [
                    {
                        "distance": 1400.0,
                        "duration": 720.0,
                        "geometry": {
                            "coordinates": [
                                [-3.7, 40.4],
                                [-3.75, 40.45],
                                [-3.69, 40.41],
                            ],
                        },
                    }
                ]
            },
            {
                "routes": [
                    {
                        "distance": 1500.0,
                        "duration": 780.0,
                        "geometry": {
                            "coordinates": [
                                [-3.7, 40.4],
                                [-3.64, 40.45],
                                [-3.69, 40.41],
                            ],
                        },
                    }
                ]
            },
        ]
    )
    router = OSRMRouter(
        base_url="https://example.test/route/v1",
        user_agent="sun-router-test",
        timeout_s=5.0,
        max_alternatives=3,
        session=session,
    )

    routes = router.get_routes(
        origin=Coordinates(lat=40.4, lon=-3.7),
        destination=Coordinates(lat=40.41, lon=-3.69),
        profile="driving",
    )

    assert len(routes) == 3
    assert [route.metadata.get("route_index") for route in routes] == [1, 2, 3]
    assert len(session.calls) >= 2
    assert any(call[0].count(";") >= 2 for call in session.calls[1:])
