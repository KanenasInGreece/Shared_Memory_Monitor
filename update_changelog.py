import re
with open('CHANGELOG.md', 'r') as f:
    text = f.read()

new_changelog = """## [0.9.18] - 2026-08-23
### Added
- Adopted framework v0.9.14 telemetry updates: passthrough of `llm_latency` via `/health`.
- The Throughput & Latency drawer and LLM pool chips now securely extract and display numeric latency bounds (avg and max) and request fault tallies.
- Single-backend fleets (such as cloud-only configurations) now correctly render LLM pool chips and placement metrics, following framework presence adjustments.

## [0.9.17]"""
text = text.replace('## [0.9.17]', new_changelog)
with open('CHANGELOG.md', 'w') as f:
    f.write(text)
