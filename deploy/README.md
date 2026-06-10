# Deployment artifacts

Files here are **templates for the operator machine** — copy or install from the repo checkout; they are not imported by the Python package at runtime.

## systemd user unit

| File | Installed to |
|------|----------------|
| `systemd/user/shared-memory-monitor.service` | `~/.config/systemd/user/shared-memory-monitor.service` |

Keeps the poll loop and dashboard running after Grok Build / SSH logout when **user linger** is on (`loginctl enable-linger $USER`).

### Install

```bash
./scripts/install-systemd-user.sh
```

Or manually:

```bash
mkdir -p ~/.config/systemd/user
cp deploy/systemd/user/shared-memory-monitor.service ~/.config/systemd/user/
# Edit paths in the unit if your checkout is not at ~/grok-labs/projects/shared-memory-monitor
systemctl --user daemon-reload
systemctl --user enable --now shared-memory-monitor.service
```

### Verify

```bash
systemctl --user status shared-memory-monitor.service
curl -s http://127.0.0.1:8765/api/meta
```

Stop a foreground/Grok-started copy first if port 8765 is busy: `fuser -k 8765/tcp`.

Shipped in the repo under `deploy/` — install with `scripts/install-systemd-user.sh` (see root `README.md`).