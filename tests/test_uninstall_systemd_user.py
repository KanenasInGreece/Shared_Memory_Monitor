"""uninstall-systemd-user.sh removes the unit and never disables linger.

Linger is per-user. The gateway's user unit on the same account depends
on it, so the script must not call disable-linger. The test stubs
systemctl and never talks to the user manager.
"""

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "uninstall-systemd-user.sh"


def _write_exec(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


class UninstallSystemdUserTests(unittest.TestCase):
    def _run(self, load_state: str):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_exec(root / "uninstall-systemd-user.sh", _SCRIPT.read_text())
            xdg = root / "xdg"
            unit_dir = xdg / "systemd" / "user"
            unit_dir.mkdir(parents=True)
            unit = unit_dir / "shared-memory-monitor.service"
            unit.write_text("[Service]\nExecStart=/bin/true\n")
            log = root / "systemctl.log"
            (root / "fakebin").mkdir()
            _write_exec(
                root / "fakebin" / "systemctl",
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' \"$*\" >> \"$LOG\"\n"
                "if [[ \"$2\" == show ]]; then\n"
                f"  printf '%s\\n' '{load_state}'\n"
                "fi\n"
                "if [[ \"$2\" == is-active ]]; then exit 3; fi\n"
                "exit 0\n",
            )
            env = dict(os.environ)
            env["PATH"] = f"{root / 'fakebin'}:{env.get('PATH', '')}"
            env["XDG_CONFIG_HOME"] = str(xdg)
            env["HOME"] = str(root)
            env["LOG"] = str(log)
            proc = subprocess.run(
                ["bash", "uninstall-systemd-user.sh"],
                cwd=root, env=env, capture_output=True, text=True, timeout=30,
            )
            return proc, log.read_text(), unit.exists()

    def test_gone_unit_exits_0_and_never_disables_linger(self):
        proc, log, unit_exists = self._run("not-found")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("Linger left unchanged", proc.stdout)
        self.assertIn("operator agrees", proc.stdout)
        self.assertNotIn("disable-linger", log)
        self.assertNotIn("linger", log)
        self.assertFalse(unit_exists)

    def test_unit_still_loaded_exits_1(self):
        proc, log, _unit_exists = self._run("loaded")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("still known to systemd", proc.stderr)
        self.assertNotIn("disable-linger", log)


if __name__ == "__main__":
    unittest.main()
