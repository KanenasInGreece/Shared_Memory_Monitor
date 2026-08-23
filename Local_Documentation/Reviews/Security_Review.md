# Security Review
**Reviewer:** Opus 4.6 (Security Role)
**Date:** 2026-08-23
**Target:** Monitor v0.9.17 Release (Install Scripts & Systemd User Linger)

## Findings
- **PATH Exports in scripts:** Adding `~/.local/bin` and `~/.cargo/bin` to `PATH` in shell scripts poses minimal risk as these are standard user-local directories for `uv` and `cargo` installations. 
- **loginctl enable-linger:** Attempting `loginctl enable-linger` via `sudo -n` in `install-systemd-user.sh` is a secure pattern because it explicitly requests non-interactive sudo (`-n`), ensuring it doesn't hang waiting for a password or prompt unexpectedly. If the user doesn't have passwordless sudo for this command, it degrades gracefully to a warning, avoiding an unauthorized privilege escalation attempt.

## Verdict
**APPROVED.** The changes adhere to security best practices for unprivileged service deployments. No new credentials or secrets are exposed.
