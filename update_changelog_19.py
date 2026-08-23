import re
with open('CHANGELOG.md', 'r') as f:
    text = f.read()

new_changelog = """## [0.9.19] - 2026-08-23
### Added
- Added `scripts/uninstall-systemd-user.sh` to provide a clean, automated teardown path matching the install script.
- Documented explicit teardown procedures in `AGENTS.md` and `README.md`, gracefully handling systemd linger disable on Debian environments.

## [0.9.18]"""
text = text.replace('## [0.9.18]', new_changelog)
with open('CHANGELOG.md', 'w') as f:
    f.write(text)
