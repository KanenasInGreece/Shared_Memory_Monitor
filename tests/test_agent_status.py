"""Hermetic subprocess test for scripts/agent-status.sh's `next:` line.

fact:2758 (measured after v0.9.32): agent-status prints `next: OK` while
`overall: partial` — a coding agent reading only `next` would think there is
nothing left to do. This test stubs curl/systemctl/uv (real git is used —
the script's own repo introspection needs a real one, and --offline skips the
only network call) so the script runs with no network or systemd access, and
pins the fix: when overall is partial, `next` must never say OK, and it must
name the failing feature id(s) and point at ./scripts/check-env.sh.
"""

import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "agent-status.sh"

_DOCTOR_JSON = {
    "connectivity": {
        "coordinator": {
            "ok": True, "version": "1.0.7", "api_version": 4,
            "client_api_version": 4, "compat": "ok",
        },
        "read_role": {"ok": True, "token_rejected": False},
    },
    "features": [
        {"id": "api_breakdown_neo4j", "ok": False, "reason": "needs framework >= 1.0.7"},
        {"id": "dashboard_history", "ok": True, "reason": "ok"},
    ],
    "gateway_client": {"agent_token_source": "monitor"},
    "keys": {"AGENT_TOKEN": "set", "agent_token_source": "monitor"},
}


def _write_exec(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


class AgentStatusPartialNeverOkTests(unittest.TestCase):
    def _run(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "scripts").mkdir()
            _write_exec(root / "scripts" / "agent-status.sh", _SCRIPT.read_text())
            (root / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "9.9.9"\n')
            (root / ".env").write_text("COORDINATOR_URL=http://localhost:8888\n")

            fakebin = root / "fakebin"
            fakebin.mkdir()
            _write_exec(fakebin / "curl", "#!/usr/bin/env bash\nexit 0\n")
            _write_exec(fakebin / "systemctl", "#!/usr/bin/env bash\nexit 1\n")
            _write_exec(
                fakebin / "uv",
                "#!/usr/bin/env bash\n"
                "if [[ \"$1\" == \"run\" ]]; then\n"
                f"  cat <<'JSON'\n{json.dumps(_DOCTOR_JSON)}\nJSON\n"
                "  exit 1\n"
                "fi\n"
                "exit 0\n",
            )

            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                             "commit", "-q", "--allow-empty", "-m", "x"], cwd=root, check=True)

            env = dict(os.environ)
            env["PATH"] = f"{fakebin}:{env.get('PATH', '')}"
            proc = subprocess.run(
                ["bash", "scripts/agent-status.sh", "--json", "--offline"],
                cwd=root, env=env, capture_output=True, text=True, timeout=30,
            )
            return proc, json.loads(proc.stdout)

    def test_next_never_says_ok_when_partial(self):
        proc, out = self._run()
        self.assertEqual(out["overall"], "partial")
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn("OK", out["next"])

    def test_next_names_failing_feature_and_check_env(self):
        proc, out = self._run()
        self.assertIn("api_breakdown_neo4j", out["next"])
        self.assertIn("check-env.sh", out["next"])


if __name__ == "__main__":
    unittest.main()
