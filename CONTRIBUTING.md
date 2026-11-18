# Contributing

Thanks for taking a look. radar-sec is a small personal research project, so the
process is light.

## Setup

- Python 3.13 and [uv](https://docs.astral.sh/uv/); Node.js 20.19+ for the dashboard.
- `uv sync`, then `cp .env.example .env` and set `SEC_USER_AGENT`.
- `./dev` runs the API and the dashboard together (`./dev --replay` for the historical replay).

## Before opening a pull request

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest
(cd web && npm run lint && npm test && npm run build)
```

The same checks run in CI (`.github/workflows/ci.yml`). Tests never touch the
network, a login or a token: SEC, Yahoo and the AI are faked.

## Guidelines

- Keep code, comments, commit messages and docs in English.
- Every user-facing string goes through the translation catalogs: `web/src/i18n/`
  (`en.ts`, `pt-BR.ts`) for the dashboard and `src/radar/locales/` (`en.py`, `pt_br.py`)
  for the CLI, alerts, summaries and reports.
  Add the English text and its pt-BR translation in the same change.
- Signal rules live in `src/radar/signals.py` and are shared by the live monitor
  and the backtest. If you change a rule, rerun the backtest and say how the
  numbers moved.
- Respect the SEC fair-access policy: keep the rate limiter and the `User-Agent`.
- Never commit `.env`, tokens, the `data/` folder or personal information.
- By contributing you agree that your contributions are licensed under the MIT License (see `LICENSE`).
- Keep pull requests small and focused, with a clear description of what changed and why.
