# Changelog

## Unreleased

- Applied Dependabot-recommended updates for GitHub Actions and Python development tooling ranges.
- Added GitHub security automation for Dependabot and CI, while leaving CodeQL to GitHub default setup to avoid default/advanced configuration conflicts.
- Hardened runtime configuration validation for provider URLs, routing profiles, HTTP timeouts, cache duration, and route alternative limits, with friendly Streamlit errors for invalid cloud settings.
- Documented security expectations for Streamlit Community Cloud secrets and provider URLs.

## [0.1.0] - 2026-05-01

- Rewrote the repository documentation so the README explains more clearly what the app is for, how a user interacts with it, where its scoring is useful, and what its main limits are.
- Optimized the initial Streamlit load by rendering the lightweight header and planning panel before the map pickers, and by caching Folium picker/result maps so reruns reuse the heavy map objects instead of rebuilding them each time.
- Hardened map-point confirmation so a reverse-geocoding SSL/provider failure no longer crashes the Streamlit app; the selected point now falls back to the typed label or coordinates and shows a friendly warning instead.
- Fixed the Spanish reverse-geocoding warning text so it renders the accented characters correctly in Streamlit.
- Hardened manual place search so a geocoding SSL/provider failure no longer crashes the app; the picker now keeps its previous state and shows a friendly error instead.
- Updated the shared HTTP client to use the operating system certificate store for HTTPS requests, fixing provider SSL validation issues seen on Windows with Nominatim and other upstream services.
- Stopped reusing cached Folium map objects across rerenders because the shared map instance could block point selection after a search; interactive maps are now rebuilt with fresh internal IDs each time.
- Improved picker interaction so clicking directly on the provisional marker now confirms that searched point instead of requiring a nearby empty-map click.
- Aligned repository metadata with the renamed GitHub repository `Sun-Glare-Aware-Router`.
- Replaced the fixed-origin glare heuristic with a dynamic segment-by-segment solar analysis that follows route progress over time.
- Added per-route high-risk duration, high-risk distance, peak-risk timing, and segment risk details for clearer recommendations.
- Updated the Streamlit UI to explain glare risk in plain Spanish, show more useful comparison columns, and avoid presenting a single route as a comparative recommendation.
- Highlighted the highest-risk segment and peak-risk point on the route map.
- Expanded automated coverage for dynamic scoring, route comparison timing, map rendering, and updated UI behavior.
- Consolidated the iteration by normalizing user-facing Spanish text, removing escaped text artifacts in the scoring explanations, and re-verifying the focused and full test suites.
- Reorganized the screen into a planning panel and a stacked origin/destination panel, and replaced "minute of risk" messaging with clearer clock-time and kilometer references.
- Added a fallback route-generation strategy that probes lateral via-points when OSRM returns too few alternatives, and made the origin/destination search boxes submit on Enter through Streamlit forms.
- Moved the route comparison table to a full-width section at the bottom so it uses both columns and stays visually separated from the planning controls.
- Route ranking now breaks full ties in favor of the shorter route, the map uses distinct colors with only the recommended route shown as a thicker solid line, and the interface has a cleaner visual treatment with refined spacing and summary cards.
- Prepared the repository for public GitHub use and Streamlit Community Cloud with root-level requirements, a checked-in `.streamlit/config.toml`, a safe secrets template, automatic local `.env` loading, and clearer deployment documentation.
- Switched the default visual theme to a dark presentation and added lightweight internationalization with an ES/EN language selector that covers the main UI, route summaries, explanations, and map labels.
- Clarified the route comparison table by renaming the peak-kilometer column, switching its format to `number + km`, and grouping high-risk time next to high-risk distance.
- Refined the comparison table with explicit column sizing and changed map wheel zoom so it only activates while holding `Ctrl`, making map navigation less intrusive.
- Reviewed the licenses of the runtime libraries directly imported by the project and refreshed `THIRD_PARTY_NOTICES.md` to reflect the current permissive-license dependency set.
