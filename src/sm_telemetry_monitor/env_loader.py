"""Configuration bootstrap for the standalone monitor plugin.

Monitor .env wins for AGENT_TOKEN and COORDINATOR_URL. SHARED_MEMORY_ROOT is
optional — only needed for framework log paths (MEMORY_LOG_PATH, etc.).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

MONITOR_ROOT = Path(__file__).resolve().parents[2]

# Vars loaded from framework / skill .env files (never load whole files wholesale)
_FRAMEWORK_KEYS = frozenset({
    "PG_PASSWORD", "PG_CONN", "NEO4J_PASSWORD",
    "MEMORY_LOG_PATH", "AUDIT_LOG_PATH", "GATEWAY_AUDIT_LOG_PATH", "MEMORY_LOG_LEVEL",
    "COORDINATOR_URL", "AGENT_TOKEN",
    "PG_HOST", "PG_PORT", "PG_DB", "PG_USER",
    "NEO4J_BROWSER_URL", "BACKUP_DIR",
})

# Extra keys allowed only from the monitor repo's own .env
_MONITOR_EXTRA_KEYS = frozenset({
    "SHARED_MEMORY_ROOT", "SM_GATEWAY_ENV", "SM_MEMORY_BRIDGE", "SM_SKILL_ROOT",
    "SM_IGNORED_OUTBOX_IDS", "SM_JOURNAL_UNIT", "BACKUP_DIR",
})

# Monitor .env overrides these even if set by framework/skill copies
_MONITOR_OVERRIDE_KEYS = frozenset({"AGENT_TOKEN", "COORDINATOR_URL"})

# Vars with framework-hardcoded defaults (not in .env.example as user-set)
_DEFAULTS = {
    "COORDINATOR_URL": "http://localhost:8888",
    "MEMORY_LOG_PATH": "~/.shared-memory/logs",
    "NEO4J_BROWSER_URL": "http://127.0.0.1:7474",
    "BACKUP_DIR": "~/.shared-memory/backups",
    "PG_HOST": "localhost",
    "PG_PORT": "5432",
    "PG_DB": "agent_data",
    "PG_USER": "postgres",
}

_AGENT_TOKEN_SOURCE: str | None = None


def _expand(path: str) -> str:
    return os.path.expanduser(path.strip())


def _parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), _expand(v.strip())
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            if k:
                out[k] = v
    except OSError:
        pass
    return out


def _bridge_script_candidates_labeled() -> list[tuple[str, Path]]:
    """(source_label, scripts_dir) — optional; used for log-path discovery only."""
    found: list[tuple[str, Path]] = []

    bridge = os.environ.get("SM_MEMORY_BRIDGE")
    if bridge:
        p = Path(_expand(bridge))
        if p.is_file():
            found.append(("SM_MEMORY_BRIDGE", p.parent))

    shared_root = os.environ.get("SHARED_MEMORY_ROOT")
    if shared_root:
        scripts = Path(_expand(shared_root)) / "shared-memory" / "scripts"
        if (scripts / "memory_bridge.py").is_file():
            found.append(("SHARED_MEMORY_ROOT", scripts))

    for name, sibling in (
        ("sibling:shared-memory-GitHub", MONITOR_ROOT.parent / "shared-memory-GitHub" / "shared-memory" / "scripts"),
        ("sibling:shared-memory", MONITOR_ROOT.parent / "shared-memory" / "shared-memory" / "scripts"),
    ):
        if (sibling / "memory_bridge.py").is_file():
            found.append((name, sibling))

    skill_root = os.environ.get("SM_SKILL_ROOT")
    if skill_root:
        scripts = Path(_expand(skill_root)) / "scripts"
        if (scripts / "memory_bridge.py").is_file():
            found.append(("SM_SKILL_ROOT", scripts))

    for agent in ("grok", "claude", "codex", "gemini"):
        scripts = Path.home() / f".{agent}" / "skills" / "shared-memory" / "scripts"
        if (scripts / "memory_bridge.py").is_file():
            found.append((f"skill:{agent}", scripts))

    return found


def _bridge_script_candidates() -> list[Path]:
    return [scripts for _, scripts in _bridge_script_candidates_labeled()]


def _env_file_candidates() -> list[Path]:
    """Search order — first file wins per key (setdefault at load)."""
    candidates: list[Path] = []

    explicit = os.environ.get("SM_GATEWAY_ENV")
    if explicit:
        candidates.append(Path(_expand(explicit)))

    shared_root = os.environ.get("SHARED_MEMORY_ROOT")
    if shared_root:
        candidates.append(Path(_expand(shared_root)) / ".env")

    for sibling in (
        MONITOR_ROOT.parent / "shared-memory-GitHub" / ".env",
        MONITOR_ROOT.parent / "shared-memory" / ".env",
    ):
        candidates.append(sibling)

    for scripts in _bridge_script_candidates():
        if f"{Path.home()}/." in str(scripts) and "/skills/shared-memory/" in str(scripts):
            continue
        candidates.append(scripts.parent.parent / ".env")

    skill_root = os.environ.get("SM_SKILL_ROOT")
    if skill_root:
        candidates.append(Path(_expand(skill_root)) / ".env")

    for agent in ("grok", "claude", "codex", "gemini"):
        candidates.append(
            Path.home() / f".{agent}" / "skills" / "shared-memory" / ".env"
        )

    seen: set[Path] = set()
    unique: list[Path] = []
    for p in candidates:
        rp = p.resolve() if p.exists() else p
        if rp not in seen:
            seen.add(rp)
            unique.append(p)
    return unique


def _allowed_env_keys(path: Path) -> frozenset[str]:
    """Whitelist per source — avoids loading unrelated secrets from framework .env."""
    monitor_env = (MONITOR_ROOT / ".env").resolve()
    if path.resolve() == monitor_env:
        return _FRAMEWORK_KEYS | _MONITOR_EXTRA_KEYS
    return _FRAMEWORK_KEYS


def _record_token_source(path: Path, key: str, source_label: str) -> None:
    global _AGENT_TOKEN_SOURCE
    if key == "AGENT_TOKEN" and (os.environ.get("AGENT_TOKEN") or "").strip():
        _AGENT_TOKEN_SOURCE = source_label


def bootstrap_env() -> None:
    """Load whitelisted .env keys into os.environ (monitor .env overrides token/URL)."""
    global _AGENT_TOKEN_SOURCE
    monitor_env = (MONITOR_ROOT / ".env").resolve()

    for path in _env_file_candidates():
        if not path.is_file():
            continue
        allowed = _allowed_env_keys(path)
        is_monitor_env = path.resolve() == monitor_env
        source_label = "monitor" if is_monitor_env else str(path.resolve())
        for key, val in _parse_env_file(path).items():
            if key not in allowed and not (is_monitor_env and key.startswith("SM_")):
                continue
            if os.environ.get(key) is None:
                os.environ[key] = val
                _record_token_source(path, key, source_label)

    if monitor_env.is_file():
        for key, val in _parse_env_file(monitor_env).items():
            if key in _MONITOR_OVERRIDE_KEYS or key in _MONITOR_EXTRA_KEYS or key.startswith("SM_"):
                if val:
                    os.environ[key] = val
                    if key == "AGENT_TOKEN":
                        _AGENT_TOKEN_SOURCE = "monitor"
            elif key in _FRAMEWORK_KEYS and key not in _MONITOR_OVERRIDE_KEYS:
                if val and os.environ.get(key) is None:
                    os.environ[key] = val

    for key, val in _DEFAULTS.items():
        os.environ.setdefault(key, val)


@lru_cache(maxsize=1)
def _bootstrapped() -> bool:
    bootstrap_env()
    return True


def get(key: str, default: str | None = None) -> str | None:
    _bootstrapped()
    return os.environ.get(key, default)


def agent_token_source() -> str | None:
    """Where AGENT_TOKEN was resolved from (e.g. 'monitor', 'skill:grok')."""
    _bootstrapped()
    return _AGENT_TOKEN_SOURCE


def memory_bridge_scripts_dir() -> Path | None:
    """Optional framework checkout — log paths only; not required for telemetry."""
    _bootstrapped()
    candidates = _bridge_script_candidates()
    return candidates[0] if candidates else None