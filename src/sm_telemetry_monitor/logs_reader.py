"""Sole log client — all log lines on screen come through here.

Tails journalctl (gateway unit) and framework audit JSONL on disk.
Diagram agent-activity uses the same agent-audit bytes. No gateway log HTTP API.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
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


def _live_path(source_id: str) -> Path | None:
    if source_id == "rem_audit":
        return audit_path()
    if source_id == "agent_audit":
        return agent_audit_path()
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
    for path in root.glob("*.gz"):
        if not path.is_file():
            continue
        name = path.name
        if any(name.startswith(prefix) for prefix in names):
            archives.append(path)
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
    """Infrastructure log sources — gateway journal, REM audit, agent audit."""
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
    ]


def _parse_ts(value: str | None) -> datetime | None:
    if not value or value == "?":
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _ts_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


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
    if offset > size:
        offset = size
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
                "fetched_at": datetime.now(timezone.utc).isoformat(),
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
        "fetched_at": datetime.now(timezone.utc).isoformat(),
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


def _is_daemon_agent(agent: str | None) -> bool:
    if not agent:
        return True
    key = agent.strip().lower()
    if key in _DAEMON_AGENTS:
        return True
    return key.endswith("_daemon") or key.endswith("-daemon")


def _daemon_diagram_node(agent: str | None) -> str | None:
    """Map audit agent id to diagram node key for REM/NREM logic flows."""
    if not agent:
        return None
    key = agent.strip().lower()
    if key in ("rem_daemon", "rem"):
        return "rem_daemon"
    if key in ("consolidation", "nrem_daemon", "nrem"):
        return "nrem_daemon"
    return None


def classify_daemon_audit_io(path: str | None) -> str | None:
    """Classify daemon gateway proxy traffic for diagram logic flows."""
    route = (path or "").split("?", 1)[0]
    if route == "/v1/chat/completions":
        return "chat"
    if route == "/v1/embeddings":
        return "embeddings"
    if route.startswith("/v1/"):
        return "proxy"
    return None


def classify_agent_audit_io(method: str | None, path: str | None) -> str | None:
    """Classify an agent-audit request as read or write; None when not memory I/O."""
    route = (path or "").split("?", 1)[0]
    if not route or route.startswith("/v1/"):
        return None
    if route in _WRITE_PATHS:
        return "write"
    if route in _READ_PATHS:
        return "read"
    if any(route == p or route.startswith(p + "/") for p in _READ_PATH_PREFIXES):
        return "read"
    verb = (method or "GET").upper()
    if verb == "GET":
        return "read"
    if verb in ("POST", "PUT", "PATCH", "DELETE"):
        return "write"
    return None


def _iter_audit_files() -> list[Path]:
    live = agent_audit_path()
    files: list[Path] = []
    if live.exists():
        files.append(live)
    for archive in _archive_candidates("agent_audit"):
        if archive not in files:
            files.append(archive)
    return files


def _read_audit_lines(path: Path) -> list[str]:
    if not path.is_file():
        return []
    if path.suffix == ".gz" or path.name.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
            return [ln.strip() for ln in f if ln.strip()]
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


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
        for line in _read_audit_lines(path):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = _parse_ts(row.get("ts"))
            if not _in_window(ts, since_dt, until_dt):
                continue
            agent = row.get("agent")
            if _is_daemon_agent(agent):
                node = _daemon_diagram_node(str(agent) if agent else None)
                kind = classify_daemon_audit_io(row.get("path"))
                if node and kind:
                    bucket = daemon_logic.setdefault(node, {"chat": 0, "embeddings": 0, "proxy": 0})
                    bucket[kind] += 1
                continue
            io = classify_agent_audit_io(row.get("method"), row.get("path"))
            if not io:
                continue
            key = str(agent).strip()
            bucket = counts.setdefault(key, {"read": 0, "write": 0})
            bucket[io] += 1

    return {
        "since": since,
        "until": until,
        "agents": counts,
        "daemon_logic": daemon_logic,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }