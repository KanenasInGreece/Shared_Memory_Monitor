from __future__ import annotations

import argparse
import subprocess
import time

from .charts import render_graphs
from .config import DATA_FILE, GRAPHS_DIR, POLL_INTERVAL_S, SERVER_HOST, SERVER_PORT
from .dashboard import ensure_dashboard_files
from .pipeline_chart import render_pipeline
from .collector import load_history, poll_once
from .server import start_server_thread


def _render_all() -> None:
    history = load_history()
    render_graphs(history)
    render_pipeline(history)
    ensure_dashboard_files()
    print(f"graphs updated in {GRAPHS_DIR}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Shared Memory Monitor")
    parser.add_argument("--once", action="store_true", help="Single poll then exit")
    parser.add_argument("--interval", type=int, default=POLL_INTERVAL_S)
    parser.add_argument("--serve", action="store_true", help="Start live dashboard server")
    parser.add_argument("--open", action="store_true", help="Open dashboard in browser")
    parser.add_argument("cmd", nargs="?", default="loop",
                        choices=["loop", "serve", "check"],
                        help="loop (poll), serve (dashboard only), or check (env doctor)")
    parser.add_argument("--json", action="store_true", help="JSON output (check command)")
    args = parser.parse_args()

    if args.cmd == "check":
        from .doctor import main_check
        raise SystemExit(main_check(as_json=args.json))

    if args.cmd == "serve":
        from .server import run_server
        ensure_dashboard_files()
        run_server(block=True)
        return

    if args.serve:
        start_server_thread()

    print(f"Shared Memory Monitor — interval {args.interval}s, data → {DATA_FILE}")
    url = f"http://{SERVER_HOST}:{SERVER_PORT}/"
    if args.serve:
        print(f"Dashboard → {url}")

    while True:
        if poll_once() is not None:
            _render_all()
            if args.serve:
                print(f"dashboard → {url}")
        if args.open:
            subprocess.run(["xdg-open", url if args.serve else str(GRAPHS_DIR / "dashboard.html")],
                             check=False)
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()