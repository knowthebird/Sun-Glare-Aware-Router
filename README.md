# Sun-Glare-Aware Router

Sun-Glare-Aware Router is a Streamlit MVP that helps a driver compare possible trip times for a selected route and look for lower estimated direct-sun glare. You choose an origin, a destination, a route, and a departure or arrival window; the app estimates sun alignment along the route and recommends the lowest-glare candidate it found.

Project status: MVP / experimental prototype.

## Safety Warning

Results are estimates. This application is not a navigation system, a driving-safety guarantee, or a substitute for real visibility judgment. It does not account for all road, weather, traffic, vehicle, obstruction, or driver conditions. Drivers remain responsible for safe operation and should not interact with the application while driving.

## 30-Second Quick Start

Tested in CI with Python `3.11` on Ubuntu and Windows. The package metadata accepts Python `3.11+`.

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
streamlit run app.py
```

On Windows PowerShell, activate with:

```powershell
.venv\Scripts\Activate.ps1
```

On Windows, use `py -3.11` or your installed Python launcher in place of `python3`.

Expected result: Streamlit prints a local URL such as `http://localhost:8501` and serves the app with a preloaded Washington, District of Columbia to Sacramento, California demo trip. If that port is busy, Streamlit chooses another local port.

## Project Lineage

This project is an expansion of [DOKOS-TAYOS/Sun-Glare-Aware-Router](https://github.com/DOKOS-TAYOS/Sun-Glare-Aware-Router). The original project provides the Streamlit application foundation, routing and geocoding integrations, map-based location selection, solar-position calculations, route glare-scoring foundation, Folium route visualization, and configuration/provider abstractions. This repository wraps and extends that work with additional time-search, route-visualization, location-entry, timezone, and usability features.

The upstream MIT license and copyright notices remain authoritative for inherited code. See [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Inherited foundation:

- Streamlit UI and local demo workflow.
- Nominatim geocoding and reverse geocoding.
- OSRM-compatible route acquisition and route alternatives.
- Map-based origin and destination refinement.
- Solar-position lookup and segment-level glare scoring.
- Folium map rendering for pickers and route results.
- Environment-driven provider configuration.

Extensions in this repository:

- Departure-window and arrival-window time searches.
- Best-time recommendations for a selected route.
- Single-day and date-range search scopes.
- Exact date-range evaluation when the candidate grid fits the budget.
- Deterministic adaptive date-range search for larger ranges.
- Glare levels displayed along the inspected route.
- Peak-glare and longest high-glare stretch markers.
- Route-direction reversal.
- Address suggestions with graceful fallback to explicit search and map refinement.
- Origin, browser, configured-default, and manual timezone selection.
- Date-range presets and alternative-candidate inspection.

## Why This Project?

Ordinary route planners optimize for time, distance, or traffic. This project explores a narrower question: whether driving the same route at a different time can reduce estimated direct sun alignment in front of the vehicle.

The demo can be useful for comparing commute departure times, examining morning or evening glare exposure, exploring lower-glare trips across a date range, or demonstrating solar geometry applied to routing. It is not appropriate for turn-by-turn navigation, safety certification, or deciding whether conditions are safe to drive.

## Using The Application

### Single-Day Search

1. Keep the demo trip or search for a new origin and destination.
2. Confirm each location by selecting a suggestion, submitting an explicit search, or clicking the exact point on the picker map.
3. Use `Reverse origin and destination` if you want to evaluate the return direction.
4. Generate route alternatives and choose the route to evaluate.
5. Select `Single day`, choose `Departure` or `Arrival`, set the date, time window, and timezone.
6. Run the evaluation.
7. Review the recommended departure time, expected arrival time, overall glare score, high-risk minutes, candidate table, chart, and glare-colored route map.
8. Pick another evaluated candidate from the inspection control to recolor the map without rerunning the search.

### Date-Range Search

1. Select `Date range` after generating route alternatives.
2. Choose a start date, end date, daily time window, departure or arrival mode, and timezone.
3. Use the 7-day, 30-day, or summer presets if they match the period you want to inspect.
4. Run the date-range evaluation.
5. Interpret the result as the best individual trip found in the selected range, not a recurring schedule.
6. Inspect recommended and alternative candidates, the heatmap, fixed-time view, and route map.

Date-range results are labeled as either `Exact search` or `Adaptive estimate`. Exact search evaluates every date/time candidate at the final 10-minute resolution. Adaptive estimate means the full grid was larger than the default evaluation budget, so the optimizer sampled representative candidates and refined promising periods. Adaptive results are deterministic, but they are not a mathematical guarantee of the global optimum.

### Address Entry And Timezones

Address suggestions use the public Photon endpoint when enabled and online. If suggestions fail, explicit search and map refinement remain available. Recent session suggestions may still appear from local Streamlit state.

The timezone defaults to the confirmed origin when possible. Browser timezone and `SUNROUTER_DEFAULT_TIMEZONE` are fallbacks, and the UI also allows manual override. Trip windows are interpreted in the selected timezone; in normal automatic mode that is the origin timezone.

## Understanding Results

Lower glare scores mean less estimated direct-sun alignment according to this model. They do not mean the drive is safe or comfortable in real conditions.

| Result | Meaning |
| --- | --- |
| Overall glare score | Length-weighted route score from `0` to `100`; lower is better in the model. |
| High-risk duration | Estimated time spent on route segments scoring at least `35`. |
| High-risk distance | Estimated distance on route segments scoring at least `35`. |
| Recommended departure | Candidate departure with the lowest score, then lower high-risk duration, then earliest requested time as tie-breakers. |
| Expected arrival | Estimated arrival based on the route provider duration. |
| Exact search | Every final-resolution candidate was evaluated. |
| Adaptive estimate | A deterministic sampled/refined search was used because the full grid exceeded the budget. |

The inspected route map uses these glare levels:

| Level | Segment score |
| --- | ---: |
| Minimal | `0-5` |
| Low | `5-20` |
| Moderate | `20-35` |
| High | `35-65` |
| Severe | `65+` |

The map can mark the highest instantaneous glare segment and the longest contiguous stretch of high-glare segments. Those markers may appear in different places.

## How It Works

```text
Origin and destination
        |
        v
Selected route geometry
        |
        v
Candidate dates and times
        |
        v
Estimated sun position along route segments
        |
        v
Glare scoring and time comparison
        |
        v
Recommendation and glare-colored map
```

The app splits route geometry into segments. It estimates when the vehicle reaches each segment by distributing the route provider's total duration by segment length. For each segment midpoint, it compares the segment bearing with the solar azimuth and reduces the score when the sun is high or below the horizon. Candidate trip times are ranked by overall score, high-risk duration, and requested time.

Large date ranges may use deterministic adaptive sampling instead of evaluating every possible 10-minute candidate.

## Requirements And Installation

- Python: tested with `3.11`; package metadata allows `3.11+`.
- Browser: required for the Streamlit UI.
- Network: required for first-time public geocoding, address suggestions, routing, and map tiles.
- Offline behavior: glare calculations can run after route geometry and location data are already available in app state, but the default public providers are online services.
- Tested platforms: CI runs on Ubuntu and Windows with Python `3.11`.

Install the runtime app:

```bash
python3 -m pip install -e .
```

Install development dependencies:

```bash
python3 -m pip install -e ".[dev]"
```

## Configuration

The app reads environment variables directly and also loads a local `.env` file from the repository root. Start with [.env.example](.env.example) for common settings.

| Variable | Default | Purpose |
| --- | --- | --- |
| `SUNROUTER_DEFAULT_TIMEZONE` | `America/New_York` | Fallback IANA timezone. |
| `SUNROUTER_GEOCODER_PROVIDER` | `nominatim` | Geocoder implementation. |
| `SUNROUTER_GEOCODER_BASE_URL` | `https://nominatim.openstreetmap.org/search` | Forward-geocoding endpoint. |
| `SUNROUTER_REVERSE_GEOCODER_BASE_URL` | `https://nominatim.openstreetmap.org/reverse` | Reverse-geocoding endpoint. |
| `SUNROUTER_SUGGESTIONS_ENABLED` | `true` | Enable address suggestions. |
| `SUNROUTER_SUGGESTION_ENDPOINT_URL` | `https://photon.komoot.io/api` | Photon-compatible suggestion endpoint. |
| `SUNROUTER_ROUTER_PROVIDER` | `osrm` | Routing implementation. |
| `SUNROUTER_ROUTER_BASE_URL` | `https://router.project-osrm.org/route/v1` | OSRM-compatible route endpoint root. |
| `SUNROUTER_ROUTING_PROFILE` | `driving` | Route profile. |
| `SUNROUTER_MAX_ALTERNATIVES` | `3` | Maximum route alternatives kept. |
| `SUNROUTER_HTTP_TIMEOUT_S` | `10` | HTTP timeout in seconds. |
| `SUNROUTER_CACHE_TTL_S` | `900` | In-memory cache lifetime in seconds. |
| `SUNROUTER_LOG_LEVEL` | `INFO` | App and provider logging level. |

Other suggestion debounce, rate-limit, and result-count settings are defined in [src/config.py](src/config.py). Public demonstration endpoints may be rate-limited, unavailable, or unsuitable for heavy production traffic. Use your own provider infrastructure for sustained use.

## Limitations

- No traffic modeling.
- No weather, cloud, or air-quality modeling.
- No buildings, trees, hills, signs, windshield, visor, vehicle-height, or driver-position modeling.
- Route timing is estimated from total route duration, not turn-by-turn timing.
- Public provider availability is not guaranteed.
- Address suggestions and new route generation require connectivity.
- Adaptive searches do not guarantee the global mathematical optimum.
- Route providers may return limited alternatives.
- A low estimated glare score is not a safety determination.
- The app is not intended for use while driving.

## Development

```bash
python3 -m pip install -e ".[dev]"
ruff check .
ruff format --check .
pyright
python3 -m pytest
streamlit run app.py
```

Small repository map:

- [app.py](app.py): Streamlit UI and orchestration.
- [src/route_time_search.py](src/route_time_search.py): single-day and date-range candidate search.
- [src/scoring.py](src/scoring.py): solar alignment and glare scoring.
- [src/mapview.py](src/mapview.py): Folium picker and route maps.
- [src/geocoding.py](src/geocoding.py) and [src/routing.py](src/routing.py): provider integrations.
- [tests](tests): automated tests for scoring, providers, maps, UI state, and search behavior.

## Streamlit Community Cloud Deployment

The repository includes the expected Streamlit Cloud files:

- [app.py](app.py) as the main file.
- [requirements.txt](requirements.txt) for cloud dependency installation.
- [.streamlit/config.toml](.streamlit/config.toml).
- [.streamlit/secrets.toml.example](.streamlit/secrets.toml.example).

Configure real secrets or provider overrides in Streamlit's Secrets manager, not in committed files. Public geocoding, suggestion, routing, and map services still have their own usage policies and may not be reliable enough for production traffic.

## Support

Use the current repository's GitHub issue tracker for reproducible bugs, feature requests, and usage questions. Include the route, date/time window, provider configuration, traceback, and whether the issue reproduces with the default demo when applicable.

## License And Attribution

This repository is released under the MIT License. See [LICENSE](LICENSE).

This project builds on [DOKOS-TAYOS/Sun-Glare-Aware-Router](https://github.com/DOKOS-TAYOS/Sun-Glare-Aware-Router), and the upstream license and copyright notices remain authoritative for inherited code.

Runtime dependency and service notes are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). OpenStreetMap, Nominatim, Photon, OSRM-compatible providers, and map tile providers have their own attribution and usage terms. Visible map attribution must remain intact.
