# Deployment artifacts

Templates for the operator machine — not imported by the Python package at runtime.

## systemd user unit

| File | Installed to |
|------|----------------|
| `systemd/user/shared-memory-monitor.service` | `~/.config/systemd/user/shared-memory-monitor.service` |

The template uses `@MONITOR_ROOT@` placeholders. `install-systemd-user.sh` substitutes your checkout path and copies the unit into `~/.config/systemd/user/`.

Keeps poll loop + dashboard running after logout when **user linger** is enabled (`loginctl enable-linger $USER`).

### Install

```bash
./scripts/install-systemd-user.sh
```

### Manual install

```bash
ROOT="$(pwd)"
mkdir -p ~/.config/systemd/user
sed "s|@MONITOR_ROOT@|$ROOT|g" deploy/systemd/user/shared-memory-monitor.service \
  > ~/.config/systemd/user/shared-memory-monitor.service
systemctl --user daemon-reload
systemctl --user enable --now shared-memory-monitor.service
```

### Verify

```bash
systemctl --user status shared-memory-monitor.service
curl -s http://127.0.0.1:8765/api/meta
```

Stop a foreground copy first if port 8765 is busy: `fuser -k 8765/tcp`.

See root [README.md](../README.md#running-as-a-service).

## Log rotation (audit jsonl)

Per-save logs are archived daily by the framework (`shared_memory_YYYY-MM-DD.log.gz`). REM and agent audit jsonl files are append-only — rotate them externally.

Copy [logrotate/shared-memory-audit.example](logrotate/shared-memory-audit.example), set paths to your `MEMORY_LOG_PATH`, and install under `/etc/logrotate.d/`. The monitor **REM audit** and **Agent audit** tabs discover rotated `.gz` files next to the live jsonl and list them in the **File** dropdown (read-only).