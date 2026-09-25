"""Hermetic subprocess test for scripts/agent-upgrade.sh's detached-HEAD handling.

fact:2758: `agent-upgrade.sh --ref TAG` leaves a detached HEAD, and a later plain
upgrade (no --ref) then has no branch to fast-forward — `git rev-parse
--abbrev-ref HEAD` returns the literal string "HEAD", and `git pull --ff-only
origin HEAD` is not what the operator wants. Uses a local file:// origin so the
whole test is offline; stubs `uv` and `systemctl` since neither matters here.
"""

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "agent-upgrade.sh"


def _write_exec(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _git(args, cwd, **kw):
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
                           cwd=cwd, check=True, capture_output=True, text=True, **kw)


class AgentUpgradeDetachedHeadTests(unittest.TestCase):
    def _make_origin_and_clone(self, td: Path):
        origin = td / "origin.git"
        origin.mkdir()
        _git(["init", "-q"], cwd=origin)
        (origin / "pyproject.toml").write_text('[project]\nversion = "1.0.0"\n')
        (origin / "scripts").mkdir()
        _write_exec(origin / "scripts" / "agent-upgrade.sh", _SCRIPT.read_text())
        _write_exec(origin / "scripts" / "agent-status.sh", "#!/usr/bin/env bash\nexit 0\n")
        _git(["add", "-A"], cwd=origin)
        _git(["commit", "-q", "-m", "first"], cwd=origin)
        _git(["tag", "v1.0.0"], cwd=origin)
        (origin / "pyproject.toml").write_text('[project]\nversion = "1.0.1"\n')
        _git(["commit", "-q", "-am", "second"], cwd=origin)
        _git(["branch", "-M", "main"], cwd=origin)

        clone = td / "clone"
        _git(["clone", "-q", str(origin), str(clone)], cwd=td)
        _git(["checkout", "-q", "v1.0.0"], cwd=clone)  # detached HEAD, as --ref TAG leaves it

        fakebin = td / "fakebin"
        fakebin.mkdir()
        _write_exec(fakebin / "uv", "#!/usr/bin/env bash\nexit 0\n")
        _write_exec(fakebin / "systemctl", "#!/usr/bin/env bash\nexit 1\n")
        return clone, fakebin

    def test_no_ref_on_detached_head_checks_out_main_before_fast_forward(self):
        with tempfile.TemporaryDirectory() as td:
            clone, fakebin = self._make_origin_and_clone(Path(td))
            env = dict(os.environ)
            env["PATH"] = f"{fakebin}:{env.get('PATH', '')}"
            proc = subprocess.run(
                ["bash", "scripts/agent-upgrade.sh"],
                cwd=clone, env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=clone).stdout.strip()
            self.assertEqual(branch, "main")
            version = (clone / "pyproject.toml").read_text()
            self.assertIn("1.0.1", version)  # fast-forwarded past the pinned tag

    def test_ref_tag_says_pinned_and_how_to_return_to_main(self):
        with tempfile.TemporaryDirectory() as td:
            clone, fakebin = self._make_origin_and_clone(Path(td))
            env = dict(os.environ)
            env["PATH"] = f"{fakebin}:{env.get('PATH', '')}"
            proc = subprocess.run(
                ["bash", "scripts/agent-upgrade.sh", "--ref", "v1.0.0"],
                cwd=clone, env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("Pinned to v1.0.0", proc.stdout)
            self.assertIn("git checkout main", proc.stdout)
            branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=clone).stdout.strip()
            self.assertEqual(branch, "HEAD")  # still detached — pinning does not move it


if __name__ == "__main__":
    unittest.main()
