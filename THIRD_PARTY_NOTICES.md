# Third-party notices

Shared Memory Monitor is licensed under the **MIT License** (see [LICENSE](LICENSE)).

This application depends on the packages below. When you distribute or deploy
the monitor, their licenses apply to those components in addition to MIT for
this project's own source code.

## Direct Python dependencies

| Package | License | Role |
|---------|---------|------|
| [httpx](https://github.com/encode/httpx) | BSD-3-Clause | HTTP client (gateway `/health`, `/memory/telemetry`, `/memory/graph`) |
| [python-dotenv](https://github.com/theskumar/python-dotenv) | BSD-3-Clause | `.env` loading |
| [matplotlib](https://matplotlib.org/) | BSD-style (Matplotlib License) | PNG chart export |

## Transitive dependencies (selected)

| Package | License | Pulled in by |
|---------|---------|--------------|
| numpy | BSD-3-Clause (and others) | matplotlib |
| pillow | MIT-CMU | matplotlib |
| certifi | MPL-2.0 | httpx |
| httpcore, anyio, idna | BSD-3-Clause / MIT | httpx |

Run `pip-licenses -r` in the project venv for a full transitive list.

## Frontend (CDN, not bundled)

| Component | License | Usage |
|-----------|---------|-------|
| [Chart.js](https://www.chartjs.org/) 4.4.1 | MIT | Loaded from jsDelivr in `static/dashboard.html` |

## Gateway integration (HTTP, not vendored)

The monitor calls the Shared Memory Framework hive-mind gateway over HTTP
(`GET /memory/telemetry`, `POST /memory/graph`, `GET /health`). It does not
bundle or import `memory_bridge.py`.

## Generating a full license report

```bash
uv sync
uv pip install pip-licenses
pip-licenses -r --format=markdown -o licenses-report.md
```