"""Legacy static export — primary UI is static/dashboard.html via server."""

from __future__ import annotations

import shutil

from .config import GRAPHS_DIR, STATIC_DIR


def ensure_dashboard_files() -> None:
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    GRAPHS_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("dashboard.html", "logs.html", "diagram.html", "theme.css", "bar-meta.js"):
        src = STATIC_DIR / name
        if src.exists():
            shutil.copy2(src, GRAPHS_DIR / name)