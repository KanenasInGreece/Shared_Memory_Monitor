"""install.sh reports the doctor's exit once .env exists.

A new .env is created and the script stops before the doctor, because the
operator has not pasted the token yet. An existing .env is checked, and a
rejected token must not look like a finished install.
"""

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "install.sh"


def _write_exec(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


class InstallScriptTests(unittest.TestCase):
    def _run(self, root: Path, uv_body: str):
        fakebin = root / "fakebin"
        fakebin.mkdir()
        _write_exec(fakebin / "uv", uv_body)
        scripts = root / "scripts"
        scripts.mkdir()
        _write_exec(scripts / "install.sh", _SCRIPT.read_text())
        (root / "pyproject.toml").write_text('version = "0.0.0"\n')
        env = dict(os.environ)
        env["PATH"] = f"{fakebin}:{env.get('PATH', '')}"
        env.update(HOME=str(root), GIT_CONFIG_GLOBAL="/dev/null")
        return subprocess.run(
            ["bash", "scripts/install.sh"],
            cwd=root, env=env, capture_output=True, text=True, timeout=30,
        )

    def test_new_env_exits_before_the_doctor(self):
        uv = "#!/usr/bin/env bash\n[[ \"$1\" == sync ]] && exit 0\necho ran-check\nexit 2\n"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "checkout"
            root.mkdir()
            (root / ".env.example").write_text("AGENT_TOKEN=\n")
            proc = self._run(root, uv)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertNotIn("ran-check", proc.stdout)
            mode = (root / ".env").stat().st_mode & 0o777
            self.assertEqual(mode, 0o600)

    def test_existing_env_propagates_a_rejected_token(self):
        uv = "#!/usr/bin/env bash\n[[ \"$1\" == sync ]] && exit 0\nexit 2\n"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "checkout"
            root.mkdir()
            (root / ".env").write_text("AGENT_TOKEN=present\n")
            proc = self._run(root, uv)
            self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
            self.assertIn("Not ready", proc.stdout)
