# Phase 2 research plan (pre-registration)

Written on 2026-11-18, **before** any 2023–2025 (test) result of the variants below was
computed. Everything in this file is frozen once committed; later changes go in the
"Addenda" section at the end, dated, with the reason, and never after looking at test data.

## Why a phase 2

Phase 1 (`reports/backtest-2026-11-18.md`) found that `cluster_buy` and `big_officer_buy`
did not beat SPY in 2020–2025: the median excess return was negative at every horizon and no
t-stat reached 2. On top of that, 26% of the signals (2,369 of 9,018) were never measured,
mostly because the company left the exchange and Yahoo has no prices for it. Phase 2 asks
two questions, in this order:

1. Does the phase-1 conclusion survive once the delisted companies are put back?
2. Is there a more selective rule, taken from the academic literature, that beats SPY
   **and** IWM out of sample?

If nothing passes, the deliverable is the evidence that nothing passes.

## Ground rules

- **Train / test split.** Rules and the few free parameters are chosen looking only at signals
  filed 2020-01-01 to 2022-12-31 (train). Each variant is then run **once** on signals filed
  2023-01-01 to 2025-12-31 (test). Both are reported; the verdict uses test.
- **Point-in-time.** A signal is dated by the SEC filing date and may only use information
  filed on or before that date. Entry is the close of the first trading session after the
  filing date. No AI anywhere in the backtest.
- **Costs.** 0.2% round trip; 1.0% round trip when the entry price is below US$ 5.
- **Horizons.** Primary holding period: **3 months**. 1 and 6 months are reported as
  secondary. The pass/fail decision uses 3 months only. (Chosen from the literature: insider
  purchase drift is documented over 1–12 months; 3 months is the middle and keeps enough
  independent months in a 3-year test window.)
- **Benchmarks.** SPY and IWM (Yahoo adjusted closes). Risk-free rate for alphas: 13-week
  T-bill (`^IRX` on Yahoo), converted to a monthly rate; if unavailable, zero, stated in the
  report.
- **Data.** SEC Insider Transactions Data Sets 2016Q4–2025Q4 (the extra 2016Q4–2019Q4
  quarters exist only to build the 24- and 36-month look-back histories), SEC submissions
  API, EDGAR filings, XBRL frames, Yahoo Finance prices. No paid data.

## Statistics reported for every variant, train and test

Per signal (event study):
- N generated, N measured, N measured only thanks to the survivorship correction.
- Mean, median and winsorized (1/99) mean of net return and of excess vs SPY and vs IWM, at 1,
  3 and 6 months; share of signals beating each benchmark.

Calendar-time portfolio (the main test):
- Every signal is held from entry for the holding period. Each trading day the portfolio is
  the equal-weighted average of the daily returns of all positions open that day; the round
  trip cost is charged on the entry day. Positions that delist early leave the portfolio on
  the delisting date (proceeds in cash, outside the portfolio).
- Signals measured only through the survivorship correction have no daily path (only a start
  and an end value); their return is spread evenly in log terms over the trading days held.
- Daily returns are compounded into calendar months. Months with fewer than 5 open positions
  are dropped and counted in the report.
- Reported: mean monthly return, mean monthly excess vs SPY and vs IWM, **Newey-West t**
  (lag 3) of the monthly excess, CAPM-style alpha (OLS of portfolio minus risk-free on
  benchmark minus risk-free, Newey-West lag 3) against SPY and against IWM, number of months,
  average positions per month, and the yearly breakdown.

## Pass criterion (decided now, applied to test only)

At the 3-month primary horizon, in 2023–2025:

1. median per-signal excess return > 0 against SPY **and** against IWM, and
2. mean monthly excess of the calendar portfolio with Newey-West t ≥ 2 against SPY **and**
   against IWM.

Verdicts:
- **use**: passes both conditions in test.
- **maybe**: positive mean monthly excess vs both benchmarks in test **and** in train, with
  test t between 1 and 2, or passes on one benchmark only. Not traded; watched.
- **discard**: anything else.

Only "use" variants become live signal types in the monitor. If none passes, the monitor gets
only the survivorship-corrected backtest numbers and the panel shows the honest verdict.

## Front 1 — survivorship correction (applies to every insider variant)

For each signal without a full Yahoo price path, find out from the SEC itself what happened
to the company, using the submissions API (`data.sec.gov/submissions/CIK##########.json`,
including its paginated history files):

| Outcome | Evidence (filed by the issuer, or Form 25 by the exchange) |
|---|---|
| acquisition | DEFM14A, DEFM14C, PREM14A, SC 14D9, SC TO-T, or an 8-K with item 2.01, 3.01 or 5.01, within 18 months before the delisting / last filing |
| bankruptcy | 8-K item 1.03 (bankruptcy or receivership), or a Form 15 / Form 25 following an 8-K 1.03 |
| voluntary delisting / deregistration | Form 25 or Form 15 (15-12B, 15-12G, 15-15D) with none of the above |
| unknown | none of the above (still filing, or no evidence) |

The terminal date is the first Form 25 / Form 15 date, or else the last filing date.

Value used at the terminal date, in this order:
1. Yahoo partial history, if the ticker has any prices up to the terminal date.
2. Acquisition: cash price per share in the merger agreement, extracted with a regular
   expression from the DEFM14A / SC 14D9 / 8-K text ("US$ X.XX per share in cash"). Stock or
   mixed deals without an extractable cash price fall through to 3.
3. **SEC price tape**: the median price of open-market and tax-withholding transactions
   (Form 4 codes P, S, F) by any insider of the same issuer, on the nearest date within 10
   calendar days. This is a free, point-in-time price source that exists for every company
   with active insiders. Its accuracy is validated against Yahoo on the signals that do have
   Yahoo prices, and the error is reported.
4. Bankruptcy: −100% (conservative; equity holders usually get nothing, sometimes something).
5. Otherwise the signal stays unmeasured, counted in the funnel.

Entry price when Yahoo has nothing: the SEC price tape on the first date after the filing
date (within 5 calendar days); otherwise the insider's own reported purchase price. The bias of
the latter (price move between the insider's trade and the day after filing) is measured on
the Yahoo-covered signals and reported.

When the terminal date falls before the end of the holding period, the position ends at the
terminal date and the benchmarks are measured over the same shorter window. When it falls
after, the exit value at the horizon comes from the price tape (step 3) if available.

Results are reported with and without the correction. The price source sits behind a
`PriceSource`-style interface so that Tiingo or Polygon can be plugged in later without a key
being required now.

## Front 2 — insider variants

### Building blocks

- **Base event `insider_buy` (B)**: one original Form 4 (no amendments) with open-market
  purchases (code P, common stock) by a reporting owner who is an officer or a director
  (filings where every owner is only a 10% owner or "other" are excluded), aggregate value
  ≥ US$ 50,000. One signal per issuer per 30 days (cooldown, per variant). B itself is
  reported as the reference for the filters.
- **Routine insider** (Cohen, Malloy & Pomorski 2012): an owner whose trade is in a calendar
  month in which they also traded (P or S, same issuer) in each of the three previous calendar
  years. **Opportunistic** = not routine. Histories use only trades filed before the signal.
- **First buy**: no code-P purchase by the same owner in the same issuer in the 24 months
  before the transaction date.
- **Stake increase**: shares bought ÷ shares owned before the purchase (from "shares owned
  following transaction" on the Form 4).
- **Drawdown**: issuer's adjusted-close return over the 63 trading days ending on the filing
  date (needs Yahoo history; issuers without it cannot qualify — this exclusion is reported).
- **Entity filter** for clusters: owners whose name looks like a fund or company (LP, LLC,
  L.P., FUND, CAPITAL, PARTNERS, HOLDINGS, MANAGEMENT, TRUST, INC, CORP, LTD, ADVISORS,
  INVESTMENTS) and pure 10% owners are not counted.

### Variants (frozen list)

| # | Name | Rule | Why (literature / phase 1) |
|---|---|---|---|
| R1 | `cluster_buy` (phase 1) | unchanged | reference, re-measured with the survivorship correction |
| R2 | `big_officer_buy` (phase 1) | unchanged | reference, re-measured with the survivorship correction |
| V0 | `insider_buy` | base B | the population the filters below act on |
| V1 | `opportunistic_buy` | B, and no purchasing owner of the filing is routine | Cohen, Malloy & Pomorski (2012): opportunistic trades predict returns, routine ones do not |
| V2 | `first_buy` | B, and no purchasing owner bought (P) the issuer in the prior 24 months | a first purchase after a long silence is a deliberate decision, not a habit |
| V3 | `stake_jump` | B, and stake increase ≥ X, X ∈ {10%, 20%} chosen on train | conviction: size relative to own wealth in the stock (Seyhun 1998; Lakonishok & Lee 2001 on trade intensity) |
| V4 | `dip_buy` | B, and drawdown ≤ −Y, Y ∈ {20%, 30%} chosen on train | contrarian insiders buying after large falls (Seyhun; Jenter 2005) |
| V5 | `csuite_cluster` | within 14 days, ≥ 2 distinct non-entity officer/director buyers including **both CEO and CFO**, or ≥ 3 distinct officers; ≥ US$ 100k total; 30-day cooldown | top executives have the most information; excludes funds and 10% owners that drove part of phase-1 clusters |
| V6 | `opportunistic_dip` | V1 and V4 | information-driven trade at a moment the market is pessimistic |
| V7 | `first_big_stake` | V2 and V3 | rare and large: strongest revealed conviction |
| V8 | `lazy_nonchangers` | see front 3 (a) | Cohen, Malloy & Nguyen (2020) |
| V9 | `insider_buy_text_ok` | V0 restricted to issuers in the text universe, excluding those whose latest 10-K is in the bottom similarity quintile (largest change) | front 3 (b): avoid buying into firms whose disclosures just changed a lot |

Free parameters: only X (V3, V7) and Y (V4, V6). Each is chosen on train by the higher
mean monthly excess vs IWM of the 3-month calendar portfolio; ties or differences under 0.1
percentage point go to the stricter value (20% / 30%). Everything else is fixed above.

## Front 3 — "Lazy Prices" text signal

- **Universe**: companies with a ticker in the SEC company ticker file, Yahoo prices, and a
  market value ≥ US$ 300 million at the filing date (XBRL frames shares outstanding × Yahoo
  close). The universe size per year is reported. Because the ticker file and Yahoo only know
  current tickers, this universe is survivorship-biased; stated in the report.
- **Documents**: annual reports (10-K) filed 2019–2025, primary document only, compared with
  the same company's previous 10-K (filed 300–450 days earlier). 10-Q comparisons are left
  out to keep the download volume viable (≈ 3 requests per company-year instead of 6);
  stated as a limitation.
- **Measure (primary)**: cosine similarity of term-frequency vectors of the full document text
  (HTML stripped, numbers and one-letter tokens removed, lowercase). **Secondary**: the same
  on Item 1A (Risk Factors) only, when it can be located. Jaccard similarity of the word sets
  is reported as a robustness check.
- **Quintiles**: each filing is ranked against the similarity of all universe filings of the
  previous 12 months (rolling, point-in-time breakpoints; the first year uses 2019 filings
  only for breakpoints).
- **(a) V8 `lazy_nonchangers`**: long the top quintile (least change), entered after the
  10-K filing and held 3 months, as a calendar portfolio vs SPY and IWM. The bottom quintile
  and the top-minus-bottom spread are reported for information only (not a candidate:
  shorting is out of scope).
- **(b) V9**: the filter described in the variants table.
- **SEC fair access**: at most 5 requests per second for this job, everything cached; only the
  extracted text is kept on disk (gzip), never the full HTML.

## Front 4 — B3 / CVM

Feasibility study only, in `research/b3-feasibility.md`.

## Integration

- Variants with verdict "use" become new signal types in `radar` (live monitor) with score and
  explanation, and appear in the War Room panel (filter chips, colors, and the "what the
  backtest says" panel with the phase-2 numbers, failed variants included).
- If none passes: integrate only the survivorship-corrected numbers and update the panel with
  the honest verdict. No new live signal types.

## Deliverables

- this plan, committed before the test run;
- `reports/phase2-<date>.md`: funnel, survivorship correction, train vs test per variant,
  calendar portfolios, alphas vs SPY and IWM, yearly breakdown, verdict per variant;
- `research/b3-feasibility.md`;
- README update.

## Addenda

### 2026-11-18 (a) — survivorship evidence, before any return was measured

Written after reading the SEC form/item definitions and before measuring any return, train or
test:

- **8-K item 3.01 is dropped as acquisition evidence.** It is "notice of delisting or failure to
  satisfy a continued listing rule", which distressed companies file routinely. Acquisition
  evidence is now: DEFM14A, DEFM14C, PREM14A, PREM14C, SC 14D9, SC TO-T or SC 13E3 within 18
  months before the terminal date, or an 8-K with item 5.01 (change in control), or with items
  2.01 and 3.01 together, within 60 days before the terminal date.
- **Merger consideration from Form 4 code D.** When a merger closes, insiders file Form 4s
  disposing of their shares to the issuer (code D) at the per-share consideration. The median
  code-D price within 15 days before the terminal date is used as the acquisition value first;
  the cash price regex on the DEFM14A / SC 14D9 / SC TO-T text is the fallback. Both are
  public, point-in-time SEC data.
- Bankruptcy evidence (8-K item 1.03) takes precedence over acquisition evidence (asset sales
  inside a bankruptcy are not a premium for shareholders).
- A company that simply stopped filing (no Form 25 / 15) without Yahoo prices is "unknown".

### 2026-11-18 (b) — SEC price tape calibration, on Yahoo-covered signals, before any variant return

Validated on the phase-1 signals that Yahoo does measure (all years; this is a data-quality
check of a price source, not a strategy result):

- A tape entry price (any P/S/F trade within 5 days after the filing) exists for 36% of
  signals; its median absolute error against the Yahoo close is 1.7%.
- Tape exit prices exist for 30–39% of signals per horizon. The tape value is the **median of
  every P/S/F price within ±10 days** of the target date (not a single day), and tape returns
  outside 1/50x–20x are rejected as unit errors. With that, the median error against Yahoo raw
  returns is +0.9% to +1.1% and the 90th percentile absolute error is 19–22%.
- When no tape entry exists, the insider's own price is used. On **train** signals (2020–2022)
  the Yahoo entry close is a median 2.1% above the insider's price (the stock moves between the
  trade and the day after filing), so that entry is scaled up by 2.1% to remove the bias.

### 2026-11-18 (c) — opportunistic definition, before any variant return

With the plan's wording ("opportunistic = not routine"), only 1.4% of base filings are routine,
so V1 would be almost identical to V0 and would not test the idea. Cohen, Malloy & Pomorski
(2012) only classify insiders who traded in **each of the three previous calendar years**;
the rest are unclassified. V1 and V6 now follow the paper exactly: every purchasing owner of
the filing must have traded (P or S) the issuer in each of the three prior calendar years, and
none may be routine (same calendar month in each of those years). That leaves 13% of base
filings classified and 12% opportunistic (550–730 a year). Decided from counts only; no
return of any variant had been computed.

### 2026-11-18 (d) — parameters frozen on train, before the test run

Rule: higher mean monthly excess vs IWM of the 3-month calendar portfolio in 2020–2022; a
difference under 0.1 percentage point goes to the stricter value.

| Parameter | Candidates (train excess vs IWM per month) | Frozen |
|---|---|---|
| X, stake increase (V3) | 10%: +0.48% · 20%: +0.52% | **20%** (difference < 0.1 pp → stricter) |
| Y, drawdown (V4) | 20%: +0.34% · 30%: +1.46% | **30%** |

V6 and V7 inherit Y = 30% and X = 20%. No other rule changes. For the record, nothing looked
strong in train: every variant had a negative median excess return vs SPY and vs IWM, and no
calendar-portfolio t reached 1.5. The test run below is executed once.

### 2026-11-18 (e) — data cleaning found on train, before the test run

- **Daily path glitches.** In the train run, one Yahoo series (ATXG, August 2022) jumps +8,650%
  in a day and falls 95% the next. With an equal-weighted portfolio rebalanced daily, that
  spike adds a gain nobody could have earned (+398% in one month for the 10-K Q1 portfolio). A
  position whose daily path has a move above +200% or below −75% now keeps only its total
  return, spread evenly over the holding days, like the SEC-valued positions. Per-signal
  returns are unchanged.
- **V9 ordering.** The 10-K similarities are now computed before the variants are built, so
  V9 and its comparison set (V0 restricted to the text universe) exist in both splits.
- The SEC 10-K download kept the hidden inline-XBRL header in the text (the HTML parser does
  not see its namespace); its content is mostly numbers, which the tokenizer drops. Stated as a
  limitation, not changed, so the stored word counts stay what they were.

Train numbers in the report are from the run after these fixes. The fix moved some train
portfolio numbers, so the rule of addendum (d) was applied again; it picks the same values:

| Parameter | Train excess vs IWM per month after the fix | Frozen |
|---|---|---|
| X, stake increase | 10%: +0.37% · 20%: +0.40% | **20%** (difference < 0.1 pp → stricter) |
| Y, drawdown | 20%: −0.79% · 30%: −0.59% | **30%** |

For the record, with the fix V9 (insider buys in the text universe, excluding the bottom
similarity quintile) has a train t of 2.8 against IWM but 0.6 against SPY; V0 restricted to
the same universe has 1.9 against IWM. Nothing else changes before the single test run.
