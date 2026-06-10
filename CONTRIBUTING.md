# Contributing

Thanks for helping improve Shared Memory Monitor.

## Before you open a PR

1. Changes should preserve **decoupling** from the framework — no imports of `memory_bridge.py`, no direct Postgres in the default dashboard path.
2. Run tests and the publish audit:
   ```bash
   uv sync
   uv run python -m unittest discover -s tests -v
   ./scripts/pre-publish-check.sh
   ```
3. Do not commit `.env`, `data/`, or `.grok/`.

## Framework changes

Gateway API or telemetry shape changes belong in the [Shared Memory Framework](https://github.com/KanenasInGreece/Shared_Memory) first. This repo consumes public HTTP routes only.

## Docs

- User-facing setup → `README.md`
- Relationship to the framework → `docs/SISTER_PROJECT.md`
- Deploy artifacts → `deploy/README.md`

## License

Contributions are accepted under the same [MIT License](LICENSE) as the project.