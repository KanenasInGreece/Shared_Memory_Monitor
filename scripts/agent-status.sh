#!/usr/bin/env bash
# One-shot operator status for coding agents and humans — no secrets printed.
# Exit: 0 ready | 1 partial (optional panels) | 2 not ready | 3 usage/tool error
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

JSON=0
if [[ "${1:-}" == "--json" ]]; then
  JSON=1
elif [[ -n "${1:-}" ]]; then
  echo "Usage: $0 [--json]" >&2
  exit 3
fi

have() { command -v "$1" >/dev/null 2>&1; }

git_branch=""
git_head=""
git_dirty=0
if have git && git rev-parse --git-dir >/dev/null 2>&1; then
  git_branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  git_head="$(git rev-parse --short HEAD 2>/dev/null || true)"
  if [[ -n "$(git status --porcelain 2>/dev/null || true)" ]]; then
    git_dirty=1
  fi
fi

pkg_version=""
if [[ -f pyproject.toml ]]; then
  pkg_version="$(grep -E '^version\s*=' pyproject.toml | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"
fi

env_exists=0
[[ -f .env ]] && env_exists=1

coord_url="http://localhost:8888"
if [[ -f .env ]]; then
  line="$(grep -E '^COORDINATOR_URL=' .env | head -1 || true)"
  if [[ -n "$line" ]]; then
    coord_url="${line#COORDINATOR_URL=}"
    coord_url="${coord_url%\"}"
    coord_url="${coord_url#\"}"
    coord_url="${coord_url%\'}"
    coord_url="${coord_url#\'}"
  fi
fi

gateway_http=0
if have curl; then
  if curl -sf --max-time 3 "${coord_url%/}/health" >/dev/null 2>&1; then
    gateway_http=1
  fi
fi

unit_state="absent"
if have systemctl; then
  if systemctl --user cat shared-memory-monitor.service >/dev/null 2>&1; then
    unit_state="$(systemctl --user is-active shared-memory-monitor.service 2>/dev/null || echo inactive)"
  fi
fi

dashboard_http=0
if have curl; then
  if curl -sf --max-time 3 http://127.0.0.1:8765/api/meta >/dev/null 2>&1; then
    dashboard_http=1
  fi
fi

doctor_tmp="$(mktemp)"
doctor_exit=2
cleanup() { rm -f "$doctor_tmp"; }
trap cleanup EXIT

if have uv; then
  set +e
  uv run python -m sm_telemetry_monitor check --json >"$doctor_tmp" 2>/dev/null
  doctor_exit=$?
  set -e
  if [[ ! -s "$doctor_tmp" ]]; then
    echo '{}' >"$doctor_tmp"
  fi
else
  echo '{}' >"$doctor_tmp"
fi

payload="$(
  MONITOR_ROOT="$ROOT" \
  PKG_VERSION="$pkg_version" \
  GIT_BRANCH="$git_branch" \
  GIT_HEAD="$git_head" \
  GIT_DIRTY="$git_dirty" \
  ENV_EXISTS="$env_exists" \
  COORD_URL="$coord_url" \
  GW_OK="$gateway_http" \
  UNIT_STATE="$unit_state" \
  DASH_OK="$dashboard_http" \
  DOC_EXIT="$doctor_exit" \
  DOC_JSON_PATH="$doctor_tmp" \
  python3 - <<'PY'
import json, os

def jload(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}

doc = jload(os.environ["DOC_JSON_PATH"])
conn = doc.get("connectivity") or {}
coord = conn.get("coordinator") or {}
features = {f.get("id"): f for f in (doc.get("features") or []) if isinstance(f, dict)}

out = {
    "monitor_root": os.environ.get("MONITOR_ROOT"),
    "package_version": os.environ.get("PKG_VERSION") or None,
    "git": {
        "branch": os.environ.get("GIT_BRANCH") or None,
        "head": os.environ.get("GIT_HEAD") or None,
        "dirty": os.environ.get("GIT_DIRTY") == "1",
    },
    "env_file_present": os.environ.get("ENV_EXISTS") == "1",
    "coordinator_url": os.environ.get("COORD_URL"),
    "gateway_http_ok": os.environ.get("GW_OK") == "1",
    "gateway_version": coord.get("version"),
    "api_version": coord.get("api_version"),
    "client_api_version": coord.get("client_api_version"),
    "api_compat": coord.get("compat"),
    "agent_token_source": (doc.get("gateway_client") or {}).get("agent_token_source")
        or (doc.get("keys") or {}).get("agent_token_source"),
    "doctor_exit": int(os.environ.get("DOC_EXIT") or 2),
    "connectivity": {
        k: {"ok": bool((v or {}).get("ok")), "error": (v or {}).get("error")}
        for k, v in conn.items()
        if isinstance(v, dict)
    },
    "features": {
        fid: {"ok": bool(f.get("ok")), "reason": f.get("reason")}
        for fid, f in features.items()
    },
    "unit": os.environ.get("UNIT_STATE"),
    "dashboard_http_ok": os.environ.get("DASH_OK") == "1",
    "dashboard_url": "http://127.0.0.1:8765/",
}

ready = (
    out["env_file_present"]
    and out["gateway_http_ok"]
    and out["doctor_exit"] == 0
    and (out["dashboard_http_ok"] or out["unit"] in ("active", "activating"))
)
partial = out["env_file_present"] and out["gateway_http_ok"] and out["doctor_exit"] in (0, 1)
if ready:
    out["overall"] = "ready"
elif partial:
    out["overall"] = "partial"
else:
    out["overall"] = "not_ready"

if not out["env_file_present"]:
    out["next"] = "Run ./scripts/install.sh and set AGENT_TOKEN + COORDINATOR_URL in .env"
elif not out["gateway_http_ok"]:
    out["next"] = f"Start Shared Memory gateway or fix COORDINATOR_URL ({out['coordinator_url']})"
elif out["doctor_exit"] == 2:
    out["next"] = "Fix AGENT_TOKEN / read_role — see ./scripts/check-env.sh"
elif out["doctor_exit"] == 1 and not out["dashboard_http_ok"]:
    out["next"] = "Doctor partial; start dashboard: ./scripts/run-loop.sh --serve or install-systemd-user.sh"
elif not out["dashboard_http_ok"] and out["unit"] not in ("active", "activating"):
    out["next"] = "Start monitor: ./scripts/install-systemd-user.sh or ./scripts/run-loop.sh --serve --interval 600"
elif out.get("api_compat") == "incompatible":
    out["next"] = "API version skew — upgrade monitor or gateway so api_version matches"
else:
    out["next"] = "OK — open " + out["dashboard_url"]

print(json.dumps(out, indent=2))
PY
)"

status_tmp="$(mktemp)"
printf '%s\n' "$payload" >"$status_tmp"
trap 'rm -f "$doctor_tmp" "$status_tmp"' EXIT

if [[ "$JSON" -eq 1 ]]; then
  cat "$status_tmp"
else
  python3 - "$status_tmp" <<'PY'
import json, sys
with open(sys.argv[1]) as f:
    d = json.load(f)
print("Shared Memory Monitor — agent status")
print(f"  overall:     {d.get('overall')}")
print(f"  package:     {d.get('package_version')}")
g = d.get("git") or {}
dirty = " (dirty)" if g.get("dirty") else ""
print(f"  git:         {g.get('branch')}@{g.get('head')}{dirty}")
print(f"  .env:        {'present' if d.get('env_file_present') else 'MISSING'}")
print(f"  coordinator: {d.get('coordinator_url')}")
gw = "ok" if d.get("gateway_http_ok") else "DOWN"
ver = d.get("gateway_version")
print(f"  gateway:     {gw}" + (f"  v{ver}" if ver else ""))
av, cv, ac = d.get("api_version"), d.get("client_api_version"), d.get("api_compat")
if av is not None or cv is not None:
    print(f"  api:         server={av} client={cv} compat={ac}")
print(f"  token src:   {d.get('agent_token_source') or 'unknown'}")
print(f"  doctor:      exit {d.get('doctor_exit')}")
print(f"  unit:        {d.get('unit')}")
dash = "ok" if d.get("dashboard_http_ok") else "down"
print(f"  dashboard:   {dash}  {d.get('dashboard_url')}")
print(f"  next:        {d.get('next')}")
PY
fi

overall="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("overall"))' "$status_tmp")"
case "$overall" in
  ready) exit 0 ;;
  partial) exit 1 ;;
  *) exit 2 ;;
esac
