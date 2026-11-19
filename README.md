# radar-sec

**English** · [Português (Brasil)](README.pt-BR.md)

**radar-sec** (Radar SEC) watches what companies file with the SEC (EDGAR), flags insider buying
that looks meaningful, and measures, with a backtest that takes no shortcuts,
whether those signals would actually have made money.

It does four things:

1. **Monitors** EDGAR in near real time: Form 4 (insider purchases and sales) and Schedule 13D (someone crossed 5% of a company).
2. **Flags** three situations: several insiders buying together, a CEO or CFO making a large purchase, and a new significant shareholder.
3. **Measures** the outcome of those signals from 2020 to 2025 against SPY, with costs and limitations stated up front.
4. **Shows** everything on a real-time war-room dashboard designed to stay open on a monitor, in English or Brazilian Portuguese. See [Dashboard](#dashboard-war-room).

![Dashboard in replay mode](docs/screenshots/replay-1920x1080.png)

> **Honest verdict:** following these signals mechanically did **not** beat SPY between 2020 and 2025, and none of ten more selective, literature-based variants passed a pre-registered out-of-sample test either. See [Backtest result](#backtest-result) and [Phase 2 research](#phase-2-research).
>
> This is a research tool, not investment advice. Nothing here is a recommendation to buy or sell any security.

## Quickstart

Requires Python 3.13, [uv](https://docs.astral.sh/uv/) and [Node.js](https://nodejs.org) 20.19 or newer.

```bash
uv sync
cp .env.example .env      # then set SEC_USER_AGENT
./dev --replay            # historical replay, no SEC traffic needed beyond logos/prices
./dev                     # LIVE: polls the real SEC feeds
```

Open <http://localhost:5173>. `./dev` starts the API server (`uv run radar serve`) and the dashboard (`npm run dev` in `web/`) together and stops both on Ctrl+C. The first run installs the dashboard dependencies. Change the server port with `RADAR_PORT=8010 ./dev`; any extra option is passed to `radar serve`.

To run everything from a single process, without the dev server:

```bash
(cd web && npm install && npm run build)   # builds web/dist
uv run radar serve                         # API, WebSocket, collector and dashboard on http://localhost:8000
```

## Configuration

### `.env`

`.env` is never committed. Only one variable is required.

| Variable | Required | Purpose |
|---|---|---|
| `SEC_USER_AGENT` | **yes** | Identification required by the SEC, in the form `"Name contact@domain"`. Use your own name or project and an e-mail of yours. Without it, commands stop with an explanation. |
| `CLAUDE_CODE_OAUTH_TOKEN` | no | Only for AI summaries on a machine without a Claude Code login (see below). |
| `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` | no | With both set, alerts also go to Telegram. |
| `RADAR_ALERTS` | no | Comma-separated alert channels: `console`, `macos`, `telegram`. Default: `console`. |
| `RADAR_LANG` | no | Language for AI summaries, alerts and CLI output: `en` or `pt-BR`. Overrides `lang` in `radar.toml`. Default: `en`. |
| `RADAR_DATA_DIR` | no | Where the database and cache live. Default: `./data`. |
| `RADAR_CONFIG` | no | Parameters file. Default: `./radar.toml`. |

### `radar.toml`

All thresholds (signal rules, SEC rate limit, AI cap, backtest costs and filters) live in [`radar.toml`](radar.toml), with a comment on every key. The top-level `lang` key sets the language of AI summaries, alerts and CLI output (`en` by default, or `pt-BR`).

### AI summaries

Each signal gets a 3–5 line summary (who, how much, context). It is written by the [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/python), which uses the Claude Code installation on your machine and **your own subscription**.

- **Nothing to configure.** Just be logged in to Claude Code: run `claude` and use `/login`.
- On a server or a machine without a login, create a token with `claude setup-token` and put it in `CLAUDE_CODE_OAUTH_TOKEN`.
- `ANTHROPIC_API_KEY` is **not used**. If it is in the environment, the radar removes it before calling the AI, so a call is never billed through the API.
- The subscription has a quota, so the AI is only called for signals that fire (never for every filing), once per filing and language (the summary is cached in SQLite), and capped at 30 calls per hour.
- Summaries are written in the configured `lang`. The dashboard shows the AI summary in that language and a deterministic template summary in the other one.
- If the AI fails for any reason (no login, quota exhausted, timeout), the template summary is used and the reason is logged. The system never depends on the AI: `--no-ai` turns it off.
- The backtest does not use AI.

## Commands

### `radar watch`

```bash
uv run radar watch --once          # one cycle: fetch, process, flag, alert
uv run radar watch --interval 60   # repeat every 60 seconds until Ctrl+C
```

Each cycle reads the EDGAR feeds, stores new filings (without duplicates), extracts their data, applies the rules and sends alerts. Useful options: `--alert console --alert macos` (channels for this run only), `--no-ai` (template summaries only), `--lang pt-BR` (language for this run) and `-v` (more logging).

The first run downloads a few hundred of the day's filings, which takes about a minute. After that each cycle only fetches what is new and takes a few seconds. When the radar sees an open-market purchase it also fetches the issuer's Form 4 filings from the last 44 days, so `cluster_buy` sees purchases made before the monitor was started.

### `radar signals`

```bash
uv run radar signals --since 7d                       # signals from the last 7 days
uv run radar signals --since 24h --type cluster_buy   # filter by type
uv run radar signals --since 2026-01-01 --full        # with the full summary
```

`--since` accepts `24h`, `7d`, `2w`, `3m` or a `YYYY-MM-DD` date.

### `radar backtest`

```bash
uv run radar backtest --start 2020-01-01 --end 2025-12-31
```

Downloads the SEC history, replays the rules and writes:

- `reports/backtest-<date>.md` — tables and verdict, in English;
- `reports/backtest-<date>.pt-BR.md` — the same report in Brazilian Portuguese;
- `reports/backtest-<date>-signals.csv` — one signal per row (not versioned, it is large);
- `reports/backtest-<date>-replay.jsonl.gz` — signals with details and outcome, for the dashboard REPLAY mode.

`radar backtest` always writes both reports; `--lang` only picks the language of its console output. The first run downloads about 350 MB from the SEC plus prices for about 3,000 tickers; it takes 15 to 40 minutes, depending on how much Yahoo throttles requests. Later runs use the cache and take a few minutes.

### `radar report`

```bash
uv run radar report                    # re-render both reports from the latest signals CSV
uv run radar report --lang pt-BR       # only the pt-BR report
```

Re-renders the Markdown reports from an existing signals CSV, using the cached SEC datasets and no price downloads. A CSV from the first (Portuguese) version is converted to the English columns.

### `radar phase2`

```bash
uv run radar phase2 collect            # SEC datasets and filings, prices (hours the first time; resumable)
uv run radar phase2 run --split train  # 2020–2022: measure every pre-registered variant
uv run radar phase2 freeze --stake 0.2 --dip 0.3   # record the parameters chosen on train
uv run radar phase2 run --split test   # 2023–2025: refuses to run before the freeze
uv run radar phase2 report             # reports/phase2-<date>.md and the dashboard summary .json
```

The research behind [Phase 2 research](#phase-2-research). Everything intermediate stays in `data/phase2/`. `--prices tiingo` uses a Tiingo key (`TIINGO_API_KEY`) instead of Yahoo; no key is needed by default.

### `radar serve` and `radar replay-build`

```bash
uv run radar serve                                   # LIVE
uv run radar serve --replay --replay-start 2022-01-03 --replay-speed 4
uv run radar serve --no-ai --interval 120 --port 8010
uv run radar replay-build                            # rebuild only the replay file from the latest backtest CSV
```

| Option | Purpose |
|---|---|
| `--replay` | Turns on REPLAY mode. |
| `--replay-start YYYY-MM-DD` | Replay start date. Default: 2020-02-18. |
| `--replay-speed N` | Simulated days per minute. Default: 2. |
| `--interval N` | LIVE: seconds between collection cycles. Default: 60. |
| `--alert channel` | LIVE: alert channel in addition to the dashboard (console, macos, telegram). |
| `--no-ai` | Template summaries only. |
| `--price-interval N` and `--no-prices` | Quote polling interval, or quotes off. |
| `--host` and `--port` | Where the server listens. Default: `127.0.0.1:8000`. |

The server has no authentication. It only listens on `127.0.0.1`; think twice before exposing it with `--host 0.0.0.0`.

## Dashboard (war room)

A full-screen, dark, dense screen, with signals arriving over WebSocket.

| Panel | Content |
|---|---|
| Top bar | LIVE or REPLAY badge, New York and Brasília clocks, market session, SPY, QQQ, IWM and VIX, and the state of the SEC collector, AI, WebSocket and prices. **EN / PT** toggle. |
| 01 Signals | One card per signal: logo, ticker, type, insiders (name, role and value), amount bought, score and sector. New signals enter at the top, highlighted. |
| 02 Signal in focus | Price chart with the filing day and the insider purchases marked, the average price paid, the summary (AI or template), the rule that fired and the company's purchase history. |
| 03 Buying radar | A radar scope by sector (each blip is a company, size is the amount bought, the rim is today) and the companies with the most buying in 7 or 30 days. |
| Tape | New filings (Form 4 and 13D) scrolling by, with the latest pinned on the left. |

The dashboard opens each new signal by itself. If you click another one, it waits two minutes before following new signals again (or click "Pinned" to resume right away). Arrow keys move through the signals.

**Small caps.** The backtests only found evidence for the *avoid* filters (late filings, crowded shorts, CEO/CFO exits, auditor changes, Form 144 clusters and large planned sales, persistent fails-to-deliver, bankruptcies) on liquid stocks. So, by default, these signals are shown only when the company's latest price is at least $5 and its market value (price × shares outstanding from the 10-Q/10-K cover) at least $300M; a company of unknown size counts as small. "Show small caps" in the signals panel reveals the rest (the choice is remembered in the browser), and avoid cards show the price and market value. Thresholds: `[dashboard]` in `radar.toml`. Long and context signals are never hidden.

![Live room: "Show small caps" under the signal count; avoid cards with price and market value](docs/screenshots/live-small-caps-1920x1080.png)

**Language.** The dashboard is bilingual: English (default) and Brazilian Portuguese. The EN / PT toggle in the top bar switches everything live, including numbers, currency and dates (`$2.2M` / `Nov 18` vs `US$ 2,2 mi` / `18 nov`). The choice is remembered in the browser; the first visit follows the browser language.

![Dashboard in Portuguese](docs/screenshots/replay-pt-BR-1920x1080.png)

### LIVE and REPLAY

- **LIVE** runs the same cycle as `radar watch` inside the server, every 60 seconds, and publishes each filing and signal as soon as it is processed. Red badge with a blinking light.
- **REPLAY** plays back the 9,018 backtest signals from 2020 to 2025, two simulated days per minute. It is meant for demos and to keep the room alive: real signals are few per day. Amber badge, a striped band at the top and the simulated date front and center. You can pause and speed it up from the dashboard.

In replay each signal carries the **outcome measured by the backtest**: the 1, 3 and 6 month return against SPY, or why it couldn't be measured. The replay reads `reports/backtest-<date>-replay.jsonl.gz`, which is versioned (≈2.4 MB).

| LIVE | REPLAY (2560×1440) |
|---|---|
| ![Live mode](docs/screenshots/live-1920x1080.png) | ![Replay at 1440p](docs/screenshots/replay-2560x1440.png) |

### API

| Route | Returns |
|---|---|
| `GET /api/health` | Mode and state of the collector, AI, prices and WebSocket. |
| `GET /api/state` | The same snapshot sent when a WebSocket connects. |
| `GET /api/signals?limit=&since=&type=` | Signals, newest first. |
| `GET /api/signals/{id}` | One signal with purchases, the company's previous signals and the chart range. |
| `GET /api/filings` | The latest filings, summarized. |
| `GET /api/company/{cik}` | A company's signals and purchases. |
| `GET /api/ranking?days=7` | Companies and sectors with the most buying in 7 or 30 days. |
| `GET /api/backtest` | Numbers from the latest backtest report. |
| `GET /api/quotes` | Latest quotes. |
| `GET /api/prices/{ticker}/history?start=&end=` | Daily bars. |
| `GET /api/logo/{ticker}` | The PNG logo, or 404. |
| `GET /api/events?limit=&source=` | Events of the extra sources (Form 144, 8-K, 13F, short data). |
| `GET /api/company/{cik}/context` | A company across all sources: signals, insider buys, Form 144, 8-K, 13F and short data. |
| `POST /api/replay/control` | REPLAY: `{"paused": true}`, `{"speed": 5}` or `{"seek": "2021-03-01"}`. |

LIVE signals also carry `price`, `price_as_of`, `market_value`, `liquid` and `liquidity_gated` (an avoid signal hidden by default unless `liquid`). Prices come from the quote service (cached for 12 hours); shares outstanding from the SEC company concept API, at most once a day per company.

The WebSocket lives at `/ws`. On connect the server sends a `snapshot` with everything the screen needs, then numbered events (`seq`): `signal.new`, `filing.new`, `price.tick`, `system.status`, `ranking.update`, `feed.reset`, `market_event.new` (an event of the extra sources) and `signals.update` (signals already on screen with a new price and market value). The client reconnects on its own with exponential backoff and receives a fresh snapshot, so nothing is lost. The server sends codes (filing kinds, sectors, roles, states) and `{"en", "pt-BR"}` maps for generated text (explanations, summaries, verdict), so the dashboard can switch language without refetching.

## Architecture

```mermaid
flowchart LR
  subgraph Sources
    EDGAR["SEC EDGAR<br/>getcurrent feeds + filings"]
    DS["SEC insider<br/>transaction datasets"]
    YF["Yahoo Finance<br/>(yfinance)"]
    LOGO["Logo endpoints<br/>(FMP, nvstly/icons)"]
    CLAUDE["Claude Agent SDK<br/>(logged-in Claude Code)"]
  end

  subgraph Python["radar (Python)"]
    HTTP["http.py<br/>rate limit, retry, cache"]
    PARSE["parsers/<br/>Form 4, 13D"]
    RULES["signals.py<br/>shared rules"]
    DB[("SQLite<br/>data/radar.sqlite")]
    SUM["summary.py + ai.py<br/>AI or template, en/pt-BR"]
    ALERT["alerts/<br/>console, macOS, Telegram"]
    BT["backtest/<br/>returns, stats, report"]
    API["api/<br/>FastAPI REST + WebSocket<br/>live and replay engines"]
  end

  WEB["web/<br/>React war room<br/>typed i18n catalogs en / pt-BR"]
  REP[("reports/<br/>backtest .md, replay .jsonl.gz")]

  EDGAR --> HTTP --> PARSE --> DB --> RULES
  RULES --> SUM --> ALERT
  CLAUDE -.-> SUM
  DS --> BT
  YF --> BT
  RULES --> BT --> REP
  DB --> API
  REP --> API
  YF --> API
  LOGO --> API
  API <-->|REST + WS| WEB
```

The same rule functions run in the live monitor and in the backtest, so what the backtest measures is exactly what the monitor fires.

```
src/radar/
  cli.py            watch, signals, backtest, report, serve and replay-build commands
  config.py         .env and radar.toml
  i18n.py           language handling and lookups; catalogs in locales/ (en, pt_br)
  http.py           SEC client: User-Agent, rate limit, retry, cache
  feed.py           "getcurrent" Atom feed
  edgar.py          EDGAR submission (.txt) files
  parsers/          Form 4 (XML) and Schedule 13D (new XML and legacy HTML)
  signals.py        the three rules, shared by the monitor and the backtest
  db.py             SQLite: filings, transactions, signals, AI cache and usage, schema migrations
  ai.py             Claude Agent SDK call
  summary.py        AI summary, cache, hourly cap and template
  alerts/           console, macOS and Telegram
  watch.py          the monitor cycle
  backtest/         datasets, prices, returns, statistics, report and replay file
  research/         phase 2: SEC outcomes and price tape, price sources, variants, 10-K text,
                    calendar portfolios, report (`radar phase2`)
  sectors.py        issuer sector from the SIC code
  sources/          extra sources (form144, eightk, thirteenf, short): rules, history, live
                    pollers, source tables, new-signals backtest and report
  api/              dashboard server (REST, WebSocket, live and replay engines, prices, logos)
web/                dashboard (React, TypeScript, Vite)
tests/              offline tests, with real filings in tests/fixtures
dev                 starts server and dashboard together
```

To add an alert channel, write a class with `name` and `send(signal)` and register it with `radar.alerts.register("name", factory)`.

## The signals

| Signal | Rule |
|---|---|
| `cluster_buy` | At least 2 distinct insiders buy the same issuer's stock on the open market (code P) within 14 days, totaling at least $100K. |
| `big_officer_buy` | The CEO or CFO buys at least $250K on the open market in a single Form 4. |
| `activist_13d` | A new Schedule 13D (not an amendment) declares a stake of 5% or more. |

Details that change the result:

- **Only code P counts.** It is an open-market purchase with the insider's own money. Grants (A), option exercises (M), gifts (G), tax withholding (F) and other codes are stored but never fire a signal.
- **A signal is born on the filing date.** The signal date is the day the Form 4 reached the SEC, never the transaction date. The cluster looks at purchases from the previous 14 days, and only those already public.
- **"Distinct" means distinct.** A joint Form 4 (fund, manager and partner) counts as one insider. So do two Form 4s reporting the same transaction with the same resulting position.
- **Amendments don't count.** Form 4/A and 13D/A repeat information already disclosed.
- **Funds are left out.** `cluster_buy` and `big_officer_buy` ignore closed-end funds and similar vehicles, whose directors and adviser buying fund shares is not an insider bet on a business. An issuer is a fund when its SIC (from the SEC registry) is 6722 or 6726 (investment offices; 6798, REITs, stays in), or when it has no SIC (registered funds such as BNY Mellon Strategic Municipals show `0000`) and files registered-fund reports (N-CSR, NPORT-P, N-CEN...). When the registry gives no answer, a tight name heuristic ("Municipal Income Fund", "Credit Trust") decides. BDCs file 10-Qs and stay in. Same rule live, in the backtest and on the dashboard (stored fund signals are hidden, not deleted). Settings: `exclude_funds`, `fund_sic_codes` and `fund_name_heuristic` under `[signals]`.
- **30-day cooldown.** After firing, the same signal type doesn't repeat for the same issuer within that period.
- **Score from 0 to 100.** A heuristic to rank alerts (more insiders, larger value, CEO/CFO present, larger stake). The backtest report shows whether it relates to returns (it doesn't).

The 13D format changed in December 2024: since then it is structured XML, read field by field. For older filings, in HTML or text, the radar extracts what it can from the cover page (names and percentage) and says in the explanation that the data came from free text.

## Backtest result

Reference run: 2020-01-01 to 2025-12-31, default rules. It predates the fund exclusion and was not rerun: the next `radar backtest` (or `radar report`, which drops fund rows from an existing CSV) lists the excluded signals in the data funnel. Full report: [`reports/backtest-2026-11-18.md`](reports/backtest-2026-11-18.md) ([pt-BR](reports/backtest-2026-11-18.pt-BR.md)).

**The signals did not beat SPY.** The typical signal lost to the index at every horizon, and fewer than half of the signals ended above it.

| Signal | Horizon | Signals measured | Mean return | Median return | Mean excess vs SPY | Median excess vs SPY | Beats SPY |
|---|---|---|---|---|---|---|---|
| `cluster_buy` | 1 month | 4,903 | +0.8% | -0.1% | -0.7% | -1.7% | 43.6% |
| `cluster_buy` | 3 months | 4,903 | +6.3% | +2.2% | +0.7% | -3.1% | 42.9% |
| `cluster_buy` | 6 months | 4,903 | +9.8% | +2.4% | -0.0% | -6.5% | 40.6% |
| `big_officer_buy` | 1 month | 1,746 | +0.1% | +0.0% | -0.9% | -1.2% | 44.8% |
| `big_officer_buy` | 3 months | 1,746 | +5.0% | +1.1% | +0.5% | -3.1% | 43.5% |
| `big_officer_buy` | 6 months | 1,746 | +8.6% | +1.7% | -0.2% | -6.4% | 41.0% |

Returns are net of a 0.2% round-trip cost.

- **The signals made money, but the index made as much or more.** At 6 months the mean return was about 9%, practically the same as SPY over the same dates.
- **The mean is misleading.** Mean excess is near zero because a few stocks multiplied in value and offset the majority that lagged. The median, the typical case, is negative at every horizon (down to -6.5% at 6 months).
- **Nothing is statistically distinguishable from chance.** The highest t-stat by monthly cohort is 0.2; the bar for evidence would be 2.
- **Filtering for liquidity doesn't save it.** With price ≥ $5 and market cap ≥ $300M, the 6-month median excess stays negative: -4.3% for `cluster_buy` and -4.9% for `big_officer_buy`.
- **Same picture against small caps.** Swapping SPY for IWM, the 6-month mean excess goes to +0.7%, but the median stays at -5.3% and -4.6%.
- **It depends on the year.** 2020 was the only good year (+14% and +18% mean excess at 6 months, in the post-pandemic recovery). 2021 was the worst (-14% and -11%). From 2022 to 2025 the 6-month median excess was between -4% and -13%.
- **The score doesn't help.** High-score signals did not do better than low-score ones.
- **26% of the signals could not be measured** (2,369 of 9,018), mostly (1,459) because the ticker has no price on Yahoo, which usually means a delisted company. This is the largest uncertainty in the result.

Bottom line: following these signals mechanically, with these rules, did not justify the risk between 2020 and 2025. Phase 2 (below) tested more selective cuts out of sample and put the delisted companies back: neither changed the conclusion.

## Phase 2 research

Pre-registered plan: [`research/phase2-plan.md`](research/phase2-plan.md) (committed, with dated addenda, before the test run). Full report: [`reports/phase2-2026-11-18.md`](reports/phase2-2026-11-18.md).

**Method.** Rules and the two free parameters were chosen on signals filed in 2020–2022 (train), frozen, then run once on 2023–2025 (test). Each variant is measured per signal and as an equal-weighted calendar-time portfolio (every signal held 3 months), with Newey-West t-stats and alphas against SPY and IWM, costs of 0.2% round trip (1% below $5). A variant passes only if, in the test period, its median excess is positive and its monthly portfolio t ≥ 2 **against both SPY and IWM**.

**Survivorship correction, without paid data.** For signals Yahoo can't price, the company's own SEC filings say what happened (Form 25 and 15, merger proxies and tender offers, 8-K items 1.03, 2.01 and 5.01), and Form 4 transaction prices act as a free price tape (median error about 1% against Yahoo). Measured phase-1 signals went from 74% to 83%. The companies brought back did **worse** than the rest (median 3-month excess vs SPY −6.4%), so the correction makes the phase-1 verdict slightly more negative, not less.

**Result (test period, 3 months): no variant passed.**

| Variant | Idea | Median excess vs SPY / IWM | Portfolio t vs SPY / IWM | Verdict |
|---|---|---|---|---|
| `insider_buy` | officer/director open-market buy ≥ $50K (the base) | −4.1% / −2.7% | −0.8 / 0.7 | discard |
| `opportunistic_buy` | Cohen, Malloy & Pomorski "opportunistic" insiders | −3.3% / −1.6% | −0.4 / 0.9 | discard |
| `first_buy` | first purchase in 24 months | −3.6% / −2.6% | −1.6 / −1.0 | discard |
| `stake_jump` | position up ≥ 20% | −4.3% / −3.2% | −1.3 / −0.4 | discard |
| `dip_buy` | stock down ≥ 30% in 3 months | −4.4% / −4.0% | 0.0 / 0.6 | discard |
| `csuite_cluster` | CEO and CFO (or 3 officers) buying within 14 days | −3.5% / −2.2% | −0.5 / 0.7 | discard |
| `opportunistic_dip`, `first_big_stake` | combinations | −1.7% to −4.1% | −1.9 to −0.6 | discard |
| `lazy_nonchangers` | 10-K barely changed vs last year ("Lazy Prices") | −6.2% / −0.9% | −3.0 / −1.5 | discard |
| `insider_buy_text_ok` | insider buy, 10-K not in the most-changed quintile | −2.9% / −1.6% | −0.7 / 1.0 | discard |
| `cluster_buy` (phase 1) | unchanged | −4.3% / −3.1% | −1.6 / −0.6 | discard |
| `big_officer_buy` (phase 1) | unchanged | −4.5% / −2.3% | −0.3 / 2.3 | discard |

The closest call, `big_officer_buy`, beat IWM by 0.5% a month (t 2.3) but lost to SPY and its typical signal lost to both; it was also negative in train. The 10-K text signal reversed between train and test. Because no variant passed, **no new signal type was added to the live monitor**; the full verdict is in [`reports/phase2-2026-11-18.md`](reports/phase2-2026-11-18.md). A feasibility study for Brazil (CVM/B3 data) is in [`research/b3-feasibility.md`](research/b3-feasibility.md).

### How each signal is measured

1. The signal becomes public on the filing date.
2. **Entry** at the close of the first trading day *after* that date.
3. **Exit** 1, 3 and 6 months later, at the close.
4. A 0.2% round-trip cost is subtracted.
5. **Excess** is that net return minus SPY's return over the same dates.

Read, in this order: **median excess** (the typical signal), **beats SPY** (share of signals with positive excess), **t (monthly cohort)** (above 2 is evidence), the **liquidity-filtered tables**, the **per-year breakdown** and the **data funnel** (how many signals went unmeasured and why).

## Extra signal sources

Besides Form 4 and 13D, the radar watches four more free, public sources. Each one lives in
`src/radar/sources/<source>/` with the same parts (parser, pure rules shared by live and backtest,
point-in-time history, live poller) and is shown on the dashboard with its own chips, cards,
tape events and company context.

| Source | What it watches | Signals | Live pace |
|---|---|---|---|
| **Form 144** | Notices of planned sales by affiliates (electronic since 2023-04) | `form144_cluster` (3+ sellers in 10 days), `form144_large` (≥ US$ 10 mi or ≥ 1% of shares; context, not tested) | every cycle |
| **8-K / NT** | Current reports classified by EDGAR item; late-filing notices | `buyback_8k`, `ceo_cfo_exit_8k` (5.02), `bankruptcy_8k` (1.03), `auditor_change_8k` (4.01), `late_filing_nt`; merger agreements, completed deals and earnings releases as context | every cycle (NT every 15 min) |
| **13F** | Quarterly holdings of managers > US$ 100 mi | `fund_consensus_13f` (breadth of ownership, dated at the 45-day deadline), `notable_fund_new_13f` (new positions of a fixed list of managers) | every 15 min; consensus job after each deadline |
| **Short data** | FINRA short interest and daily short volume, SEC fails-to-deliver | `short_crowded`, `squeeze_setup`, `ftd_persistent`; short volume as context | hourly checks |

US Congress trades (House/Senate STOCK Act filings) and event calendars (IPO lock-ups,
earnings dates) were evaluated and **skipped**: trades live in free-layout PDFs, the Senate site
needs a scripted session, and there is no free structured calendar. The reasoning is in
[`research/new-signals-plan.md`](research/new-signals-plan.md).

```bash
uv run radar backtest-sources                 # reports/new-signals-<date>.md and .pt-BR.md
```

The rules, periods (train 2020–2022, test 2023–2025) and verdict criteria were fixed in the plan
**before** any backtest ran. Same price engine and benchmarks as the insider backtest; costs
0.2% round trip, 1% under US$ 5. Verdict at the primary horizon, test period, excess over SPY
(full report: [`reports/new-signals-2026-11-18.md`](reports/new-signals-2026-11-18.md)):

| Signal | Hypothesis | Test N | Excess mean / median | t | Verdict | Liquid subset¹ |
|---|---|---|---|---|---|---|
| `buyback_8k` (6m) | beats | 1,276 | -4.2% / -5.9% | -3.5 | discard | discard |
| `ceo_cfo_exit_8k` (3m) | lags | 508 | -6.2% / -13.6% | -1.0 | maybe (avoid) | maybe (avoid) |
| `bankruptcy_8k` (1m) | lags | 54 | -30.4% / -38.9% | -3.0 | maybe (avoid) | insufficient data |
| `auditor_change_8k` (3m) | lags | 1,860 | +160%² / -12.4% | 1.3 | discard² | maybe (avoid) |
| `late_filing_nt` (3m) | lags | 4,949 | +864%² / -16.9% | 1.2 | discard² | **avoid** |
| `form144_cluster` (3m) | lags | 6,130 | -1.0% / -3.7% | -0.9 | maybe (avoid) | maybe (avoid) |
| `fund_consensus_13f` (3m) | beats | 349 | +2.0% / -0.2% | 1.7 | discard | maybe |
| `notable_fund_new_13f` (3m) | beats | 619 | -0.1% / -1.1% | 0.0 | discard | discard |
| `short_crowded` (1m) | lags | 916 | -1.3% / -1.7% | -1.0 | maybe (avoid) | **avoid** |
| `squeeze_setup` (1m) | beats | 93 | -4.8% / -8.3% | -2.5 | discard | insufficient data |
| `ftd_persistent` (1m) | lags | 587 | -12.8% / -16.5% | -5.3 | maybe (avoid) | maybe (avoid) |

¹ Entry price ≥ US$ 5 and market value ≥ US$ 300 mi: a view fixed in the plan, not the basis of
the verdict. ² The mean is dominated by sub-penny OTC quotes (US$ 0.0001 jumping to dollars);
the median is the meaningful number. **No new signal earned "use".** The useful ones are
filters: late filings and crowded, rising short interest lagged the index among liquid stocks,
and fails-to-deliver, CEO/CFO exits and bankruptcies lagged strongly but without a consistent
train period or significance. Survivorship (Yahoo has almost no delisted tickers) makes every
*avoid* number look less negative than it was.

![Live room with the extra sources](docs/screenshots/live-sources-1920x1080.png)

On the dashboard: source chips above the signal feed (then type chips for the chosen source),
cards with a source badge, an icon and text tags for the hypothesis (**Avoid**, **Bullish**) and
**Not tested**, the source events on the tape, and a "company across all sources" block in the
focused signal (insider buys, Form 144, 8-K, 13F, short interest, short volume and fails).
AI summaries cover the new signals within the same hourly cap. Turn sources on or off in
`radar.toml` (`[sources] enabled`).

## Data sources and terms

| Source | Used for | Terms |
|---|---|---|
| [SEC EDGAR](https://www.sec.gov/edgar) ("getcurrent" feeds, filing archives, company submissions) | Live monitoring, sectors | Public data. The radar follows the SEC [fair access policy](https://www.sec.gov/os/accessing-edgar-data): a declared `User-Agent`, at most 8 requests per second (the limit is 10), backoff on 429/5xx and a local cache so nothing is downloaded twice. |
| [SEC insider transactions data sets](https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets) | Backtest | Public data, same fair access policy. |
| [EDGAR full-text search](https://efts.sec.gov/LATEST/search-index) and [SEC Form 13F](https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets) / [fails-to-deliver](https://www.sec.gov/data-research/sec-markets-data/fails-deliver-data) data sets | Extra sources: history and live | Public data, same fair access policy and rate limiter. |
| [FINRA Query API](https://developer.finra.org) (consolidated short interest) and [daily short volume files](https://www.finra.org/finra-data/browse-catalog/short-sale-volume-data) | Short-data source | Public datasets, no credentials; a few requests per day, cached. |
| [Yahoo Finance](https://finance.yahoo.com) via [yfinance](https://github.com/ranaroussi/yfinance) | Backtest prices, delayed dashboard quotes and charts | Unofficial API, not affiliated with Yahoo; data is for personal use under Yahoo's terms and comes with no guarantee. Quotes are delayed about 15 minutes. |
| [Financial Modeling Prep](https://financialmodelingprep.com) public image endpoint, with [nvstly/icons](https://github.com/nvstly/icons) as fallback | Company logos on the dashboard | Logos are trademarks of their owners, fetched on demand and cached locally (`data/cache/logos/`), never committed. Only the ticker is sent. |
| [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/python) | Optional AI summaries | Runs on your own Claude Code login/subscription and its terms. |

## Limitations

The report lists all of them with the run's numbers. The main ones:

- **Survivorship bias.** Yahoo Finance keeps prices for almost no delisted companies. Phase 2 corrects most of it from SEC data (see [Phase 2 research](#phase-2-research)), approximately: Form 4 prices are noisy, and 17% of phase-1 signals remain unmeasured.
- **Illiquid microcaps.** Much insider buying happens in small companies, where the spread costs far more than the assumed 0.2%.
- **Idealized execution.** Buys and sells exactly at the close, with no price impact and no size limit.
- **Hand-entered data.** Ticker, title and price are typed by the filer. Gross errors are filtered; subtle ones get through. CEO/CFO detection is based on the title text.
- **13D is not in the backtest.** The historical data sets cover only Forms 3/4/5.
- **Older 13Ds are read heuristically.** There was no XML before December 2024.
- **The monitor depends on the "getcurrent" feed**, which shows only the most recent filings. If the radar is off for days, what left the feed meanwhile is not recovered (except recent Form 4s of issuers with a new purchase).
- **Dashboard prices are delayed** about 15 minutes and come from a free source with no guarantee.
- **The live buying radar only sees what is in the database.** The 30-day window is incomplete until the monitor has run for 30 days; the dashboard shows since when the database has coverage.
- **Replay shows today's ticker and logo**, not the historical ones. Companies that left the SEC registry show a monogram and, usually, no chart.

## Tests

```bash
uv run pytest                                    # backend
uv run ruff check src tests                      # lint
(cd web && npm run lint && npm test && npm run build)   # dashboard
```

Tests never use the network, a login or a token. Parsers run against real filings saved in `tests/fixtures`; the monitor and the backtest run end to end with the SEC, Yahoo and the AI faked. The API and WebSocket are tested with fake price and logo sources, in both modes. In the dashboard, vitest covers state, WebSocket reconnection, locale-aware formatting, the language toggle and the main components. CI runs all of this on every push and pull request.

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE) © 2026 Jonatas Soares. Company logos, SEC data and Yahoo Finance data are not covered by this license and remain subject to their owners' terms (see [Data sources and terms](#data-sources-and-terms)).

## Disclaimer

radar-sec is a personal research project. It is **not investment advice**, not a recommendation to buy or sell any security, and not affiliated with the SEC, Yahoo, Financial Modeling Prep or Anthropic. Data may be delayed, incomplete or wrong. Past results, including the backtest above, do not predict future results. Do your own research and use it at your own risk.
