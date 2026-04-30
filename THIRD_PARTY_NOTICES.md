# Third-Party Notices

This repository is published under the MIT license. The third-party libraries
that are directly imported by the application or its runtime support code use
permissive licenses as well.

This is a practical compatibility note for the repository, not legal advice.
Each third-party package keeps its own license terms, copyright notices, and
any attribution requirements.

## Runtime Libraries Imported By This Project

| Package | License | Notes |
| --- | --- | --- |
| `streamlit` | Apache-2.0 | Permissive. Keep Apache license and notice obligations when redistributing the package itself. |
| `streamlit-folium` | MIT | Permissive. |
| `folium` | MIT | Permissive. |
| `branca` | MIT | Permissive. Imported directly in `src/mapview.py`. |
| `requests` | Apache-2.0 | Permissive. Keep Apache license and notice obligations when redistributing the package itself. |
| `astral` | Apache-2.0 | Permissive. |
| `python-dotenv` | BSD-3-Clause | Permissive. |
| `tzdata` | Apache-2.0 | Permissive. Windows-only runtime dependency in this project. |

## Development Dependencies

| Package | License | Notes |
| --- | --- | --- |
| `pytest` | MIT | Permissive. Test-only dependency. |
| `ruff` | MIT | Permissive. Lint/format dependency. |
| `pyright` | MIT | Permissive. Type-checking dependency. |
| `setuptools` | MIT | Permissive. Build dependency. |

## Summary

All direct runtime libraries currently imported by the project use permissive
licenses that are commonly compatible with distributing this repository under
MIT.

The main extra point to remember is that Apache-2.0 packages are still
permissive but carry their own attribution and notice requirements when you
redistribute those packages or substantial bundled copies of them.
