#!/usr/bin/env python3
"""Capture README screenshots from a running monitor (full-page, data-aware)."""
from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images"
BASE = os.environ.get("SM_SCREENSHOT_URL", "http://127.0.0.1:8765").rstrip("/")

PAGES: list[tuple[str, str, dict[str, int]]] = [
    ("dashboard.png", "/", {"width": 1440, "height": 900}),
    ("schema-breakdown.png", "/?schema=1&capture=1", {"width": 1440, "height": 900}),
    ("diagram.png", "/diagram?capture=1", {"width": 1280, "height": 900}),
    ("logs.png", "/logs?source=agent_audit&capture=1", {"width": 1440, "height": 900}),
]


def _probe() -> None:
    try:
        with urllib.request.urlopen(f"{BASE}/api/meta", timeout=8) as resp:
            if resp.status != 200:
                raise urllib.error.URLError(f"HTTP {resp.status}")
    except Exception as exc:
        print(f"Monitor not reachable at {BASE} — start it first:", file=sys.stderr)
        print("  ./scripts/run-loop.sh --serve --interval 600", file=sys.stderr)
        print(f"  ({exc})", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    _probe()
    OUT.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for name, path, viewport in PAGES:
            page = browser.new_page(viewport=viewport)
            page.goto(f"{BASE}{path}", wait_until="networkidle", timeout=60_000)
            if "diagram" in path:
                page.wait_for_selector("body[data-diagram-ready='1']", timeout=60_000)
            if "logs" in path:
                page.wait_for_selector("body[data-logs-ready='1']", timeout=60_000)
                page.wait_for_selector("#tabs .view-tab.is-active[data-id='agent_audit']", timeout=60_000)
                page.wait_for_selector(".log-agent-audit", timeout=60_000)
            if "schema=1" in path:
                page.wait_for_selector("body[data-schema-ready='1']", timeout=60_000)
                page.wait_for_selector("#schema-content:not([hidden])", timeout=60_000)
                page.wait_for_selector("#schema-drawer.open", timeout=60_000)
                page.wait_for_timeout(600)
            target = OUT / name
            page.screenshot(path=str(target), full_page=True)
            print(f"wrote {target}")
        browser.close()

    print("Screenshots ready under docs/images/ — commit and push to update the GitHub project page.")


if __name__ == "__main__":
    main()