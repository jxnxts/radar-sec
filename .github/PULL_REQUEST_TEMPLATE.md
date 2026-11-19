## What and why

<!-- What changed and why. Link the issue if there is one. -->

## Checklist

- [ ] `uv run ruff check src tests`, `uv run ruff format --check src tests` and `uv run pytest` pass
- [ ] `cd web && npm run lint && npm test && npm run build` pass
- [ ] New user-facing strings are in both catalogs (en-US and pt-BR)
- [ ] If a signal rule changed: the backtest was rerun and the README/report numbers updated
- [ ] No secrets, personal data or `data/` files committed
