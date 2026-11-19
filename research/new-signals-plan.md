# New market signals: research plan (pre-registered)

Written on 2026-11-18, **before** any backtest of these signals was run. The rules,
thresholds, horizons, periods and verdict criteria below are fixed here and will not be
changed after looking at results. If a rule turns out to be unimplementable as written,
the change and the reason will be recorded in the report, not silently applied.

Context: the phase-1 insider signals (`cluster_buy`, `big_officer_buy`) did not beat SPY
in 2020–2025 (`reports/backtest-2026-11-18.md`). This plan widens the radar to other
free, public sources. Another agent is refining the Form 4/13D signals in parallel; this
work does not touch them.

## 1. Sources: what was checked and what was chosen

All URLs and formats below were fetched and inspected on 2026-11-18.

| # | Source | Access checked | Decision |
|---|---|---|---|
| 1 | **Form 144** (notice of proposed sale) | Live: EDGAR `getcurrent` Atom feed `type=144` (≈300 filings/day). Document: `primary_doc.xml` inside the `.txt` submission (issuer, seller, relationship, units, aggregate market value, units outstanding, approximate sale date, how the shares were acquired). History: EDGAR full-text search (`efts.sec.gov/LATEST/search-index?forms=144`) returns issuer + seller CIKs per filing, per day. Electronic filing is mandatory only since 2023-04-13. | **Implement** (live + backtest of a count-based rule from 2023-05). |
| 2 | **13F-HR** (quarterly holdings of managers > US$ 100 mi) | History: SEC *Form 13F Data Sets* (quarterly zips by **filing date**, 64–90 MB each; `SUBMISSION`, `COVERPAGE`, `INFOTABLE` TSVs). Live: `getcurrent` feed `type=13F-HR` plus the filing's information-table XML. CUSIP → ticker: SEC fails-to-deliver files carry both CUSIP and symbol. | **Implement** (live + backtest 2020–2025). |
| 3 | **8-K by item**, plus **NT 10-K / NT 10-Q** | Live: `getcurrent` feed `type=8-K`; the Atom `<summary>` already lists the items ("Item 5.02: …"), so most filings need no extra request; the `.txt` is downloaded only when text is needed. History: EDGAR full-text search returns `items`, `file_date`, CIKs and tickers per document and supports exact-phrase queries. `forms=NT 10-K,NT 10-Q` works the same way. | **Implement** (live + backtest 2020–2025). |
| 4 | **Short interest, short volume, fails-to-deliver** | FINRA Query API, dataset `otcMarket/consolidatedShortInterest`, **no credentials needed**, ≈19k rows per settlement date (exchange-listed and OTC, 5,000 rows per page, history back to at least 2020). FINRA daily short volume files `cdn.finra.org/equity/regsho/daily/CNMSshvol<YYYYMMDD>.txt` (public). SEC fails-to-deliver half-month zips (`/files/data/fails-deliver-data/cnsfails<YYYYMM><a|b>.zip`); the SEC page says the first half of a month is posted at the end of that month and the second half around the 15th of the next; HTTP `Last-Modified` confirms (2024-01a → 2024-01-30, 2024-01b → 2024-02-15). | **Implement** (live + backtest 2020–2025; daily short volume is context only). |
| 5 | **US Congress trades** (STOCK Act) | House: yearly index zip `disclosures-clerk.house.gov/public_disc/financial-pdfs/<YEAR>FD.zip` works (451 PTRs in 2024), but each trade lives inside a PDF (`ptr-pdfs/<YEAR>/<DocID>.pdf`); electronic ones are text PDFs with a free layout, paper ones are scans. Senate: `efdsearch.senate.gov` answers **403** to a plain client; it requires accepting terms in a session with CSRF tokens. | **Skip.** Parsing free-layout PDFs and driving the Senate session is exactly the fragile scraping the brief rules out. Revisit if an official structured feed appears. |
| 6 | **Event calendar** (IPO lock-up expiry, earnings dates) | Lock-up: would require reading lock-up terms from S-1/424B prose; no structured source. Earnings dates: no free official calendar; vendor pages are scraping. | **Skip as a signal.** As context, 8-K **Item 2.02** (results of operations) marks the actual earnings release date and is shown in the company panel. |

Four sources are implemented: **Form 144, 13F, 8-K/NT, short (FINRA + SEC FTD)**.

## 2. Common rules for every backtest

These copy the phase-1 engine (`radar.backtest.returns`, `radar.backtest.prices`) so the
numbers are comparable.

- **Dating.** A signal is dated by the day its information became public: filing date
  for EDGAR documents, publication date for FINRA/SEC data files (rules per source
  below). Never by the event or trade date.
- **Entry** at the close of the first trading session strictly after the signal date.
  **Exit** at the close 1, 3 and 6 months later. Adjusted closes (Yahoo Finance, same
  DuckDB cache).
- **Costs.** 0.2% round trip; **1.0%** round trip when the unadjusted close on the entry
  day is below US$ 5.
- **Benchmarks.** Excess return vs **SPY** (main) and vs **IWM**, over the same dates.
- **Periods.** Train = signals dated 2020-01-01 to 2022-12-31; Test = 2023-01-01 to
  2025-12-31. Nothing is tuned on either: "train" is only used to check that the sign is
  stable. Form 144 has no history before 2023-04 (see its section).
- **Tickers.** EDGAR sources: current ticker from the SEC cadastre (`company_tickers.json`)
  by CIK, else the ticker shown in the filing. 13F: CUSIP → symbol from the SEC FTD files
  of the same or nearest period. FINRA/FTD: symbol as published. Unmapped signals are
  counted in the funnel, not silently dropped.
- **Data hygiene.** Same discards as phase 1: no prices (usually delisted), no price near
  entry, suspicious split-like jump (≥5× from below US$ 1).
- **Cooldown.** The same signal type does not fire again for the same issuer within
  30 days (90 days for buybacks; 1 quarter is implicit for 13F).
- **Statistics.** Per signal × horizon: N, hit rate, share beating the index, mean,
  median, winsorized mean (1–99%) of excess, and the **t-stat of monthly-cohort mean
  excess** (one point per month, as in phase 1). Plus a liquidity subset: entry price
  ≥ US$ 5 and market value ≥ US$ 300 mi (shares outstanding from XBRL `dei` frames with a
  45-day lag, as in phase 1).
- **No AI** anywhere in the backtest.

### Verdict criteria (decided now)

Each signal has one **primary horizon** (below). The verdict uses the **test period**,
excess vs SPY, at the primary horizon, all signals with prices:

- **Long hypotheses** (signal should beat the index):
  - **use**: mean > 0, median > 0 and monthly-cohort t ≥ 2.0, and the train-period mean
    has the same sign.
  - **maybe**: mean > 0 and median > 0 but t < 2.0 (or train sign disagrees).
  - **discard**: otherwise.
- **Short/avoid hypotheses** (signal should lag the index):
  - **avoid**: mean < 0, median < 0 and t ≤ −2.0, and the train-period mean has the same
    sign. Meaning: do not hold / do not buy names with this flag (it is a filter, not a
    short-selling recommendation).
  - **maybe (avoid)**: mean < 0 and median < 0 but |t| < 2.0 (or train sign disagrees).
  - **discard**: otherwise.
- If the test period has fewer than **12 distinct months** with signals or fewer than
  **50 measured signals**, the verdict is **insufficient data** regardless of the numbers.

About a dozen primary tests are run; at 5% significance roughly one false "use/avoid"
is expected by chance. That is why a verdict also needs the train sign to agree.

## 3. Signals per source

Notation: "primary" = horizon used by the verdict. Thresholds are fixed.

### 3.1 Form 144 (`form144`)

What it is: a notice that an affiliate (officer, director, 10% holder) intends to sell
restricted or control shares under Rule 144, filed no later than the sale itself.

| Signal | Rule | Hypothesis | Primary |
|---|---|---|---|
| `form144_cluster` | At least **3 distinct sellers** (reporting-person CIK) file an original Form 144 for the **same issuer** within **10 calendar days**. Fires on the filing date of the third. Cooldown 30 days. | Coordinated affiliate selling precedes **underperformance** → *avoid*. | 3 months |
| `form144_large` (live only) | A single Form 144 with aggregate market value ≥ **US$ 10 mi** or ≥ **1%** of units outstanding. | Large planned sale → context for the cards. | not tested |

- History: EDGAR full-text search, one query per day (`forms=144`), paging 100 hits; each
  hit lists the issuer and the seller. Period **2023-05-01 to 2025-12-31** (electronic
  filing mandatory from 2023-04-13; April is left out as a ramp-up month).
- There is no pre-2023 train period. Since nothing is tuned, the whole period is treated
  as out-of-sample; the report also shows 2023-05–2024-06 vs 2024-07–2025-12 as a
  stability check, and the verdict uses the whole period.
- `form144_large` needs the XML of every filing (~190k documents since 2023-04, about
  7 hours at the SEC limit and more when sharing the limit with other processes), so it
  is **not backtested**. It is shown in the panel as context and labeled "not tested".
- Look-ahead: none; the filing date is when the notice became public.

### 3.2 13F holdings (`thirteenf`)

What it is: quarterly long positions of institutional managers with > US$ 100 mi, filed
up to 45 days after quarter end.

Common: only `13F-HR` originals (no amendments), only rows with `SSHPRNAMTTYPE = SH` and
no put/call. Positions are compared **in shares** (the `VALUE` column changed from
thousands to dollars in January 2023). CUSIP → ticker via SEC FTD files.

| Signal | Rule | Hypothesis | Primary |
|---|---|---|---|
| `fund_consensus_13f` | For report quarter Q, take **active filers**: 13F-HR originals filed **by the deadline** (45 days after quarter end, rolled to the next business day), with **20 to 500** share positions, that also filed for Q−1. Per CUSIP, **ΔBreadth** = (active filers holding in Q − active filers holding in Q−1) ÷ number of active filers (Chen, Hong & Stein 2002). Universe: CUSIPs held by ≥ **20** active filers in Q−1 (excludes IPOs/spin-offs, where every holder is "new"). Signal: the **top 30** CUSIPs by ΔBreadth. Signal date = deadline. | Rising breadth of ownership predicts **outperformance** → *long*. | 3 months |
| `notable_fund_new_13f` | A manager from the fixed list below files a 13F-HR with a CUSIP **absent from its previous 13F-HR** and weight ≥ **1%** of that filing's reported value. Signal date = that filing's filing date. | Concentrated, research-driven managers' new positions **outperform** → *long*. | 3 months |

Fixed manager list (CIKs resolved from 13F cover pages by name, chosen for being known
fundamental, concentrated managers as of 2019, **not** by any 2020–2025 result):
Berkshire Hathaway 1067983, Pershing Square 1336528, Baupost 1061768, Appaloosa 1656456,
Greenlight 1079114, Third Point 1040273, Lone Pine 1061165, Viking Global 1103804,
Tiger Global 1167483, Coatue 1135730, Duquesne Family Office 1536411, Scion 1649339,
Himalaya 1709323, Akre 1112520, ValueAct 1418814, Trian 1345471, Starboard Value 1517137,
Icahn 921669, Elliott 1791786 and 1048445, Soros Fund Management 1029160, Dalal Street
(Pabrai) 1549575, Markel 1096343, JANA Partners 1159159, Glenview 1138995,
D1 Capital 1747057, Ruane Cunniff 1720792.

- Look-ahead: the consensus uses only filings filed by the deadline and is dated at the
  deadline; late filers are ignored. The notable-fund signal is dated by each filing.
- Known bias: the manager list is "famous today" and fame partly comes from pre-2020
  performance; that is selection on the past, not on the test period.

### 3.3 8-K items and late-filing notices (`eightk`)

Items come from EDGAR metadata (feed summary live; `items` field of full-text search in
history). Text rules use the **same fixed phrase list** live (regex on the downloaded
text, case-insensitive, whitespace-normalized) and in history (exact-phrase full-text
search, then confirmed by form/items).

| Signal | Rule | Hypothesis | Primary |
|---|---|---|---|
| `buyback_8k` | 8-K (any document of the filing) contains one of: "authorized a share repurchase program", "approved a share repurchase program", "authorized a new share repurchase program", "approved a new share repurchase program", "authorized a stock repurchase program", "approved a stock repurchase program", "authorized a new stock repurchase program", "approved a new stock repurchase program", "new share repurchase program", "new stock repurchase program". Cooldown 90 days. | New buyback authorizations are followed by **outperformance** (Ikenberry, Lakonishok & Vermaelen 1995) → *long*. | 6 months |
| `ceo_cfo_exit_8k` | 8-K with **Item 5.02** whose text contains one of: "resigned as chief executive officer", "resign as chief executive officer", "resignation as chief executive officer", "step down as chief executive officer", "stepping down as chief executive officer", "terminated as chief executive officer", and the same six with "chief financial officer". | Unplanned top-executive departures precede **underperformance** → *avoid*. | 3 months |
| `bankruptcy_8k` | 8-K with **Item 1.03** (bankruptcy or receivership). | **Underperformance** → *avoid*. | 1 month |
| `auditor_change_8k` | 8-K with **Item 4.01** (change in certifying accountant). | **Underperformance** → *avoid*. | 3 months |
| `late_filing_nt` | Original **NT 10-K** or **NT 10-Q**. | Late filing precedes **underperformance** → *avoid*. | 3 months |

Context only (shown in the panel, not signals, not tested): **Item 1.01** containing
"Agreement and Plan of Merger" (direction depends on target vs acquirer), **Item 2.01**
(completion of acquisition/disposition), **Item 2.02** (earnings release date).

- History: items-based signals use exact-phrase searches for the item heading text
  ("Item 1.03", "Item 4.01", "Item 5.02") restricted to 8-K, then keep only filings
  whose `items` metadata contains the item; NT forms use `forms=NT 10-K,NT 10-Q`.
  Queries are split by month so no query exceeds the 10,000-hit cap.
- Amendments (8-K/A, NT 10-K/A) are ignored.

### 3.4 Short interest, short volume and fails-to-deliver (`short`)

Universe: symbols that map to an SEC registrant (`company_tickers.json`), on an exchange
(FINRA `marketClassCode` not `OTC`), and whose name does not contain ETF, ETN, Fund,
Trust, iShares, ProShares, Direxion, SPDR, Invesco or Leveraged (funds are not companies).

| Signal | Rule | Hypothesis | Primary |
|---|---|---|---|
| `short_crowded` | FINRA settlement date with **days to cover ≥ 7**, short position **≥ 1 mi shares**, position up **≥ 25%** vs the previous settlement date, and average daily volume ≥ **100k shares**. Cooldown 30 days. | Rising, crowded short interest precedes **underperformance** (Asquith, Pathak & Ritter 2005; Boehmer, Jones & Zhang 2008) → *avoid*. | 1 month |
| `squeeze_setup` | Days to cover **≥ 7**, short position **down ≥ 15%** vs the previous settlement date, and adjusted price **up ≥ 20%** over the 10 sessions ending on the signal date. Cooldown 30 days. | Covering under price pressure **continues** short term → *long*. | 1 month |
| `ftd_persistent` | In one SEC half-month fails file, the security has fails **≥ 10,000 shares** and **≥ 0.5% of shares outstanding** on **≥ 5 consecutive settlement dates** (the Reg SHO threshold definition). Shares outstanding from XBRL `dei` frames with a 45-day lag. Cooldown 30 days. | Persistent delivery failures (hard-to-borrow, distressed names) precede **underperformance** → *avoid*. | 1 month |

- Dating, FINRA short interest: settlement date **+ 10 business days** (FINRA publishes
  about 7 business days after settlement; the margin avoids using data before it was out).
- Dating, SEC FTD: the later of the file's HTTP `Last-Modified` date and the rule
  "first half → last day of the month + 3 days; second half → 18th of the next month".
  Both are at or after the real posting date.
- FINRA **daily short volume** (`ShortVolume / TotalVolume`) is shown as context only.
  It includes market-maker hedging and is not short interest; it is not a signal.

## 4. Live monitor and panel (implementation plan)

Each source lives in `src/radar/sources/<source>/` behind one interface:

```
class Source(Protocol):
    name: str                      # "form144", "thirteenf", "eightk", "short"
    interval_s: float              # how often the live loop polls it
    def collect(ctx) -> list[RawItem]          # fetch new raw items (cached, rate-limited)
    def normalize(item) -> list[MarketEvent]   # common event shape stored in SQLite
    def signals(ctx, events) -> list[Signal]   # same rule functions as the backtest
    def history(ctx, start, end) -> Iterable[MarketEvent]  # point-in-time history
```

Polling (all SEC calls share the process-wide 8 req/s limiter; FINRA calls are a few per
day):

| Source | Live input | Frequency |
|---|---|---|
| form144 | `getcurrent` feed `type=144`, then `primary_doc.xml` of new filings | every cycle (60 s) |
| eightk | `getcurrent` feed `type=8-K` (items from the summary); `.txt` only for items 2.02/5.02/7.01/8.01 | every cycle (60 s) |
| eightk (NT) | `getcurrent` feeds `NT 10-K`, `NT 10-Q` (slow, ~15 s) | every 15 min |
| thirteenf | `getcurrent` feed `type=13F-HR`; information table only for listed managers; consensus once per quarter after the deadline | every 15 min |
| short | FINRA short-interest API (new settlement date?), FINRA daily short volume file, SEC FTD page (new zip?) | every 6 h |

Storage: additive tables created by a migration (`market_events`, plus per-source detail
tables). The existing `signals` table receives the new signal types.

WebSocket: a new event type `market_event.new` (source, kind, issuer, fields) for the tape;
new signal types reuse `signal.new`. Snapshot gains `market_events`. REST gains
`GET /api/events` and `GET /api/company/{cik}/context` (insiders + 13F + 8-K + 144 +
short in one payload).

Panel: source filter chips, an icon + text label per event kind (never color alone),
cards with the source-specific fields, new events on the tape, and a company-context
section in the focused-signal panel. Same visual identity as the room.

AI summaries: allowed for signals fired by the new sources, within the existing hourly cap.

## 5. Deliverables

- This plan (committed before any backtest).
- `reports/new-signals-<date>.md`: per-signal tables (train/test, SPY/IWM, horizons,
  liquidity subset, funnel) and the verdict per signal.
- README update, panel screenshots in `docs/screenshots/`.
