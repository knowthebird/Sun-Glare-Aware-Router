# Sun-Glare-Aware Router

A public-repo-friendly Streamlit MVP that compares route alternatives and estimates which route is less likely to put low sun directly in the driver's field of view.

## What The App Does

- Geocodes an origin and destination.
- Lets the user refine origin and destination by clicking the exact point on two separate maps.
- Requests one or more candidate routes from an OSRM-compatible backend.
- Computes the sun's azimuth and elevation for a chosen date, time, and timezone.
- Scores each route with a simple glare-risk heuristic.
- Recommends the lowest-glare route and visualizes all candidates on an interactive map.

## Screenshots

_Add screenshots here after running the app locally._

## Architecture Overview

- `app.py`: Streamlit UI, guided location picking, orchestration, and result rendering.
- `src/config.py`: Environment-driven settings and timezone helpers.
- `src/geocoding.py`: Swappable geocoder interface plus default Nominatim client.
- `src/pickers.py`: State transitions for origin/destination pickers and route-generation readiness.
- `src/routing.py`: Swappable router interface plus default OSRM-compatible client.
- `src/solar.py`: Timezone-aware datetime handling and Astral sun position lookup.
- `src/scoring.py`: Isolated glare scoring and route recommendation logic.
- `src/mapview.py`: Folium map assembly for Streamlit.
- `src/cache.py`: Small in-memory TTL cache and polite rate limiter.
- `src/utils.py`: Lightweight geometry, formatting, and shared helpers.

## Setup

1. Create a virtual environment.
2. Install the package and dev dependencies:

```bash
python -m pip install -e .[dev]
```

3. Copy `.env.example` to `.env` if you want to override provider settings.

## Run Locally

```bash
streamlit run app.py
```

The default UI is pre-filled with a demo trip from Madrid to Burgos at 09:00 in `Europe/Madrid` time so you can try the MVP quickly. You now refine both points by searching approximately and then clicking the exact place on each map.

## Environment Variables

| Variable | Purpose | Default |
| --- | --- | --- |
| `SUNROUTER_GEOCODER_PROVIDER` | Active geocoder implementation | `nominatim` |
| `SUNROUTER_GEOCODER_BASE_URL` | Geocoder endpoint | `https://nominatim.openstreetmap.org/search` |
| `SUNROUTER_REVERSE_GEOCODER_BASE_URL` | Reverse geocoder endpoint | `https://nominatim.openstreetmap.org/reverse` |
| `SUNROUTER_GEOCODER_MIN_INTERVAL_S` | Minimum delay between geocoding calls | `1.0` |
| `SUNROUTER_ROUTER_PROVIDER` | Active router implementation | `osrm` |
| `SUNROUTER_ROUTER_BASE_URL` | OSRM-compatible route endpoint root | `https://router.project-osrm.org/route/v1` |
| `SUNROUTER_ROUTER_MIN_INTERVAL_S` | Minimum delay between routing calls | `1.0` |
| `SUNROUTER_ROUTING_PROFILE` | Routing profile name | `driving` |
| `SUNROUTER_MAX_ALTERNATIVES` | Max routes kept from provider output | `3` |
| `SUNROUTER_USER_AGENT` | Request header for public providers | `sun-glare-router-mvp/0.1` |
| `SUNROUTER_HTTP_TIMEOUT_S` | HTTP timeout in seconds | `10` |
| `SUNROUTER_CACHE_TTL_S` | In-memory TTL cache duration in seconds | `900` |
| `SUNROUTER_DEFAULT_TIMEZONE` | Default IANA timezone shown in the UI | `Europe/Madrid` |
| `SUNROUTER_LOG_LEVEL` | Application and provider log verbosity | `INFO` |

## How Glare Scoring Works

This MVP uses an intentionally simple and explainable heuristic:

1. The user searches an approximate origin and destination, then confirms both points by clicking on two separate maps.
2. The sun position is computed once for the selected datetime using the confirmed origin coordinates.
3. Each route geometry is split into line segments.
4. Every segment gets a forward bearing and a length.
5. The bearing is compared with the sun azimuth using a smooth cosine-based alignment penalty.
6. The penalty is scaled up when the sun is low and scaled to zero when the sun is below the horizon.
7. Segment penalties are weighted by length and normalized to a `0-100` route glare score.

The heuristic is easy to replace later because scoring is isolated in `src/scoring.py`.

## Limitations Of The MVP

- Solar position is computed at the confirmed origin only, not continuously along the route.
- Public demo providers may return only one route for some trips.
- Traffic, obstructions, weather, road grade, and windshield orientation are not modeled.
- The score is a routing aid, not a safety guarantee.

## Attribution And Usage Notes

- The default map tiles use OpenStreetMap and must retain visible attribution.
- Default demo geocoding and routing endpoints are for light/demo usage only. Heavy or production traffic should use self-hosted or contractually supported infrastructure.
- The repository code is MIT-licensed, but OpenStreetMap data terms and public service usage policies are separate and still apply.

## Swapping Providers Later

The app is designed so you can replace providers through environment variables and factory wiring:

- Point `SUNROUTER_ROUTER_BASE_URL` at a self-hosted OSRM instance and keep `SUNROUTER_ROUTER_PROVIDER=osrm`.
- Replace the default geocoder by implementing the `Geocoder` protocol and updating `build_geocoder`.
- Replace the default router by implementing the `Router` protocol and updating `build_router`.

This keeps the UI and glare scoring stable while letting you swap infrastructure later.

## Testing

Run the unit tests with:

```bash
python -m pytest
```

The test suite avoids live network calls and focuses on geometry, scoring, and provider parsing.
