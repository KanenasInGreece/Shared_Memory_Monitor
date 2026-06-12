from __future__ import annotations

import json
import mimetypes
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .analytics import build_api_payload
from .config import (
    IGNORED_OUTBOX_IDS,
    NEO4J_BROWSER_URL,
    POLL_INTERVAL_S,
    REM_BATCH,
    REM_POLL_S,
    ROOT,
    SERVER_HOST,
    SERVER_PORT,
    STATIC_DIR,
)
from .breakdown import fetch_breakdown
from .env_loader import bootstrap_env
from .summary import live_summary
from .system_health import system_health_snapshot
from .logs_reader import list_archives, list_sources, tail_source
from .store import init_db, load_history, meta, parse_range

_DASHBOARD = STATIC_DIR / "dashboard.html"
_LOGS = STATIC_DIR / "logs.html"
_DIAGRAM = STATIC_DIR / "diagram.html"
_STATIC_ROOT = STATIC_DIR.resolve()


def diagram_payload() -> dict:
    """Bundle live summary + health for the architecture diagram view."""
    return {
        "summary": live_summary(),
        "health": system_health_snapshot(),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def _safe_static_path(url_path: str) -> Path | None:
    """Resolve /static/… under STATIC_DIR only — blocks path traversal."""
    if not url_path.startswith("/static/"):
        return None
    rel = url_path[len("/static/"):]
    if not rel or ".." in rel.split("/"):
        return None
    target = (_STATIC_ROOT / rel).resolve()
    if _STATIC_ROOT not in target.parents and target != _STATIC_ROOT:
        return None
    return target


def _auto_bucket_minutes(rows: list[dict], range_spec: str) -> int | None:
    """Downsample only when point count or span warrants it — keep short history raw."""
    if len(rows) <= 48:
        return None
    if not rows:
        return None
    from datetime import datetime
    t0 = datetime.fromisoformat(rows[0]["collected_at"])
    t1 = datetime.fromisoformat(rows[-1]["collected_at"])
    span_h = (t1 - t0).total_seconds() / 3600
    if span_h > 24 * 14:
        return 360   # 6 h buckets beyond 2 weeks
    if span_h > 24 * 3:
        return 60    # 1 h beyond 3 days
    if span_h > 48:
        return 10    # 10 min beyond 2 days
    if range_spec in ("7d", "30d") and len(rows) > 200:
        return 60
    return None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quieter logs
        print(f"[server] {self.address_string()} {fmt % args}")

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path) -> None:
        if not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path in ("/", "/dashboard", "/dashboard.html"):
            return self._file(_DASHBOARD)

        if path in ("/logs", "/logs.html"):
            return self._file(_LOGS)

        if path in ("/diagram", "/diagram.html"):
            return self._file(_DIAGRAM)

        try:
            if path == "/api/summary":
                return self._json(200, live_summary())

            if path == "/api/health":
                return self._json(200, system_health_snapshot())

            if path == "/api/diagram":
                return self._json(200, diagram_payload())

            if path == "/api/breakdown":
                force = (qs.get("force") or ["0"])[0] in ("1", "true")
                return self._json(200, fetch_breakdown(force=force))
        except FileNotFoundError as exc:
            return self._json(503, {"error": str(exc), "status": "unconfigured"})

        if path == "/api/logs/sources":
            return self._json(200, {
                "sources": [
                    {"id": s.id, "label": s.label, "kind": s.kind,
                     "description": s.description}
                    for s in list_sources()
                ],
            })

        if path == "/api/logs/archives":
            allowed = {s.id for s in list_sources()}
            source = (qs.get("source") or [""])[0]
            if source not in allowed:
                return self._json(400, {"error": f"Unknown source: {source}"})
            return self._json(200, list_archives(source))

        if path == "/api/logs/tail":
            allowed = {s.id for s in list_sources()}
            source = (qs.get("source") or ["gateway"])[0]
            if source not in allowed:
                return self._json(400, {"error": f"Unknown source: {source}"})
            try:
                lines = int((qs.get("lines") or ["150"])[0])
            except ValueError:
                lines = 150
            try:
                offset = int((qs.get("offset") or ["0"])[0])
            except ValueError:
                offset = 0
            since = (qs.get("since") or [None])[0]
            until = (qs.get("until") or [None])[0]
            archive = (qs.get("archive") or [None])[0]
            return self._json(200, tail_source(
                source, lines=lines, offset=offset, since=since, until=until,
                archive=archive,
            ))

        if path == "/api/meta":
            return self._json(200, {
                **meta(),
                "poll_interval_s": POLL_INTERVAL_S,
                "rem_batch": REM_BATCH,
                "rem_poll_s": REM_POLL_S,
                "neo4j_browser_url": NEO4J_BROWSER_URL,
                "ignored_outbox_ids": list(IGNORED_OUTBOX_IDS),
            })

        if path == "/api/history":
            range_spec = (qs.get("range") or ["6h"])[0]
            bucket = (qs.get("bucket") or ["auto"])[0]
            since = parse_range(range_spec)
            rows_raw = load_history(since=since, bucket_minutes=None)
            bucket_minutes = None
            if bucket == "auto":
                bucket_minutes = _auto_bucket_minutes(rows_raw, range_spec)
            elif bucket != "raw":
                try:
                    bucket_minutes = int(bucket)
                except ValueError:
                    bucket_minutes = None
            rows = load_history(since=since, bucket_minutes=bucket_minutes) if bucket_minutes else rows_raw
            return self._json(200, build_api_payload(
                rows, range_spec=range_spec, bucket_minutes=bucket_minutes,
            ))

        if path.startswith("/static/"):
            static_target = _safe_static_path(path)
            if static_target is None:
                return self.send_error(404)
            return self._file(static_target)

        self.send_error(404)


def run_server(block: bool = True) -> ThreadingHTTPServer:
    bootstrap_env()
    init_db()
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer((SERVER_HOST, SERVER_PORT), Handler)
    url = f"http://{SERVER_HOST}:{SERVER_PORT}/"
    print(f"Shared Memory Monitor → {url}")
    if block:
        httpd.serve_forever()
    return httpd


def start_server_thread() -> threading.Thread:
    httpd = run_server(block=False)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True, name="sm-telemetry-server")
    thread.start()
    return thread