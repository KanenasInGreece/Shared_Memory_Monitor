"""The unit file gets the checkout path as text, not as a sed pattern.

A path that contains sed metacharacters must survive unchanged. The test
stubs systemctl so it never talks to the user manager.
"""

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "install-systemd-user.sh"
_UNIT = _REPO_ROOT / "deploy" / "systemd" / "user" / "shared-memory-monitor.service"


def _write_exec(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


class InstallSystemdUserTests(unittest.TestCase):
    def test_checkout_path_with_a_pipe_is_copied_literally(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "a|b"
            _write_exec(root / "scripts" / "install-systemd-user.sh", _SCRIPT.read_text())
            dest_dir = root / "deploy" / "systemd" / "user"
            dest_dir.mkdir(parents=True)
            (dest_dir / "shared-memory-monitor.service").write_text(_UNIT.read_text())
            xdg = root / "xdg"
            fakebin = root / "fakebin"
            _write_exec(fakebin / "systemctl", "#!/usr/bin/env bash\nexit 0\n")
            _write_exec(fakebin / "loginctl", "#!/usr/bin/env bash\nexit 1\n")
            _write_exec(fakebin / "sudo", "#!/usr/bin/env bash\nexit 1\n")
            _write_exec(
                fakebin / "curl",
                "#!/usr/bin/env bash\n"
                "[[ \"$*\" == *8765/api/meta* ]] && exit 0\n"
                "exit 1\n",
            )
            _write_exec(fakebin / "ss", "#!/usr/bin/env bash\nexit 1\n")
            env = dict(os.environ)
            env["PATH"] = f"{fakebin}:{env.get('PATH', '')}"
            env["XDG_CONFIG_HOME"] = str(xdg)
            env["HOME"] = str(root)
            proc = subprocess.run(
                ["bash", "scripts/install-systemd-user.sh"],
                cwd=root, env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            written = (xdg / "systemd" / "user" / "shared-memory-monitor.service").read_text()
            self.assertIn(str(root), written)
            self.assertNotIn("@MONITOR_ROOT@", written)
            self.assertIn(f"WorkingDirectory={root}\n", written)
            self.assertIn(f"EnvironmentFile={root}/.env\n", written)
            self.assertNotIn(f'WorkingDirectory="{root}"', written)
            self.assertIn(f'ExecStart="{root}/.venv/bin/python"', written)

    def test_space_and_percent_use_systemd_escapes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "a b%c"
            _write_exec(root / "scripts" / "install-systemd-user.sh", _SCRIPT.read_text())
            dest_dir = root / "deploy" / "systemd" / "user"
            dest_dir.mkdir(parents=True)
            (dest_dir / "shared-memory-monitor.service").write_text(_UNIT.read_text())
            xdg = root / "xdg"
            fakebin = root / "fakebin"
            _write_exec(fakebin / "systemctl", "#!/usr/bin/env bash\nexit 0\n")
            _write_exec(fakebin / "loginctl", "#!/usr/bin/env bash\nexit 1\n")
            _write_exec(fakebin / "sudo", "#!/usr/bin/env bash\nexit 1\n")
            _write_exec(
                fakebin / "curl",
                "#!/usr/bin/env bash\n"
                "[[ \"$*\" == *8765/api/meta* ]] && exit 0\n"
                "exit 1\n",
            )
            _write_exec(fakebin / "ss", "#!/usr/bin/env bash\nexit 1\n")
            env = dict(os.environ)
            env["PATH"] = f"{fakebin}:{env.get('PATH', '')}"
            env["XDG_CONFIG_HOME"] = str(xdg)
            env["HOME"] = str(root)
            proc = subprocess.run(
                ["bash", "scripts/install-systemd-user.sh"],
                cwd=root, env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            written = (xdg / "systemd" / "user" / "shared-memory-monitor.service").read_text()
            path = str(root).replace("%", "%%")
            self.assertIn(f"WorkingDirectory={path}\n", written)
            self.assertIn(f"EnvironmentFile={path}/.env\n", written)
            self.assertIn(f'ExecStart="{path}/.venv/bin/python"', written)
            self.assertNotIn("\\x20", written)
            self.assertNotIn(f'WorkingDirectory="{root}"', written)

    def test_backslash_and_quote_are_literal_in_path_settings(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'a\\b"c'
            _write_exec(root / "scripts" / "install-systemd-user.sh", _SCRIPT.read_text())
            dest_dir = root / "deploy" / "systemd" / "user"
            dest_dir.mkdir(parents=True)
            (dest_dir / "shared-memory-monitor.service").write_text(_UNIT.read_text())
            xdg = root / "xdg"
            fakebin = root / "fakebin"
            _write_exec(fakebin / "systemctl", "#!/usr/bin/env bash\nexit 0\n")
            _write_exec(fakebin / "loginctl", "#!/usr/bin/env bash\nexit 1\n")
            _write_exec(fakebin / "sudo", "#!/usr/bin/env bash\nexit 1\n")
            _write_exec(
                fakebin / "curl",
                "#!/usr/bin/env bash\n"
                "[[ \"$*\" == *8765/api/meta* ]] && exit 0\n"
                "exit 1\n",
            )
            _write_exec(fakebin / "ss", "#!/usr/bin/env bash\nexit 1\n")
            env = dict(os.environ)
            env["PATH"] = f"{fakebin}:{env.get('PATH', '')}"
            env["XDG_CONFIG_HOME"] = str(xdg)
            env["HOME"] = str(root)
            proc = subprocess.run(
                ["bash", "scripts/install-systemd-user.sh"],
                cwd=root, env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            written = (xdg / "systemd" / "user" / "shared-memory-monitor.service").read_text()
            self.assertIn(f"WorkingDirectory={root}\n", written)
            self.assertIn(f"EnvironmentFile={root}/.env\n", written)
            exec_inner = str(root).replace("\\", "\\\\").replace('"', '\\"')
            self.assertIn(f'ExecStart="{exec_inner}/.venv/bin/python"', written)
