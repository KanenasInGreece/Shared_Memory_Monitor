#!/usr/bin/env python3
"""Capture README screenshots from a running monitor (full-page, data-aware)."""
from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import NotRequired, TypedDict

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images"
BASE = os.environ.get("SM_SCREENSHOT_URL", "http://127.0.0.1:8765").rstrip("/")


class PageSpec(TypedDict):
    name: str
    path: str
    viewport: dict[str, int]
    full_page: NotRequired[bool]
    element: NotRequired[str]
    open: NotRequired[str]


PAGES: list[PageSpec] = [
    {
        "name": "dashboard.png",
        "path": "/",
        "viewport": {"width": 1440, "height": 900},
        "full_page": True,
    },
    {
        "name": "schema-breakdown.png",
        "path": "/?schema=1&capture=1",
        "viewport": {"width": 1440, "height": 900},
        "element": "#schema-content",
    },
    {
        "name": "consolidation.png",
        "path": "/",
        "viewport": {"width": 1440, "height": 900},
        "element": "#consolidation-content",
        "open": "#consolidation-card",
    },
    {
        "name": "diagram.png",
        "path": "/diagram?capture=1",
        "viewport": {"width": 1280, "height": 900},
        "full_page": True,
    },
    {
        "name": "logs.png",
        "path": "/logs?source=agent_audit&capture=1",
        "viewport": {"width": 1440, "height": 900},
        "full_page": True,
    },
]

_SCHEMA_EXPAND_JS = """() => {
  const drawer = document.getElementById('schema-drawer');
  const body = document.querySelector('.schema-drawer-body');
  const content = document.getElementById('schema-content');
  if (drawer) {
    drawer.style.height = 'auto';
    drawer.style.maxHeight = 'none';
    drawer.style.overflow = 'visible';
  }
  if (body) {
    body.style.overflow = 'visible';
    body.style.height = 'auto';
    body.style.flex = 'none';
  }
  if (content) content.style.overflow = 'visible';
}"""


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
        for spec in PAGES:
            name = spec["name"]
            path = spec["path"]
            page = browser.new_page(viewport=spec["viewport"])
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
                page.evaluate(_SCHEMA_EXPAND_JS)
                page.wait_for_timeout(200)
            opener = spec.get("open")
            if opener:
                page.wait_for_selector(opener, timeout=60_000)
                page.click(opener)
                page.wait_for_selector("#consolidation-drawer.open", timeout=60_000)
                page.wait_for_selector("#consolidation-content:not([hidden])", timeout=60_000)
                page.wait_for_timeout(600)
            target = OUT / name
            element = spec.get("element")
            if element:
                page.locator(element).screenshot(path=str(target))
            else:
                page.screenshot(path=str(target), full_page=spec.get("full_page", False))
            print(f"wrote {target}")
        browser.close()

    print("Screenshots ready under docs/images/ — commit and push to update the GitHub project page.")


if __name__ == "__main__":
    main()