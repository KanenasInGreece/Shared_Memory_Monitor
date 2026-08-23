import re
with open('AGENTS.md', 'r') as f:
    text = f.read()

# Add script to table
old_table = "| `./scripts/install-systemd-user.sh` | Persist as `shared-memory-monitor.service` (user unit) |"
new_table = "| `./scripts/install-systemd-user.sh` | Persist as `shared-memory-monitor.service` (user unit) |\n| `./scripts/uninstall-systemd-user.sh` | Cleanly remove the systemd unit and disable linger |"
text = text.replace(old_table, new_table)

# Replace Stop with Stop & Uninstall
old_stop = """### Stop

```bash
systemctl --user stop shared-memory-monitor.service
# disable autostart: systemctl --user disable shared-memory-monitor.service
```"""

new_stop = """### Stop

```bash
systemctl --user stop shared-memory-monitor.service
```

### Uninstall (Teardown)

```bash
./scripts/uninstall-systemd-user.sh
# Note: disabling linger on some distributions (e.g., Debian) may require sudo.
# The script attempts `sudo -n loginctl disable-linger $USER`. If it fails, run manually:
# sudo loginctl disable-linger $USER
cd .. && rm -rf Shared_Memory_Monitor
```"""

text = text.replace(old_stop, new_stop)

with open('AGENTS.md', 'w') as f:
    f.write(text)
