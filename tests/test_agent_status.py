"""Hermetic subprocess test for scripts/agent-status.sh's `next:` line.

fact:2758 finding (b), measured after v0.9.32: agent-status printed
`next: OK` while `overall` was partial. A coding agent that reads only
`next` would stop. This test stubs curl, systemctl and uv. Real git is
used, and --offline skips the only network call. When overall is partial,
`next` must not say OK. It names the failing feature id and points at
./scripts/check-env.sh.
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
            # The scripts re-export $HOME/.local/bin first; a temp HOME keeps a real uv
            # or systemctl there out of the test, and no global git config leaks in.
            env.update(HOME=str(root), GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")
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


_READY_DOCTOR = {
    "connectivity": {
        "coordinator": {
            "ok": True, "version": "1.0.7", "api_version": 4,
            "client_api_version": 4, "compat": "ok",
        },
        "read_role": {"ok": True, "token_rejected": False},
    },
    "features": [{"id": "dashboard_history", "ok": True, "reason": "ok"}],
    "gateway_client": {"agent_token_source": "monitor"},
    "keys": {"AGENT_TOKEN": "set", "agent_token_source": "monitor"},
}


def _git(args, cwd):
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    )


class AgentStatusUpdateRelationTests(unittest.TestCase):
    """A SHA that differs from HEAD is not automatically an update."""

    def _clone(self, td: Path):
        origin = td / "origin.git"
        origin.mkdir()
        _git(["init", "-q", "-b", "main"], cwd=origin)
        (origin / "README").write_text("a\n")
        _git(["add", "README"], cwd=origin)
        _git(["commit", "-q", "-m", "a"], cwd=origin)
        clone = td / "clone"
        _git(["clone", "-q", str(origin), str(clone)], cwd=td)
        (clone / "scripts").mkdir()
        _write_exec(clone / "scripts" / "agent-status.sh", _SCRIPT.read_text())
        (clone / "pyproject.toml").write_text('version = "9.9.9"\n')
        (clone / ".env").write_text("COORDINATOR_URL=http://127.0.0.1:9/\n")
        fakebin = td / "fakebin"
        fakebin.mkdir()
        _write_exec(fakebin / "curl", "#!/usr/bin/env bash\nexit 0\n")
        _write_exec(fakebin / "systemctl", "#!/usr/bin/env bash\nexit 1\n")
        _write_exec(
            fakebin / "uv",
            "#!/usr/bin/env bash\n"
            "[[ \"$1\" == run ]] || exit 0\n"
            f"cat <<'JSON'\n{json.dumps(_READY_DOCTOR)}\nJSON\n"
            "exit 0\n",
        )
        return origin, clone, fakebin

    def _status(self, td, clone, fakebin):
        env = dict(os.environ)
        env["PATH"] = f"{fakebin}:{env.get('PATH', '')}"
        env.update(HOME=str(td), GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")
        proc = subprocess.run(
            ["bash", "scripts/agent-status.sh", "--json"],
            cwd=clone, env=env, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(proc.returncode in (0, 1), True, proc.stdout + proc.stderr)
        return proc, json.loads(proc.stdout)

    def test_ahead_of_origin_is_not_an_update(self):
        with tempfile.TemporaryDirectory() as td:
            _origin, clone, fakebin = self._clone(Path(td))
            (clone / "README").write_text("local\n")
            _git(["commit", "-q", "-am", "local"], cwd=clone)
            proc, out = self._status(td, clone, fakebin)
            updates = out["updates"]
            self.assertEqual(updates["branch_relation"], "ahead")
            self.assertFalse(updates["updates_available"])
            self.assertEqual(proc.returncode, 0)
            self.assertNotIn("has commits not in HEAD", updates.get("summary") or "")

    def test_unfetched_tip_is_not_described_as_commits_absent_from_head(self):
        with tempfile.TemporaryDirectory() as td:
            origin, clone, fakebin = self._clone(Path(td))
            (origin / "README").write_text("remote\n")
            _git(["commit", "-q", "-am", "remote"], cwd=origin)
            proc, out = self._status(td, clone, fakebin)
            updates = out["updates"]
            self.assertEqual(updates["branch_relation"], "not-fetched")
            self.assertTrue(updates["updates_available"])
            self.assertIn("not in this clone", updates["summary"])
            self.assertNotIn("has commits not in HEAD", updates["summary"])
            self.assertEqual(proc.returncode, 1)

    def test_fetched_ancestor_is_behind(self):
        with tempfile.TemporaryDirectory() as td:
            origin, clone, fakebin = self._clone(Path(td))
            (origin / "README").write_text("remote\n")
            _git(["commit", "-q", "-am", "remote"], cwd=origin)
            _git(["fetch", "-q", "origin"], cwd=clone)
            _proc, out = self._status(td, clone, fakebin)
            updates = out["updates"]
            self.assertEqual(updates["branch_relation"], "behind")
            self.assertIn("is ahead of HEAD", updates["summary"])

    def test_diverged_heads_are_named_diverged(self):
        with tempfile.TemporaryDirectory() as td:
            origin, clone, fakebin = self._clone(Path(td))
            (clone / "README").write_text("local\n")
            _git(["commit", "-q", "-am", "local"], cwd=clone)
            (origin / "README").write_text("remote\n")
            _git(["commit", "-q", "-am", "remote"], cwd=origin)
            _git(["fetch", "-q", "origin"], cwd=clone)
            _proc, out = self._status(td, clone, fakebin)
            updates = out["updates"]
            self.assertEqual(updates["branch_relation"], "diverged")
            self.assertIn("diverged", updates["summary"])
            self.assertNotIn("has commits not in HEAD", updates["summary"])


if __name__ == "__main__":
    unittest.main()
