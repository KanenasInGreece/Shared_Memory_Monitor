"""Validate monitor ↔ gateway wiring without printing secrets."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import httpx

from .bridge import API_VERSION, get_health, get_telemetry, query_graph
from .config import DATA_DIR, DB_FILE, ROOT, STATIC_DIR
from .env_loader import (
    MONITOR_ROOT,
    _env_file_candidates,
    agent_token_source,
    bootstrap_env,
    get,
    memory_bridge_scripts_dir,
)
from .sanitize import sanitize_error
from .logs_reader import journal_unit, journalctl_cmd
from .store import init_db, meta

FEATURE_MATRIX = (
    ("dashboard_history", "telemetry_cache", "Charts from cached GET /memory/telemetry polls"),
    ("dashboard_live", "coordinator", "Hero, sidebar backlog, pipeline (telemetry poll)"),
    ("api_health", "coordinator", "Infrastructure grid (/api/health)"),
    ("api_breakdown_neo4j", "neo4j", "Schema drawer — graph panels"),
    ("api_breakdown_postgres", "telemetry", "Schema drawer — Postgres panels (telemetry.breakdown)"),
    ("logs_files", "log_paths", "REM audit JSONL tab"),
    ("logs_journal", "journal", "Gateway daemons tab (journalctl --user -u)"),
    ("outbox_ignore_filter", "coordinator", "Baseline outbox ignore when SM_IGNORED_OUTBOX_IDS set"),
)


def _key_status() -> dict[str, str]:
    """Presence of config keys — never returns values."""
    bootstrap_env()
    out: dict[str, str] = {}
    for key in (
        "SHARED_MEMORY_ROOT", "SM_GATEWAY_ENV", "SM_MEMORY_BRIDGE", "SM_SKILL_ROOT",
        "COORDINATOR_URL", "AGENT_TOKEN",
        "MEMORY_LOG_PATH", "AUDIT_LOG_PATH", "NEO4J_BROWSER_URL",
        "SM_JOURNAL_UNIT", "SM_IGNORED_OUTBOX_IDS",
    ):
        val = (get(key) or os_environ_get(key) or "").strip()
        if not val:
            out[key] = "missing"
        elif key == "AGENT_TOKEN":
            out[key] = "set"
        else:
            out[key] = "set"
    src = agent_token_source()
    out["agent_token_source"] = src or "unknown"
    return out


def os_environ_get(key: str) -> str | None:
    import os
    return os.environ.get(key)


def _env_sources() -> list[dict[str, Any]]:
    bootstrap_env()
    sources: list[dict[str, Any]] = []
    monitor_env = (MONITOR_ROOT / ".env").resolve()
    for path in _env_file_candidates():
        if not path.is_file():
            continue
        keys = sorted(_parse_keys_present(path))
        sources.append({
            "path": str(path.resolve()),
            "kind": "monitor" if path.resolve() == monitor_env else "framework",
            "keys_present": keys,
        })
    monitor_path = monitor_env
    if monitor_path.is_file() and not any(s["path"] == str(monitor_path) for s in sources):
        sources.insert(0, {
            "path": str(monitor_path),
            "kind": "monitor",
            "keys_present": sorted(_parse_keys_present(monitor_path)),
        })
    return sources


def _parse_keys_present(path: Path) -> set[str]:
    from .env_loader import _parse_env_file
    return set(_parse_env_file(path).keys())


def _gateway_client() -> dict[str, Any]:
    bootstrap_env()
    scripts = memory_bridge_scripts_dir()
    return {
        "mode": "httpx",
        "coordinator_url": get("COORDINATOR_URL", "http://localhost:8888"),
        "framework_scripts": str(scripts.resolve()) if scripts else None,
        "agent_token_source": agent_token_source(),
    }


def _check_coordinator() -> dict[str, Any]:
    raw = get_health()
    ok = raw.get("status") not in ("unreachable", "error") and "error" not in raw
    srv = raw.get("api_version")
    if srv is None:
        compat = "unknown"
    elif srv == API_VERSION:
        compat = "ok"
    else:
        compat = "incompatible"

    # Non-secret /health.config.llm_backends (v0.6.1+; placement ≥0.8.9).
    cfg = raw.get("config") if isinstance(raw.get("config"), dict) else {}
    backends = cfg.get("llm_backends") if isinstance(cfg.get("llm_backends"), list) else []
    n_backends = 0
    n_local = 0
    n_external = 0
    has_placement = False
    for b in backends:
        if not isinstance(b, dict) or not b.get("url"):
            continue
        n_backends += 1
        if "has_credential" in b:
            has_placement = True
            if b.get("has_credential") is True:
                n_external += 1
            elif b.get("has_credential") is False:
                n_local += 1
    pool = raw.get("llm_pool")
    has_llm_pool = isinstance(pool, dict) and bool(pool)

    return {
        "ok": ok,
        "status": raw.get("status"),
        "version": raw.get("version"),
        "api_version": srv,
        "client_api_version": API_VERSION,
        "compat": compat,
        "error": sanitize_error(raw.get("error") or raw.get("message")) or None,
        "has_llm_config": n_backends > 0,
        "llm_backend_count": n_backends,
        "has_llm_pool": has_llm_pool,
        "has_llm_placement": has_placement,
        "llm_local_count": n_local if has_placement else None,
        "llm_external_count": n_external if has_placement else None,
        "has_consolidation_health": isinstance(raw.get("consolidation"), dict),
        "inference_busy": raw.get("inference_busy"),
    }


def _check_telemetry() -> dict[str, Any]:
    payload = get_telemetry()
    ok = payload.get("status") == "success"
    err = payload.get("message") or payload.get("error")
    t = payload.get("telemetry") or {}
    nrem = t.get("nrem") if isinstance(t.get("nrem"), dict) else {}
    bd = t.get("breakdown") if isinstance(t.get("breakdown"), dict) else {}
    cons = t.get("consolidation") if isinstance(t.get("consolidation"), dict) else {}
    eg = t.get("entity_graph") if isinstance(t.get("entity_graph"), dict) else {}
    lat = t.get("latency") if isinstance(t.get("latency"), dict) else {}
    spine = t.get("spine") if isinstance(t.get("spine"), dict) else {}
    compliance = t.get("compliance") if isinstance(t.get("compliance"), dict) else {}
    return {
        "ok": ok,
        "status": payload.get("status"),
        "error": sanitize_error(str(err)) if err else None,
        "has_nrem": bool(nrem) and "error" not in nrem,
        "has_breakdown": bool(bd) and "error" not in bd,
        "has_consolidation": bool(cons) and "error" not in cons,
        "has_entity_graph": bool(eg) and "error" not in eg,
        "has_latency": bool(lat) and "error" not in lat,
        "has_spine": bool(spine) and "error" not in spine,
        "has_compliance": bool(compliance) and "error" not in compliance,
    }


def _check_neo4j_breakdown() -> dict[str, Any]:
    result = query_graph("RETURN 1 AS ok LIMIT 1")
    if isinstance(result, dict) and result.get("status") == "error":
        return {"ok": False, "error": sanitize_error(result.get("message"))}
    records = result if isinstance(result, list) else (result.get("records") if isinstance(result, dict) else [])
    return {"ok": bool(records), "error": None if records else "empty graph response"}


def _check_read_role() -> dict[str, Any]:
    """Read token should allow telemetry and reject writes."""
    bootstrap_env()
    base = get("COORDINATOR_URL", "http://localhost:8888") or "http://localhost:8888"
    token = (get("AGENT_TOKEN") or "").strip()
    if not token:
        return {"ok": False, "telemetry_ok": False, "write_denied": False, "error": "AGENT_TOKEN missing"}
    headers = {"Authorization": f"Bearer {token}", "X-SM-Api-Version": str(API_VERSION)}
    try:
        with httpx.Client(timeout=8.0) as client:
            t = client.get(f"{base}/memory/telemetry", headers=headers)
            w = client.post(
                f"{base}/memory/save",
                json={"content": "monitor probe", "metadata": {"source": "monitor_probe"}},
                headers=headers,
            )
        telemetry_ok = t.status_code == 200
        write_denied = w.status_code in (401, 403)
        ok = telemetry_ok and write_denied
        err = None
        if not telemetry_ok:
            err = f"telemetry HTTP {t.status_code}"
        elif not write_denied:
            err = f"write probe not denied (HTTP {w.status_code}) — token may be over-privileged"
        return {
            "ok": ok,
            "telemetry_ok": telemetry_ok,
            "write_denied": write_denied,
            "error": err,
        }
    except Exception as exc:
        return {"ok": False, "telemetry_ok": False, "write_denied": False, "error": sanitize_error(str(exc))}


def _check_log_paths() -> dict[str, Any]:
    from .logs_reader import audit_path, list_sources, log_dir

    ld = log_dir()
    sources = list_sources()
    file_sources = [s for s in sources if s.kind in ("jsonl", "gz_jsonl")]
    return {
        "log_dir": str(ld),
        "log_dir_exists": ld.is_dir(),
        "audit_path": str(audit_path()),
        "audit_exists": audit_path().is_file(),
        "file_sources": [
            {"id": s.id, "exists": Path(s.path).exists() if s.kind != "journal" else None}
            for s in file_sources
        ],
    }


def _check_journal() -> dict[str, Any]:
    unit = journal_unit()
    if not shutil.which("journalctl"):
        return {"ok": False, "unit": unit, "scope": "user", "error": "journalctl not installed"}
    try:
        proc = subprocess.run(
            journalctl_cmd(lines=1),
            capture_output=True, text=True, timeout=8, check=False,
        )
        ok = proc.returncode == 0 or bool(proc.stdout.strip())
        return {
            "ok": ok,
            "unit": unit,
            "scope": "user",
            "error": None if ok else sanitize_error(proc.stderr.strip() or f"exit {proc.returncode}"),
        }
    except Exception as exc:
        return {"ok": False, "unit": unit, "scope": "user", "error": sanitize_error(str(exc))}


def _check_local_data() -> dict[str, Any]:
    init_db()
    m = meta()
    return {
        "data_dir": str(DATA_DIR),
        "db_exists": DB_FILE.is_file(),
        "samples": m.get("count", 0),
        "last_at": m.get("last_at"),
    }


def _feature_readiness(checks: dict[str, Any]) -> list[dict[str, Any]]:
    keys = checks["keys"]
    c = checks["connectivity"]
    logs = checks["logs"]
    data = checks["local_data"]
    token_src = keys.get("agent_token_source", "unknown")

    def ready(feature: str) -> tuple[bool, str]:
        if feature in ("local", "telemetry_cache"):
            if data["samples"] > 0:
                return True, "ok"
            return False, "needs poll loop history"
        if feature == "coordinator":
            if keys.get("AGENT_TOKEN") != "set":
                return False, "set AGENT_TOKEN in monitor .env"
            if token_src and token_src.startswith("skill:"):
                return False, f"borrowed agent token ({token_src}) — use monitor .env"
            if not c["coordinator"]["ok"]:
                return False, c["coordinator"].get("error") or "coordinator unreachable"
            if not c["telemetry"]["ok"]:
                return False, c["telemetry"].get("error") or "telemetry poll failed"
            return True, "ok"
        if feature == "neo4j":
            if keys.get("AGENT_TOKEN") != "set":
                return False, "set AGENT_TOKEN"
            if not c["neo4j_breakdown"]["ok"]:
                return False, c["neo4j_breakdown"].get("error") or "graph query failed"
            return True, "ok"
        if feature == "telemetry":
            if not c["telemetry"]["ok"]:
                return False, c["telemetry"].get("error") or "telemetry poll failed"
            if not c["telemetry"].get("has_breakdown"):
                return False, "telemetry.breakdown missing — gateway needs Phase 3 enrichment"
            return True, "ok"
        if feature == "log_paths":
            if logs["log_paths"]["log_dir_exists"]:
                return True, "ok"
            return False, f"log dir missing: {logs['log_paths']['log_dir']} (optional: SHARED_MEMORY_ROOT)"
        if feature == "journal":
            if logs["journal"]["ok"]:
                return True, "ok"
            return False, logs["journal"].get("error") or "journal unavailable"
        return False, "unknown"

    features = []
    for fid, dep, desc in FEATURE_MATRIX:
        ok, reason = ready(dep)
        features.append({"id": fid, "ok": ok, "depends_on": dep, "description": desc, "reason": reason})
    return features


def run_doctor() -> dict[str, Any]:
    bootstrap_env()
    checks = {
        "monitor_root": str(ROOT.resolve()),
        "static_dir": str(STATIC_DIR.resolve()),
        "static_ok": (STATIC_DIR / "dashboard.html").is_file() and (STATIC_DIR / "theme.css").is_file(),
        "gateway_client": _gateway_client(),
        "env_sources": _env_sources(),
        "keys": _key_status(),
        "connectivity": {
            "coordinator": _check_coordinator(),
            "telemetry": _check_telemetry(),
            "neo4j_breakdown": _check_neo4j_breakdown(),
            "read_role": _check_read_role(),
        },
        "logs": {
            "log_paths": _check_log_paths(),
            "journal": _check_journal(),
        },
        "local_data": _check_local_data(),
    }
    checks["features"] = _feature_readiness(checks)
    checks["ok"] = all(f["ok"] for f in checks["features"] if f["depends_on"] in ("coordinator", "local"))
    return checks


def format_report(report: dict[str, Any]) -> str:
    lines = ["Shared Memory Monitor — environment check", ""]

    lines.append(f"Monitor root: {report['monitor_root']}")
    gc = report["gateway_client"]
    lines.append(f"Gateway client: {gc['mode']} → {gc['coordinator_url']}")
    src = gc.get("agent_token_source") or "unknown"
    lines.append(f"AGENT_TOKEN source: {src}")
    if src and src.startswith("skill:"):
        lines.append("  → WARNING: borrowed agent token; put a dedicated monitor token in monitor .env")
    if gc.get("framework_scripts"):
        lines.append(f"Framework checkout (logs only): {gc['framework_scripts']}")

    if report["env_sources"]:
        lines.append("")
        lines.append("Env files loaded (keys present, values not shown):")
        for src_info in report["env_sources"]:
            keys = ", ".join(src_info["keys_present"][:8])
            more = f" +{len(src_info['keys_present']) - 8}" if len(src_info["keys_present"]) > 8 else ""
            lines.append(f"  [{src_info['kind']}] {src_info['path']}")
            if keys:
                lines.append(f"         keys: {keys}{more}")
    else:
        lines.append("")
        lines.append("Env files: none found — copy .env.example → .env")

    lines.append("")
    lines.append("Configuration (presence only):")
    for key, state in sorted(report["keys"].items()):
        lines.append(f"  {key}: {state}")

    ld = report["local_data"]
    lines.append("")
    lines.append(f"Local history: {ld['samples']} samples" + (f" · last {ld['last_at']}" if ld["last_at"] else ""))

    lines.append("")
    lines.append("Connectivity:")
    for name, block in report["connectivity"].items():
        mark = "ok" if block.get("ok") else "FAIL"
        extra = f" — {block['error']}" if block.get("error") else ""
        if name == "coordinator":
            ver = block.get("version")
            srv = block.get("api_version")
            cli = block.get("client_api_version")
            compat = block.get("compat")
            bits = []
            if ver is not None:
                bits.append(f"gateway {ver}")
            if srv is not None or cli is not None:
                bits.append(f"api server={srv} client={cli} compat={compat}")
            if block.get("has_llm_config"):
                n = block.get("llm_backend_count")
                bits.append(f"{n} LLM backend" + ("s" if n != 1 else ""))
            if block.get("has_llm_pool"):
                bits.append("llm_pool")
            if block.get("has_llm_placement"):
                loc = block.get("llm_local_count") or 0
                ext = block.get("llm_external_count") or 0
                if loc and ext:
                    bits.append(f"placement {loc} local/{ext} external")
                elif ext:
                    bits.append("placement external")
                else:
                    bits.append("placement local")
            elif block.get("has_llm_config"):
                bits.append("placement n/a (gateway <0.8.9)")
            if bits:
                extra = (extra + " · " + " · ".join(bits)) if extra else " · " + " · ".join(bits)
        if name == "telemetry":
            panels = []
            for key, label in (
                ("has_nrem", "nrem"),
                ("has_breakdown", "breakdown"),
                ("has_consolidation", "consolidation"),
                ("has_entity_graph", "entity_graph"),
                ("has_latency", "latency"),
                ("has_spine", "spine"),
                ("has_compliance", "compliance"),
            ):
                if block.get(key):
                    panels.append(label)
            if panels:
                extra = (extra + " · " + "+".join(panels)) if extra else " · " + "+".join(panels)
        lines.append(f"  {name}: {mark}{extra}")

    lj = report["logs"]["journal"]
    lp = report["logs"]["log_paths"]
    lines.append("")
    jscope = lj.get("scope", "user")
    jun = lj.get("unit", journal_unit())
    lines.append(f"Logs: dir={'ok' if lp['log_dir_exists'] else 'missing'} ({lp['log_dir']})"
                 f" · journal({jscope})={'ok' if lj['ok'] else 'n/a'} [{jun}]")

    lines.append("")
    lines.append("Feature readiness:")
    for f in report["features"]:
        mark = "✓" if f["ok"] else "✗"
        lines.append(f"  {mark} {f['id']}: {f['reason']}")

    if report["keys"].get("AGENT_TOKEN") == "missing":
        lines.append("")
        lines.append("Install hint:")
        lines.append("  cp .env.example .env")
        lines.append("  # set AGENT_TOKEN=tok_monitor... and COORDINATOR_URL=http://localhost:8888")
        lines.append("  ./scripts/check-env.sh")

    return "\n".join(lines)


def main_check(*, as_json: bool = False) -> int:
    report = run_doctor()
    if as_json:
        print(json.dumps(report, indent=2))
    else:
        print(format_report(report))
    critical = (
        report["keys"].get("AGENT_TOKEN") != "set"
        or not report["connectivity"]["coordinator"]["ok"]
    )
    if critical and report["local_data"]["samples"] == 0:
        return 2
    if any(not f["ok"] for f in report["features"]):
        return 1
    return 0