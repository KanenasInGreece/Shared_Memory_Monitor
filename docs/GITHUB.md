# GitHub workflow (agents & maintainers)

Repository: **https://github.com/KanenasInGreece/Shared_Memory_Monitor**  
Default branch: **`main`**  
Local path: `/home/xenofon/grok-labs/projects/shared-memory-monitor`

## Authentication (this workstation)

| Tool | Status |
|------|--------|
| `gh` | Logged in as **KanenasInGreece** (keyring) |
| Git protocol | **SSH** — `git@github.com:KanenasInGreece/Shared_Memory_Monitor.git` |
| `git` user | Xenofon S. Motsenigos `<xsmotsenigos@gmail.com>` |

Agents can push without prompting when using the SSH remote above. Do not switch `origin` back to HTTPS unless credentials are reconfigured.

## Publish checklist

```bash
cd /home/xenofon/grok-labs/projects/shared-memory-monitor
./scripts/publish.sh          # audit + push
# or manually:
./scripts/pre-publish-check.sh
git push origin main
```

**Never commit:** `.env`, `data/*`, `graphs/*` (runtime), `.grok/`, `.venv/`

## Releases

```bash
gh release create v0.1.0 --title "v0.1.0" --notes-file CHANGELOG.md
```

Tag must match [CHANGELOG.md](../CHANGELOG.md).

## Sister repo

Framework: https://github.com/KanenasInGreece/Shared_Memory — gateway changes happen there; this repo only consumes HTTP APIs.