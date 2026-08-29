"""Sole log client — all log lines on screen come through here.

Tails journalctl (gateway unit) and framework audit JSONL on disk.
Diagram agent-activity uses the same agent-audit bytes. No gateway log HTTP API.
"""

from __future__ import annotations

import bisect
import gzip
import json
import os
import re
import subprocess
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .env_loader import bootstrap_env, get

bootstrap_env()

def journal_unit() -> str:
    """User-scoped systemd unit for the hive-mind gateway (linger/user services)."""
    return get("SM_JOURNAL_UNIT", "hive-mind-gateway.service") or "hive-mind-gateway.service"


def journalctl_cmd(*, lines: int | None = None, since: str | None = None, until: str | None = None) -> list[str]:
    """Build journalctl argv for the gateway user unit."""
    cmd = ["journalctl", "--user", "-u", journal_unit(), "--no-pager", "-o", "short-iso"]
    if lines is not None:
        cmd.extend(["-n", str(lines)])
    if since:
        cmd.extend(["--since", since])
    if until:
        cmd.extend(["--until", until])
    return cmd

_JOURNAL_TS_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)",
)
_INNER_LOG_TS_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}),(\d{3,6})\b",
)


@dataclass(frozen=True)
class LogSource:
    id: str
    label: str
    kind: str  # journal | jsonl | gz_jsonl
    path: str
    description: str


def log_dir() -> Path:
    return Path(os.path.expanduser(
        get("MEMORY_LOG_PATH", "~/.shared-memory/logs") or "~/.shared-memory/logs"
    ))


def _log_root() -> Path:
    return log_dir().resolve()


def _basename(path: Path) -> str:
    return path.name


def audit_path() -> Path:
    p = get("AUDIT_LOG_PATH")
    if p:
        return Path(os.path.expanduser(p))
    return log_dir() / "rem-audit.jsonl"


def agent_audit_path() -> Path:
    """Live agent-audit jsonl. Reads GATEWAY_AUDIT_LOG_PATH (framework env name)."""
    p = get("GATEWAY_AUDIT_LOG_PATH")
    if p:
        return Path(os.path.expanduser(p))
    root = log_dir()
    agent = root / "agent-audit.jsonl"
    legacy = root / "gateway-audit.jsonl"
    if legacy.exists() and not agent.exists():
        return legacy
    return agent


def credential_audit_path() -> Path:
    """Live credential-audit jsonl.

    Unset → ``log_dir()/credential-audit.jsonl``.
    Empty/whitespace ``CREDENTIAL_AUDIT_LOG_PATH`` → disabled (no default; path
    does not exist). Differs from ``GATEWAY_AUDIT_LOG_PATH``, where empty falls
    through to the agent-audit default.
    """
    raw = get("CREDENTIAL_AUDIT_LOG_PATH")
    if raw is not None:
        stripped = raw.strip()
        if not stripped:
            # Explicit disable — never invent log_dir()/credential-audit.jsonl.
            return Path("/nonexistent/credential-audit.jsonl")
        return Path(os.path.expanduser(stripped))
    return log_dir() / "credential-audit.jsonl"


def _live_path(source_id: str) -> Path | None:
    if source_id == "rem_audit":
        return audit_path()
    if source_id == "agent_audit":
        return agent_audit_path()
    if source_id == "credential_audit":
        return credential_audit_path()
    return None


def _archive_candidates(source_id: str) -> list[Path]:
    root = _log_root()
    if not root.is_dir():
        return []

    live = _live_path(source_id)
    if live is None:
        return []

    names: set[str] = set()
    live_name = live.name
    names.add(live_name)
    if live_name.endswith(".jsonl"):
        names.add(live_name[:-6])  # stem without .jsonl

    archives: list[Path] = []
    seen: set[Path] = set()

    # Gzip rotates: name.jsonl.N.gz and legacy name.jsonl-YYYYMMDD.gz prefix match.
    for path in root.glob("*.gz"):
        if not path.is_file():
            continue
        name = path.name
        if any(name.startswith(prefix) for prefix in names):
            archives.append(path)
            seen.add(path)

    # Uncompressed numbered rotates (logrotate delaycompress): name.jsonl.1
    prefix = live_name + "."
    try:
        entries = list(root.iterdir())
    except OSError:
        entries = []
    for path in entries:
        if not path.is_file() or path in seen:
            continue
        name = path.name
        if name == live_name:
            continue
        if not name.startswith(prefix):
            continue
        rest = name[len(prefix):]
        if rest.isdigit():
            archives.append(path)
            seen.add(path)

    return sorted(archives, key=lambda p: p.name, reverse=True)


def list_archives(source_id: str) -> dict:
    """List live tail + rotated gzip archives for a file-based log source."""
    allowed = {s.id for s in list_sources()}
    if source_id not in allowed:
        return {"error": f"Unknown source: {source_id}"}

    if source_id == "gateway":
        return {"source": source_id, "live": None, "archives": []}

    live = _live_path(source_id)
    archives = _archive_candidates(source_id)
    live_info = None
    if live is not None:
        live_info = {
            "id": "live",
            "label": "Live",
            "available": live.exists(),
            "size": live.stat().st_size if live.exists() else 0,
        }

    return {
        "source": source_id,
        "live": live_info,
        "archives": [
            {
                "id": _basename(p),
                "label": p.name,
                "size": p.stat().st_size,
            }
            for p in archives
        ],
    }


def resolve_archive(source_id: str, archive_id: str) -> Path:
    """Map a client-supplied archive basename to a path under the log root."""
    if not archive_id or archive_id == "live":
        live = _live_path(source_id)
        if live is None:
            raise ValueError(f"Source {source_id} has no live file")
        return live

    if "/" in archive_id or "\\" in archive_id or archive_id in (".", ".."):
        raise ValueError("Invalid archive id")

    allowed = {_basename(p) for p in _archive_candidates(source_id)}
    if archive_id not in allowed:
        raise ValueError(f"Unknown archive: {archive_id}")

    resolved = (_log_root() / archive_id).resolve()
    if not resolved.is_relative_to(_log_root()):
        raise ValueError("Archive path escapes log directory")
    if not resolved.is_file():
        raise ValueError(f"Archive not found: {archive_id}")
    return resolved


def list_sources() -> list[LogSource]:
    """Infrastructure log sources — gateway journal, REM/agent/credential audits."""
    return [
        LogSource(
            id="gateway",
            label="Gateway daemons",
            kind="journal",
            path=journal_unit(),
            description="hive-mind gateway — live via journalctl --user -u",
        ),
        LogSource(
            id="rem_audit",
            label="REM audit",
            kind="jsonl",
            path=_basename(audit_path()),
            description="Structured JSON-lines audit of REM outbox reviews",
        ),
        LogSource(
            id="agent_audit",
            label="Agent audit",
            kind="jsonl",
            path=_basename(agent_audit_path()),
            description="Per-request agent audit — identity, route, status, latency",
        ),
        LogSource(
            id="credential_audit",
            label="Credential audit",
            kind="jsonl",
            path=_basename(credential_audit_path()),
            description="High-signal credential/fault events — origin, backend, request_id",
        ),
    ]


def _parse_ts(value) -> datetime | None:
    if not value or value == "?":
        return None
    if not isinstance(value, str):
        # A producer may log ts as an epoch int or a JSON object; an unreadable
        # stamp makes the row undatable, never an error for the whole scan.
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    # Always tz-aware: a producer writing a naive stamp would otherwise yield a
    # value that raises TypeError the moment it is compared with an aware one,
    # killing a whole scan over one row. Naive is read as UTC, as the rest of
    # the pipeline already assumes.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _ts_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


def _fractional_to_microsecond(digits: str) -> int:
    if len(digits) <= 3:
        return int(digits.ljust(3, "0")[:3]) * 1000
    return int(digits.ljust(6, "0")[:6])


def _enrich_journal_ts(ts_dt: datetime | None, message: str) -> datetime | None:
    """Use embedded Python log millis for filter windows when journal prefix is second-only."""
    if not ts_dt:
        return None
    m = _INNER_LOG_TS_RE.match(message)
    if not m:
        return ts_dt
    return ts_dt.replace(microsecond=_fractional_to_microsecond(m.group(3)))


def line_timestamp(line: str, *, kind: str) -> datetime | None:
    """Parse a timestamp from a raw line — used only for from/to filtering."""
    if kind == "jsonl":
        try:
            return _parse_ts(json.loads(line).get("ts"))
        except json.JSONDecodeError:
            pass
    if kind == "journal":
        m = _JOURNAL_TS_RE.match(line)
        if m:
            rest = line[m.end():]
            msg = rest.split(": ", 1)[-1] if ": " in rest else rest
            return _enrich_journal_ts(_parse_ts(m.group(1)), msg)
    m = _JOURNAL_TS_RE.match(line)
    if m:
        return _parse_ts(m.group(1))
    return None


def parse_log_entry(line: str, *, kind: str) -> dict:
    """Filter metadata for a raw log line — UI displays the line unchanged."""
    return {
        "ts": _ts_iso(line_timestamp(line, kind=kind)),
        "raw": line,
    }


def _entries_from_lines(lines: list[str], *, kind: str) -> list[dict]:
    return [parse_log_entry(ln, kind=kind) for ln in lines if ln]


def _in_window(ts: datetime | None, since: datetime | None, until: datetime | None) -> bool:
    if ts is None:
        return since is None and until is None
    if since and ts < since:
        return False
    if until and ts > until:
        return False
    return True


def _filter_entries(
    entries: list[dict],
    *,
    since: datetime | None,
    until: datetime | None,
) -> list[dict]:
    if not since and not until:
        return entries
    out: list[dict] = []
    for entry in entries:
        ts = _parse_ts(entry.get("ts"))
        if _in_window(ts, since, until):
            out.append(entry)
    return out


def _tail_lines_text(path: Path, lines: int, offset: int = 0) -> dict:
    if not path.exists():
        return {"lines": [], "offset": 0, "size": 0, "error": f"File not found: {_basename(path)}"}
    size = path.stat().st_size
    offset = min(offset, size)
    collected: list[str] = []
    if offset > 0 and offset < size:
        with path.open("r", errors="replace") as f:
            f.seek(offset)
            collected = f.read().splitlines()
    else:
        with path.open("rb") as f:
            f.seek(0, 2)
            end = f.tell()
            block = 8192
            buf = b""
            pos = end
            while pos > 0 and len(buf.splitlines()) <= lines:
                read_size = min(block, pos)
                pos -= read_size
                f.seek(pos)
                buf = f.read(read_size) + buf
            collected = buf.decode("utf-8", errors="replace").splitlines()[-lines:]
    return {"lines": collected, "offset": size, "size": size}


def _tail_gz_jsonl(path: Path, lines: int) -> dict:
    if not path.exists():
        return {"lines": [], "offset": 0, "size": 0, "error": f"Archive not found: {_basename(path)}"}
    out: list[str] = []
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(line)
    return {"lines": out[-lines:], "offset": path.stat().st_size, "size": path.stat().st_size}


def tail_source(
    source_id: str,
    *,
    lines: int = 150,
    offset: int = 0,
    since: str | None = None,
    until: str | None = None,
    archive: str | None = None,
) -> dict:
    sources = {s.id: s for s in list_sources()}
    src = sources.get(source_id)
    if not src:
        return {"error": f"Unknown source: {source_id}", "sources": [s.id for s in sources.values()]}

    since_dt = _parse_ts(since) if since else None
    until_dt = _parse_ts(until) if until else None
    windowed = bool(since_dt or until_dt)
    fetch_lines = max(lines, 2000) if windowed else lines

    if src.kind == "journal":
        cmd = journalctl_cmd(lines=fetch_lines, since=since, until=until)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            raw = [ln for ln in proc.stdout.splitlines() if ln.strip()]
            if proc.returncode != 0 and not raw:
                return {"error": proc.stderr.strip() or "journalctl failed", "lines": []}
            entries = _filter_entries(_entries_from_lines(raw, kind="journal"), since=since_dt, until=until_dt)
            if windowed:
                entries = entries[-lines:]
            lines_out = [e["raw"] for e in entries]
            return {
                "source": source_id,
                "kind": "journal",
                "lines": lines_out,
                "offset": len(lines_out),
                "since": since,
                "until": until,
                "fetched_at": datetime.now(UTC).isoformat(),
            }
        except FileNotFoundError:
            return {"error": "journalctl not available", "lines": []}
        except subprocess.TimeoutExpired:
            return {"error": "journalctl timed out", "lines": []}

    try:
        if archive and archive != "live":
            path = resolve_archive(source_id, archive)
        else:
            path = resolve_archive(source_id, "live")
    except ValueError as exc:
        return {"source": source_id, "error": str(exc), "lines": []}

    use_gz = path.suffix == ".gz" or path.name.endswith(".gz")
    if use_gz:
        result = _tail_gz_jsonl(path, fetch_lines)
        kind = "jsonl"
        incremental = False
    else:
        result = _tail_lines_text(path, fetch_lines, offset if not windowed else 0)
        kind = src.kind
        incremental = True

    raw_lines = result.get("lines") or []
    entries = _filter_entries(_entries_from_lines(raw_lines, kind=kind), since=since_dt, until=until_dt)
    if windowed:
        entries = entries[-lines:]

    live = _live_path(source_id)
    archive_id = "live" if live and path.resolve() == live.resolve() else _basename(path)
    payload = {
        "source": source_id,
        "kind": kind,
        "archive": archive_id,
        "lines": [e["raw"] for e in entries],
        "since": since,
        "until": until,
        "fetched_at": datetime.now(UTC).isoformat(),
    }
    if result.get("error"):
        payload["error"] = result["error"]
    if incremental and not windowed:
        payload["offset"] = result.get("offset", 0)
        payload["size"] = result.get("size", 0)
    return payload


_CONSOLIDATION_MARKERS = (
    "consolidation run [",
    "consolidation health refresh failed",
    "consolidation_runs:",
    "insight cycle:",
    "deferring consolidation",
    "deferring sweep",
    "backup in progress — deferring",
    "inference gpu busy — deferring",
    "consolidationdaemon:",
    "marked ",
    " orphaned in-flight",
)


def is_consolidation_line(text: str) -> bool:
    """True when a gateway journal line relates to REM/NREM consolidation observability."""
    low = (text or "").lower()
    if "consolidation" in low:
        return True
    if "insight cycle:" in low:
        return True
    if "deferring consolidation" in low or "deferring sweep" in low:
        return True
    if "backup in progress — deferring" in low:
        return True
    if "nrem:" in low and "deferring" in low:
        return True
    if "rem:" in low and "deferring enrichment" in low:
        return True
    return any(marker in low for marker in _CONSOLIDATION_MARKERS)


def is_inference_backpressure(text: str) -> bool:
    """True for REM/NREM lines that are GPU-busy back-pressure, not real faults.

    When the GPU is busy (e.g. a user chatting directly with :5000), REM/NREM
    calls to the LLM time out or 503; the daemon logs these — sometimes at ERROR
    — but they are self-healing: the cycle is skipped/deferred, ledger rows stay
    open, and the next sweep retries (the same nvtop gate the defer logic uses).
    They should read as deferred warnings, never hard errors. A genuine crash
    (traceback / "crashed after") is excluded so real failures still surface.
    """
    low = (text or "").lower()
    if "crashed" in low or "traceback" in low:
        return False
    has_inference_ctx = any(
        k in low for k in ("llm", "inference", "insight", "synthes", "enrichment")
    )
    if not has_inference_ctx:
        return False
    return any(
        marker in low
        for marker in (
            "gpu busy",
            "pool has no free slot",
            "llm failed — skipping",
            "llm failed - skipping",
            "timeout",
            "timed out",
            "backend unreachable",
            "503",
            "next sweep retries",
            "ledger rows stay open",
        )
    )


def classify_gateway_line(text: str) -> str:
    """Severity class for gateway journal lines — mirrors logs.html classify()."""
    low = (text or "").lower()
    if "crashed after" in low and "consolidation run" in low:
        return "line-err"
    if "consolidation health refresh failed" in low:
        return "line-warn"
    if "consolidation_runs:" in low and ("orphan" in low or "could not" in low):
        return "line-warn"
    if is_inference_backpressure(low):
        return "line-warn"
    if "error" in low or "failed" in low or "critical" in low:
        return "line-err"
    if "warn" in low or "defer" in low:
        return "line-warn"
    if "consolidation run [" in low and "completed" in low:
        return "line-info"
    if "insight cycle:" in low:
        return "line-info"
    if "info" in low or "done" in low or "applied" in low:
        return "line-info"
    return ""


_DAEMON_AGENTS = frozenset({
    "monitor", "rem_daemon", "rem", "nrem_daemon", "nrem", "consolidation",
    "coordinator", "gateway", "hive_mind", "embedder", "reranker", "proxy",
})

# Exact-path write routes (POST bodies that mutate memory). Search is read-only
# despite POST (JSON body); see _READ_PATHS / prefix rules in classify_agent_audit_io.
_WRITE_PATHS = frozenset({
    "/memory/save",
    "/memory/retrospective",
    "/memory/supersede",
    "/memory/review_hold",
    "/memory/relations/label",
})

_READ_PATHS = frozenset({
    "/memory/telemetry",
    "/memory/graph",
    "/memory/search",
    "/memory/relations/review",
    "/health",
})

# Prefixes: lineage is GET /memory/status/{pg_id}; keep in sync with framework routes.
_READ_PATH_PREFIXES = (
    "/memory/status",
)


def _audit_agent_id(agent) -> str:
    """Agent id of an audit row, tolerating a writer that wraps it in JSON.

    An MCP client may log `agent` as `["opencode"]` rather than `"opencode"`
    (fact:1803). Unwrapping a single-element sequence keeps that client on its
    own diagram chip. Any other shape names no agent this tool can attribute
    traffic to, so it yields "" and the row goes uncounted — the monitor
    reports what the logs say, it does not invent an agent from a repr.
    """
    if isinstance(agent, str):
        return agent.strip()
    if isinstance(agent, (list, tuple)) and len(agent) == 1:
        return _audit_agent_id(agent[0])
    if isinstance(agent, (int, float)) and not isinstance(agent, bool):
        return str(agent)
    return ""


def _audit_route(path) -> str:
    """Route of an audit row, tolerating a writer that emits a non-string path.

    A client is free to log `path` as an object/array (OpenCode MCP does); a
    scan over shared bytes must not fault on one malformed producer.
    """
    if not path:
        return ""
    return str(path).split("?", 1)[0]


def _is_daemon_agent(agent) -> bool:
    if not agent:
        return True
    key = str(agent).strip().lower()
    if key in _DAEMON_AGENTS:
        return True
    return key.endswith("_daemon") or key.endswith("-daemon")


def _daemon_diagram_node(agent) -> str | None:
    """Map audit agent id to diagram node key for REM/NREM logic flows."""
    if not agent:
        return None
    key = str(agent).strip().lower()
    if key in ("rem_daemon", "rem"):
        return "rem_daemon"
    if key in ("consolidation", "nrem_daemon", "nrem"):
        return "nrem_daemon"
    return None


def classify_daemon_audit_io(path) -> str | None:
    """Classify daemon gateway proxy traffic for diagram logic flows."""
    route = _audit_route(path)
    if route == "/v1/chat/completions":
        return "chat"
    if route == "/v1/embeddings":
        return "embeddings"
    if route.startswith("/v1/"):
        return "proxy"
    return None


def classify_agent_audit_io(method, path) -> str | None:
    """Classify an agent-audit request as read or write; None when not memory I/O."""
    route = _audit_route(path)
    if not route or route.startswith("/v1/"):
        return None
    if route in _WRITE_PATHS:
        return "write"
    if route in _READ_PATHS:
        return "read"
    if any(route == p or route.startswith(p + "/") for p in _READ_PATH_PREFIXES):
        return "read"
    verb = (str(method) if method else "GET").upper()
    if verb == "GET":
        return "read"
    if verb in ("POST", "PUT", "PATCH", "DELETE"):
        return "write"
    return None


def _iter_audit_files(since: datetime | None = None) -> list[Path]:
    live = agent_audit_path()
    files: list[Path] = []
    if live.exists():
        files.append(live)
    for archive in _archive_candidates("agent_audit"):
        if archive not in files:
            files.append(archive)
    if since is None:
        return files
    # A rotated audit file is append-only and then sealed, so its mtime is the
    # instant of its last row. That lets a bounded window skip an archive
    # without parsing it at all — the difference between a cold load reading
    # one live file and reading every rotation ever kept.
    #
    # mtime is only a proxy, though: it comes from the writer's filesystem
    # while `ts` comes from the writer's clock, and the two disagree under a
    # naive local stamp, a container clock, or an NTP step. So the live file is
    # never skipped, an already-parsed file is judged on its real contents, and
    # anything else gets a slack margin rather than a hard edge. Skipping a
    # file that holds in-window rows would blank the agent layer and look
    # exactly like an idle system.
    kept: list[Path] = []
    for path in files:
        if path == live:
            kept.append(path)
            continue
        cached = _AUDIT_CACHE.get(str(path))
        if cached is not None and cached[2] is not None:
            if cached[2][1] >= since:
                kept.append(path)
            continue
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        except OSError:
            continue
        if mtime >= since - _AUDIT_MTIME_SLACK:
            kept.append(path)
    return kept


def _read_audit_lines(path: Path) -> list[str]:
    if not path.is_file():
        return []
    if path.suffix == ".gz" or path.name.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
            return [ln.strip() for ln in f if ln.strip()]
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


_AUDIT_CACHE: dict[str, tuple[tuple[int, int], list[tuple], tuple | None]] = {}
_AUDIT_CACHE_LOCK = threading.Lock()
# Rotation mints a new filename every cycle, so the key set would otherwise
# grow for the life of the process. Holding the live file plus a rotation set
# is what the scrubber actually re-reads; older entries just re-parse on demand.
_AUDIT_CACHE_MAX_FILES = 32
# The agent id is untrusted text from another process, so both how many distinct
# ids the diagram will draw and how long one may be are capped here rather than
# left to whatever a client decides to log.
ROSTER_MAX_AGENTS = 12
AGENT_ID_MAX_LEN = 64
# Reserved, and deliberately not a name any client could log: an agent that
# actually called itself "other" would otherwise merge with the fold row and
# silently hide how many agents it stood for.
OTHER_AGENT_ID = "__other__"
# The caller chooses the window, so the number of intervals it can ask to have
# bucketed is bounded here rather than by whatever it sends.
SERIES_MAX_INTERVALS = 2000
# How far an archive's mtime may sit before a window and still be read. mtime
# is the filesystem's clock and `ts` is the writer's; a naive local stamp can
# put them a whole timezone apart, and reading one extra rotation is far
# cheaper than blanking the agent layer for rows that were there all along.
_AUDIT_MTIME_SLACK = timedelta(hours=26)


def _audit_entry(path: Path) -> tuple[list[tuple], tuple | None]:
    """Parsed rows for one audit file plus its (min_ts, max_ts) span, memoised.

    The span lets a caller skip a whole archive whose time range misses the
    window without touching its rows — 7 of 15 files on a 7-day view here.
    """
    try:
        stat = path.stat()
    except OSError:
        return [], None
    stamp = (stat.st_mtime_ns, stat.st_size)
    key = str(path)
    with _AUDIT_CACHE_LOCK:
        cached = _AUDIT_CACHE.get(key)
        if cached is not None and cached[0] == stamp:
            return cached[1], cached[2]

    rows: list[tuple] = []
    for line in _read_audit_lines(path):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        rows.append((
            _parse_ts(row.get("ts")),
            _audit_agent_id(row.get("agent")),
            row.get("method"),
            _audit_route(row.get("path")),
        ))
    stamps = [r[0] for r in rows if r[0] is not None]
    span = (min(stamps), max(stamps)) if stamps else None

    with _AUDIT_CACHE_LOCK:
        _AUDIT_CACHE.pop(key, None)
        _AUDIT_CACHE[key] = (stamp, rows, span)
        while len(_AUDIT_CACHE) > _AUDIT_CACHE_MAX_FILES:
            _AUDIT_CACHE.pop(next(iter(_AUDIT_CACHE)))
    return rows, span


def _span_overlaps(span, since, until) -> bool:
    """Whether a file's time span can contain a row inside [since, until]."""
    if span is None:
        return True
    lo, hi = span
    if since and hi < since:
        return False
    if until and lo > until:
        return False
    return True


def _audit_first_ts(path: Path, probe_lines: int = 50) -> datetime | None:
    """Timestamp of the first datable row in a file, reading only its head."""
    try:
        if path.suffix == ".gz" or path.name.endswith(".gz"):
            handle = gzip.open(path, "rt", encoding="utf-8", errors="replace")
        else:
            handle = path.open("r", encoding="utf-8", errors="replace")
        with handle as fh:
            for i, line in enumerate(fh):
                if i >= probe_lines:
                    return None
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                ts = _parse_ts(row.get("ts"))
                if ts is not None:
                    return ts
    except OSError:
        return None
    return None


def audit_coverage() -> dict:
    """Oldest and newest audit row the corpus still holds.

    Rotation is the framework's, not the monitor's, so the dashboard must be
    able to say 'the log for this interval is gone' rather than 'nothing
    happened' — the two are different claims. Answered from the head of the
    oldest file and the tail of the newest rather than by parsing the corpus:
    this is called on every history load, and the whole point of a bounded
    window is that a load never has to read the archives.
    """
    # Ordered by what the files CONTAIN, not by mtime: a restored or copied
    # archive carries a newer mtime than its rows, and ordering on that can put
    # `since` months ahead of the real oldest row — which would caption every
    # interval on screen as rotated away while the rows sit in the file.
    heads: list[tuple[datetime, Path]] = []
    for path in _iter_audit_files():
        first = _audit_first_ts(path)
        if first is not None:
            heads.append((first, path))
    if not heads:
        return {"since": None, "until": None}
    heads.sort(key=lambda h: h[0])
    since = heads[0][0]
    newest_span = _audit_entry(heads[-1][1])[1]
    until = newest_span[1] if newest_span else None
    if until is not None and until < since:
        until = None
    return {"since": _ts_iso(since), "until": _ts_iso(until)}


def _audit_rows(path: Path) -> list[tuple]:
    """Parsed (ts, agent, method, path) tuples for one audit file, memoised.

    Parsing is keyed on (mtime_ns, size): a rotated or appended file re-parses,
    an untouched one costs nothing. That makes the archives — the
    bulk of the corpus — free; the live file the gateway is appending to still
    re-parses whenever it has grown since the last call.
    """
    return _audit_entry(path)[0]


def agent_activity(
    *,
    since: str | None = None,
    until: str | None = None,
) -> dict:
    """Summarize agent memory I/O and daemon /v1 proxy counts for a time window."""
    since_dt = _parse_ts(since) if since else None
    until_dt = _parse_ts(until) if until else None
    counts: dict[str, dict[str, int]] = {}
    daemon_logic: dict[str, dict[str, int]] = {}

    for path in _iter_audit_files():
        for ts, agent, method, route in _audit_rows(path):
            if not _in_window(ts, since_dt, until_dt):
                continue
            if _is_daemon_agent(agent):
                node = _daemon_diagram_node(agent)
                kind = classify_daemon_audit_io(route)
                if node and kind:
                    bucket = daemon_logic.setdefault(node, {"chat": 0, "embeddings": 0, "proxy": 0})
                    bucket[kind] += 1
                continue
            io = classify_agent_audit_io(method, route)
            if not io:
                continue
            bucket = counts.setdefault(agent, {"read": 0, "write": 0})
            bucket[io] += 1

    return {
        "since": since,
        "until": until,
        "agents": counts,
        "daemon_logic": daemon_logic,
        "fetched_at": datetime.now(UTC).isoformat(),
    }


def agent_activity_series(timestamps: list[str]) -> dict:
    """Per-interval agent and daemon activity for a whole run of poll stamps.

    The diagram scrubber's positions ARE these timestamps, so one bucketed pass
    answers every slider position at once — replacing one full-corpus query per
    position. Interval i covers (timestamps[i-1], timestamps[i]], keyed by its
    own end stamp rather than by index so a caller that obtained its stamps
    from a different request cannot silently read every interval off by one —
    `range` resolves against now, and a poll landing between two requests
    shifts the whole run. A row landing exactly on a stamp closes the interval
    ending there; unlike `_in_window`, which is closed at both ends, it is
    therefore counted once rather than in both adjacent windows.
    """
    stamps = [_parse_ts(t) for t in timestamps]
    pairs = [(s, timestamps[i]) for i, s in enumerate(stamps) if s is not None]
    empty = {
        "intervals": {},
        "roster": [],
        "coverage": audit_coverage(),
        "fetched_at": datetime.now(UTC).isoformat(),
    }
    if len(pairs) < 2:
        return empty

    ordered = sorted(pairs, key=lambda p: p[0])[-SERIES_MAX_INTERVALS:]
    keys = [p[0] for p in ordered]
    since, until = keys[0], keys[-1]

    # Materialised once, then walked twice. Re-scanning would let the gateway
    # append between the passes, so pass 2 could see an agent pass 1 never
    # ranked — which lands its traffic in a fold bucket the roster never
    # declared, breaking the key space the client looks chips up by.
    # bisect_left gives the first stamp >= ts, i.e. the interval this row closes.
    hits: list[tuple[str, object, object, object]] = []
    for path in _iter_audit_files(since):
        rows, span = _audit_entry(path)
        if not _span_overlaps(span, since, until):
            continue
        for ts, agent, method, route in rows:
            if ts is None or ts <= since or ts > until:
                continue
            idx = bisect.bisect_left(keys, ts)
            if idx <= 0 or idx >= len(keys):
                continue
            hits.append((ordered[idx][1], agent, method, route))

    # Pass 1 — who is actually here. `agent` is untrusted text written by other
    # processes, so the roster is capped by traffic and the tail folded into one
    # bucket: without that, a client minting a fresh id per request would mint a
    # chip per request.
    totals: dict[str, dict[str, int]] = {}
    for _stamp, agent, method, route in hits:
        if _is_daemon_agent(agent):
            continue
        io = classify_agent_audit_io(method, route)
        if not io:
            continue
        totals.setdefault(agent[:AGENT_ID_MAX_LEN], {"read": 0, "write": 0})[io] += 1

    ranked = sorted(totals.items(), key=lambda kv: (-(kv[1]["read"] + kv[1]["write"]), kv[0]))
    named = {a for a, _ in ranked[:ROSTER_MAX_AGENTS]}
    folded = len(ranked) - len(named)

    def bucket_for(agent: str) -> str:
        key = agent[:AGENT_ID_MAX_LEN]
        return key if key in named else OTHER_AGENT_ID

    # Pass 2 — per-interval counts, in the same key space as the roster.
    intervals: dict[str, dict] = {}
    for stamp, agent, method, route in hits:
        entry = intervals.setdefault(stamp, {})
        if _is_daemon_agent(agent):
            node = _daemon_diagram_node(agent)
            kind = classify_daemon_audit_io(route)
            if not (node and kind):
                continue
            logic = entry.setdefault("daemon_logic", {})
            logic.setdefault(node, {"chat": 0, "embeddings": 0, "proxy": 0})[kind] += 1
            continue
        io = classify_agent_audit_io(method, route)
        if not io:
            continue
        agents = entry.setdefault("agents", {})
        agents.setdefault(bucket_for(agent), {"read": 0, "write": 0})[io] += 1

    # An interval holding only traffic we do not render must not read as active.
    intervals = {k: v for k, v in intervals.items() if v}

    roster = [{"id": a, **c} for a, c in ranked if a in named]
    if folded > 0:
        tail = {"read": 0, "write": 0}
        for a, c in ranked:
            if a in named:
                continue
            tail["read"] += c["read"]
            tail["write"] += c["write"]
        roster.append({"id": OTHER_AGENT_ID, "folded_agents": folded, **tail})
    return {**empty, "intervals": intervals, "roster": roster}