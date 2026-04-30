# Changelog

## Unreleased

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
