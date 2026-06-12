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
    kind: str  # journal | file | jsonl
    path: str
    description: str


def log_dir() -> Path:
    return Path(os.path.expanduser(
        get("MEMORY_LOG_PATH", "~/.shared-memory/logs") or "~/.shared-memory/logs"
    ))


def audit_path() -> Path:
    p = get("AUDIT_LOG_PATH")
    if p:
        return Path(os.path.expanduser(p))
    return log_dir() / "rem-audit.jsonl"


def gateway_audit_path() -> Path:
    p = get("GATEWAY_AUDIT_LOG_PATH")
    if p:
        return Path(os.path.expanduser(p))
    return log_dir() / "gateway-audit.jsonl"


def list_sources() -> list[LogSource]:
    """Infrastructure log sources — gateway journal, REM audit, gateway request audit."""
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
            path=str(audit_path()),
            description="Structured JSON-lines audit of REM outbox reviews",
        ),
        LogSource(
            id="gateway_audit",
            label="Gateway audit",
            kind="jsonl",
            path=str(gateway_audit_path()),
            description="Per-request gateway audit — agent, route, status, latency",
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
        return {"lines": [], "offset": 0, "size": 0, "error": f"File not found: {path}"}
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
        return {"lines": [], "offset": 0, "size": 0, "error": f"Archive not found: {path}"}
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

    path = Path(src.path)
    if src.kind == "gz_jsonl":
        result = _tail_gz_jsonl(path, fetch_lines)
        kind = "jsonl"
    else:
        result = _tail_lines_text(path, fetch_lines, offset if not windowed else 0)
        kind = src.kind

    raw_lines = result.get("lines") or []
    entries = _filter_entries(_entries_from_lines(raw_lines, kind=kind), since=since_dt, until=until_dt)
    if windowed:
        entries = entries[-lines:]

    payload = {
        "source": source_id,
        "kind": kind,
        "path": str(path),
        "lines": [e["raw"] for e in entries],
        "since": since,
        "until": until,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    if result.get("error"):
        payload["error"] = result["error"]
    if not windowed:
        payload["offset"] = result.get("offset", 0)
        payload["size"] = result.get("size", 0)
    return payload