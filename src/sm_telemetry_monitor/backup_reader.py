"""Read latest completed backup metadata from gateway-host manifest files."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .env_loader import get

_PREFIX = "sm-backup"
_MANIFEST_GLOB = f"{_PREFIX}-*.manifest.json"


def backup_dir() -> Path:
    return Path(os.path.expanduser(
        get("BACKUP_DIR", "~/.shared-memory/backups") or "~/.shared-memory/backups"
    ))


def _normalize_iso(value: str) -> str | None:
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def latest_backup_manifest() -> dict | None:
    """Return the newest completed backup set from sm-backup-*.manifest.json."""
    dir_path = backup_dir()
    if not dir_path.is_dir():
        return None

    manifests = sorted(dir_path.glob(_MANIFEST_GLOB))
    if not manifests:
        return None

    latest = manifests[-1]
    try:
        data = json.loads(latest.read_text())
    except (OSError, json.JSONDecodeError):
        return None

    created = _normalize_iso(str(data.get("created") or ""))
    if not created:
        return None

    name = data.get("name")
    if not name:
        name = latest.name[: -len(".manifest.json")]

    return {
        "at": created,
        "name": str(name),
        "dir": str(dir_path),
    }