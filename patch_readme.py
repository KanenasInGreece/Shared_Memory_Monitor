import re
with open('README.md', 'r') as f:
    text = f.read()

old_sysd = """## systemd service

```bash
./scripts/install-systemd-user.sh    # template: deploy/systemd/user/shared-memory-monitor.service
```"""

new_sysd = """## systemd service

```bash
./scripts/install-systemd-user.sh    # template: deploy/systemd/user/shared-memory-monitor.service
./scripts/uninstall-systemd-user.sh  # cleanly remove service and disable linger
```"""
text = text.replace(old_sysd, new_sysd)

with open('README.md', 'w') as f:
    f.write(text)
