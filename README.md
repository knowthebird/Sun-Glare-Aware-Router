# Sun-Glare-Aware Router

`Sun-Glare-Aware Router` is a Streamlit app that compares driving route alternatives and estimates which one is less likely to put low sun directly in front of the driver.

In plain words: you choose an origin, a destination, a date, and a departure time, and the app tries to answer:

> "If I leave at this time, which route is less likely to be uncomfortable or risky because of sun glare?"

The repository is prepared for local use and for deployment on Streamlit Community Cloud.

## Why This Repo Exists

Most route planners optimize for time or distance. This project explores a different question: whether two similar routes may expose the driver to very different sun-glare conditions.

This can be useful for trips such as:

- commuting early in the morning or late in the afternoon,
- comparing alternative road corridors before leaving,
- experimenting with route scoring models that include environmental conditions,
- building a routing prototype for research, demos, or decision support.

The app is not trying to replace a navigation product. It is a lightweight decision aid focused on one specific factor: direct solar glare.

## What The App Does

The app:

1. geocodes an approximate origin and destination,
2. lets the user refine both points by clicking the exact place on two separate maps,
3. requests one or more candidate routes from an OSRM-compatible backend,
4. computes the sun position for the selected departure date, time, and timezone,
5. evaluates glare risk along each route as the trip progresses,
6. recommends the route with the lowest estimated glare impact,
7. explains the result with summary metrics and a highlighted high-risk segment.

The interface also includes:

- an ES/EN language toggle,
- a route comparison table,
- a debug panel with provider and scoring details,
- a pre-filled demo trip from Madrid to Burgos so the app is easy to try.

## How The Scoring Works

The current model is intentionally simple enough to understand and modify:

1. Each route geometry is split into segments.
2. Trip duration is distributed across those segments according to segment length.
3. The app recomputes the sun position near the midpoint of every segment at the estimated time the driver would reach it.
4. It compares segment direction with the sun azimuth.
5. It increases the penalty when the sun is low and reduces it to zero when the sun is below the horizon.
6. It aggregates those segment penalties into a normalized glare score between `0` and `100`.

Besides the final score, the app also reports:

- high-risk time,
- high-risk distance,
- peak-risk moment,
- approximate kilometer where peak risk occurs,
- the highest-risk segment on the map.

## What This Repo Is Good For

This repository is a good fit if you want:

- a small, readable Streamlit app,
- a public-demo-friendly routing prototype,
- a starting point for route scoring experiments,
- provider swapping through configuration instead of UI rewrites,
- a project that works locally and can be deployed easily.

## What This Repo Is Not

This repository is not:

- a production navigation system,
- a traffic-aware route optimizer,
- a safety guarantee,
- a full physical visibility model.

It does not model traffic, weather, buildings, trees, hills, windshield properties, vehicle orientation details beyond route bearing, or turn-by-turn timing precision.

## Typical User Flow

1. Open the app.
2. Keep the demo trip or search for a new origin and destination.
3. Click the exact origin point on the first map.
4. Click the exact destination point on the second map.
5. Choose the departure date, time, and timezone.
6. Generate routes.
7. Compare the suggested route, the alternatives, and the highlighted risk zone.

This makes the app more precise than a pure text-input workflow because the final analysis uses the coordinates confirmed on the maps.

## Repository Structure

- `app.py`: Streamlit UI and orchestration.
- `src/config.py`: environment-driven settings and timezone helpers.
- `src/geocoding.py`: pluggable geocoder interface and default Nominatim client.
- `src/routing.py`: pluggable router interface and default OSRM-compatible client.
- `src/solar.py`: timezone-aware sun-position lookup.
- `src/scoring.py`: glare scoring and route ranking.
- `src/pickers.py`: origin/destination picker state transitions.
- `src/mapview.py`: Folium map rendering for pickers and results.
- `src/cache.py`: small TTL cache and polite rate limiting.
- `src/utils.py`: shared helpers for geometry, formatting, and logging.
- `tests/`: unit tests for scoring, providers, map rendering, UI behavior, and state handling.

## Local Setup

This project targets Python `3.11+`.

1. Create the virtual environment:

```bash
python -m venv .venv
```

2. Activate it:

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Linux/macOS bash:

```bash
source .venv/bin/activate
```

3. Install the app with development dependencies:

```bash
python -m pip install -e .[dev]
```

4. Optional: copy `.env.example` to `.env` if you want to override provider settings locally.

`src/config.py` loads `.env` automatically when the app runs from the repository root.

## Run Locally

```bash
streamlit run app.py
```

Run the command from the repository root.

By default, the app opens with a demo trip from Madrid to Burgos at `09:00` in `Europe/Madrid`, which makes it easy to test the workflow immediately.

## Configuration

The app is configured through environment variables.

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
| `SUNROUTER_MAX_ALTERNATIVES` | Maximum number of candidate routes kept | `3` |
| `SUNROUTER_USER_AGENT` | Request header for public providers | `sun-glare-router/0.1.0` |
| `SUNROUTER_HTTP_TIMEOUT_S` | HTTP timeout in seconds | `10` |
| `SUNROUTER_CACHE_TTL_S` | In-memory cache duration in seconds | `900` |
| `SUNROUTER_DEFAULT_TIMEZONE` | Default IANA timezone in the UI | `Europe/Madrid` |
| `SUNROUTER_LOG_LEVEL` | Application and provider log verbosity | `INFO` |

## Provider Notes

The default configuration uses public OpenStreetMap ecosystem services:

- Nominatim for geocoding and reverse geocoding,
- an OSRM-compatible endpoint for routing,
- OpenStreetMap-based tiles for map display.

That is convenient for local demos and light experimentation, but it is not suitable for heavy production traffic. For more demanding use cases, point the app to your own infrastructure or to supported third-party services with appropriate usage terms.

## Swapping Providers

The project separates UI logic from provider implementations, so changing infrastructure does not require rewriting the app flow.

Examples:

- point `SUNROUTER_ROUTER_BASE_URL` to a self-hosted OSRM instance while keeping `SUNROUTER_ROUTER_PROVIDER=osrm`,
- replace the geocoder by implementing the `Geocoder` protocol and updating `build_geocoder`,
- replace the router by implementing the `Router` protocol and updating `build_router`.

## Streamlit Community Cloud Deployment

The repository already includes the files Streamlit Community Cloud usually expects:

- `app.py` at the repository root,
- `requirements.txt` at the repository root,
- `.streamlit/config.toml`,
- `.streamlit/secrets.toml.example`.

To deploy:

1. Push the repository to GitHub.
2. Create a new app in Streamlit Community Cloud.
3. Select the repository, branch, and `app.py` as the main file.
4. If needed, copy values from `.streamlit/secrets.toml.example` into the Streamlit Secrets manager.
5. Deploy.

Local `.env` files and project-level `.streamlit/secrets.toml` files should stay out of git. Only templates such as `.env.example` and `.streamlit/secrets.toml.example` should be committed.

## Testing

Run the test suite with:

```bash
python -m pytest
```

Useful quality checks for development:

```bash
ruff check . --fix
ruff format .
pyright
```

The automated tests avoid live network calls and focus on the parts that matter most in this project: geometry, scoring, provider parsing, state handling, and UI rendering behavior.

## Limitations

- Public routing providers may return only one route for some trips.
- Segment timing is estimated from total duration rather than turn-by-turn timings.
- The model focuses on direct solar alignment, not full visual obstruction.
- Results are advisory and should not be treated as a driving safety guarantee.

## License And Attribution

- The repository code is released under the MIT License.
- Runtime dependency notices are listed in `THIRD_PARTY_NOTICES.md`.
- OpenStreetMap data terms and public service usage policies still apply separately.
- Map attribution must remain visible when OpenStreetMap-derived tiles are used.
