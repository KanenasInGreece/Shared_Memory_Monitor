#!/usr/bin/env bash
# One-shot operator status for coding agents and humans — no secrets printed.
# Queries GitHub (origin) via git ls-remote for available updates (unless --offline).
# Exit: 0 ready | 1 partial (optional panels or updates available) | 2 not ready | 3 usage
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

JSON=0
OFFLINE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --json) JSON=1; shift ;;
    --offline) OFFLINE=1; shift ;;
    -h|--help)
      echo "Usage: $0 [--json] [--offline]"
      echo "  --json     machine-readable JSON (no secrets)"
      echo "  --offline  skip GitHub/origin update check (git ls-remote)"
      exit 0
      ;;
    *)
      echo "Usage: $0 [--json] [--offline]" >&2
      exit 3
      ;;
  esac
done

have() { command -v "$1" >/dev/null 2>&1; }

git_branch=""
git_head=""
git_head_full=""
git_dirty=0
git_remote="origin"
git_default_branch="main"
if have git && git rev-parse --git-dir >/dev/null 2>&1; then
  git_branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  git_head="$(git rev-parse --short HEAD 2>/dev/null || true)"
  git_head_full="$(git rev-parse HEAD 2>/dev/null || true)"
  if [[ -n "$(git status --porcelain 2>/dev/null || true)" ]]; then
    git_dirty=1
  fi
  # Prefer tracking remote/branch when set
  upstream="$(git rev-parse --abbrev-ref '@{upstream}' 2>/dev/null || true)"
  if [[ -n "$upstream" && "$upstream" == */* ]]; then
    git_remote="${upstream%%/*}"
    git_default_branch="${upstream#*/}"
  elif [[ -n "$git_branch" && "$git_branch" != "HEAD" ]]; then
    git_default_branch="$git_branch"
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
updates_tmp="$(mktemp)"
echo '{}' >"$updates_tmp"
cleanup() { rm -f "$doctor_tmp" "$updates_tmp" "${status_tmp:-}"; }
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

# ── GitHub / origin update check (git ls-remote — no local ref rewrite) ─────
if [[ "$OFFLINE" -eq 0 ]] && have git && git rev-parse --git-dir >/dev/null 2>&1 \
   && git remote get-url "$git_remote" >/dev/null 2>&1; then
  set +e
  # Bound network wait; never fail the whole status if GitHub is unreachable
  ls_out="$(GIT_TERMINAL_PROMPT=0 git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=8 \
    ls-remote "$git_remote" "refs/heads/${git_default_branch}" "refs/tags/*" 2>/dev/null)"
  ls_rc=$?
  set -e
  if [[ $ls_rc -eq 0 && -n "$ls_out" ]]; then
    REMOTE_LS="$ls_out" \
    LOCAL_FULL="$git_head_full" \
    LOCAL_SHORT="$git_head" \
    LOCAL_PKG="$pkg_version" \
    TRACK_BRANCH="$git_default_branch" \
    REMOTE_NAME="$git_remote" \
    python3 - <<'PY' >"$updates_tmp"
import json, os, re, sys

ls = os.environ.get("REMOTE_LS") or ""
local = (os.environ.get("LOCAL_FULL") or "").strip()
local_short = (os.environ.get("LOCAL_SHORT") or "").strip()
local_pkg = (os.environ.get("LOCAL_PKG") or "").strip()
branch = os.environ.get("TRACK_BRANCH") or "main"
remote = os.environ.get("REMOTE_NAME") or "origin"

branch_sha = None
tags = []  # (version_tuple, tag_name, sha)
for line in ls.splitlines():
    parts = line.split()
    if len(parts) < 2:
        continue
    sha, ref = parts[0], parts[1]
    if ref == f"refs/heads/{branch}":
        branch_sha = sha
    m = re.match(r"refs/tags/(v?(\d+)\.(\d+)\.(\d+))$", ref)
    if m:
        tag = m.group(1)
        ver = (int(m.group(2)), int(m.group(3)), int(m.group(4)))
        tags.append((ver, tag, sha))

tags.sort(key=lambda t: t[0])
latest_tag = tags[-1] if tags else None

behind_branch = None
if branch_sha and local:
    behind_branch = branch_sha != local

def parse_pkg(s):
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)", s or "")
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))

local_ver = parse_pkg(local_pkg)
behind_release = None
latest_tag_name = latest_tag[1] if latest_tag else None
latest_tag_sha = latest_tag[2] if latest_tag else None
if latest_tag and local_ver is not None:
    behind_release = latest_tag[0] > local_ver
elif latest_tag and local:
    # no package version — compare tip of latest tag to HEAD
    behind_release = latest_tag_sha != local

updates_available = bool(behind_branch or behind_release)

out = {
    "checked": True,
    "remote": remote,
    "branch": branch,
    "remote_branch_sha": branch_sha[:12] if branch_sha else None,
    "local_head": local_short or (local[:12] if local else None),
    "behind_branch": behind_branch,
    "latest_release_tag": latest_tag_name,
    "latest_release_sha": latest_tag_sha[:12] if latest_tag_sha else None,
    "local_package_version": local_pkg or None,
    "behind_release": behind_release,
    "updates_available": updates_available,
    "error": None,
}
if updates_available:
    bits = []
    if behind_branch:
        bits.append(f"{remote}/{branch} has commits not in HEAD")
    if behind_release:
        bits.append(f"newer release {latest_tag_name} (local package {local_pkg or 'unknown'})")
    out["summary"] = "; ".join(bits)
    out["upgrade_cmd"] = "./scripts/agent-upgrade.sh" + (
        f" --ref {latest_tag_name}" if behind_release and latest_tag_name and not behind_branch else ""
    )
else:
    out["summary"] = "up to date with origin" if branch_sha else "no remote branch tip"
    out["upgrade_cmd"] = None

print(json.dumps(out))
PY
  else
    python3 -c 'import json; print(json.dumps({"checked": False, "updates_available": None, "error": "git ls-remote failed or timed out", "summary": "could not reach GitHub/origin"}))' >"$updates_tmp"
  fi
else
  if [[ "$OFFLINE" -eq 1 ]]; then
    python3 -c 'import json; print(json.dumps({"checked": False, "updates_available": None, "error": "offline", "summary": "update check skipped (--offline)"}))' >"$updates_tmp"
  else
    python3 -c 'import json; print(json.dumps({"checked": False, "updates_available": None, "error": "no git remote", "summary": "update check skipped"}))' >"$updates_tmp"
  fi
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
  UPDATES_JSON_PATH="$updates_tmp" \
  python3 - <<'PY'
import json, os

def jload(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}

doc = jload(os.environ["DOC_JSON_PATH"])
updates = jload(os.environ["UPDATES_JSON_PATH"])
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
    "updates": updates,
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
updates_avail = bool((updates or {}).get("updates_available"))

# Health overall ignores updates; separate flag for agents. Exit code bumps to 1
# when ready-but-stale so automation can react without treating it as hard fail.
if ready and updates_avail:
    out["overall"] = "ready_updates"
elif ready:
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
elif updates_avail:
    cmd = (updates or {}).get("upgrade_cmd") or "./scripts/agent-upgrade.sh"
    summary = (updates or {}).get("summary") or "updates available on GitHub"
    out["next"] = f"Update available ({summary}) — run: {cmd}"
else:
    out["next"] = "OK — open " + out["dashboard_url"]

print(json.dumps(out, indent=2))
PY
)"

status_tmp="$(mktemp)"
printf '%s\n' "$payload" >"$status_tmp"

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
u = d.get("updates") or {}
if u.get("checked"):
    flag = "YES" if u.get("updates_available") else "no"
    print(f"  github:      updates={flag}  ({u.get('summary') or '—'})")
    if u.get("latest_release_tag"):
        print(f"  latest tag:  {u.get('latest_release_tag')}")
    if u.get("behind_branch"):
        print(f"  origin:      {u.get('remote')}/{u.get('branch')} tip {u.get('remote_branch_sha')} ≠ HEAD")
elif u.get("error"):
    print(f"  github:      check skipped ({u.get('error')})")
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
  ready_updates|partial) exit 1 ;;
  *) exit 2 ;;
esac
