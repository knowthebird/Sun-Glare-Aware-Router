# Third-Party Notices

This repository intentionally keeps its direct dependency list small and permissive-license-only.

## Runtime Dependencies

| Package | License |
| --- | --- |
| `streamlit` | Apache-2.0 |
| `requests` | Apache-2.0 |
| `astral` | Apache-2.0 |
| `folium` | MIT |
| `streamlit-folium` | MIT |
| `tzdata` | Apache-2.0 |

`tzdata` is only installed on Windows, where `zoneinfo` may need it.

## Development Dependencies

| Package | License |
| --- | --- |
| `pytest` | MIT |
| `setuptools` | MIT |

These notices apply to direct dependencies used by this repository. Transitive dependencies keep their own licenses and notices.
