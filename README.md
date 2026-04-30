# Sun-Glare-Aware Router

A public-repo-friendly Streamlit app that compares route alternatives and estimates which route is less likely to put low sun directly in the driver's field of view. The repository is prepared for local use and for deployment on Streamlit Community Cloud.

## What The App Does

- Geocodes an origin and destination.
- Lets the user refine origin and destination by clicking the exact point on two separate maps.
- Requests one or more candidate routes from an OSRM-compatible backend.
- Computes the sun's azimuth and elevation for a chosen date, time, and timezone.
- Scores each route with a dynamic glare-risk model that evolves along the trip.
- Explains the recommendation with time-at-risk metrics and highlights the highest-risk segment on the map.

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

## Local Setup

1. Create and activate a virtual environment.
2. Install the app and dev dependencies:

```bash
python -m pip install -e .[dev]
```

3. Optional: copy `.env.example` to `.env` if you want to override provider settings locally.

`src/config.py` loads `.env` automatically when you run the app from the repository root.

## Run Locally

```bash
streamlit run app.py
```

Run the command from the repository root so local paths behave the same way they do on Streamlit Community Cloud.

The default UI is pre-filled with a demo trip from Madrid to Burgos at 09:00 in `Europe/Madrid` time so you can try the app quickly. You refine both points by searching approximately and then clicking the exact place on each map.

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

## Streamlit Community Cloud Deployment

The repository includes the files Streamlit Community Cloud expects most often:

- `app.py` as the app entrypoint at the repository root.
- `requirements.txt` at the repository root.
- `.streamlit/config.toml` for app configuration.
- `.streamlit/secrets.toml.example` as a safe template for cloud secrets.

To deploy:

1. Push the repository to GitHub as a public repository.
2. In Streamlit Community Cloud, create a new app and select:
   - Repository: your GitHub repository
   - Branch: the branch you want to deploy
   - Main file path: `app.py`
3. Optional: in the app's advanced settings, paste root-level values based on `.streamlit/secrets.toml.example` into the Secrets field if you want to override any defaults.
4. Save and deploy.

The Streamlit docs currently recommend keeping `requirements.txt` at the root and placing custom configuration in `.streamlit/config.toml`. They also recommend passing secrets through the Secrets manager instead of committing them to the repository.

Local `.env` files and project-level `.streamlit/secrets.toml` files should stay out of git. Only commit `.env.example` and `.streamlit/secrets.toml.example`.

## How Glare Scoring Works

The current scoring model is still lightweight, but it is no longer a single-point estimate:

1. The user searches an approximate origin and destination, then confirms both points by clicking on two separate maps.
2. Each route geometry is split into line segments.
3. Segment duration is estimated by distributing the route duration across the geometry by segment length.
4. The sun position is recomputed at the midpoint of every segment using the estimated time when the driver would reach that part of the route.
5. Segment bearing is compared with the local sun azimuth using a smooth cosine-based alignment penalty.
6. The penalty is scaled up when the sun is low and scaled to zero when the sun is below the horizon.
7. Segment penalties are weighted by segment length and normalized to a `0-100` route glare score.
8. The app also reports high-risk time, high-risk distance, peak-risk timing, and the highest-risk segment for the recommended route.

The heuristic is easy to replace later because scoring is isolated in `src/scoring.py`.

## Limitations Of The MVP

- Public demo providers may return only one route for some trips.
- Segment timing is estimated from total route duration; the model does not use turn-by-turn travel times.
- Traffic, obstructions, weather, road grade, and windshield orientation are not modeled.
- The score is a routing aid, not a safety guarantee.
- The default public Nominatim and OSRM endpoints are suitable for demos and light use, not for heavy public traffic.

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

Before finishing Python work, the project also expects:

```bash
ruff check . --fix
ruff format .
```

If `pyright` is available in your environment, run it too after `pytest`.

The test suite avoids live network calls and focuses on geometry, scoring, UI rendering, and provider parsing.
