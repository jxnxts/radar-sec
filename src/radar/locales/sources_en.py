"""English messages of the extra signal sources (Form 144, 13F, 8-K, short data)."""

from __future__ import annotations

MESSAGES: dict[str, str] = {
    # -------------------------------------------------------------- sources
    "source.insiders": "Insiders",
    "source.form144": "Form 144",
    "source.thirteenf": "13F",
    "source.eightk": "8-K",
    "source.short": "Short",
    # -------------------------------------------------------------- signals
    "signal.form144_cluster": "Form 144 cluster",
    "signal.form144_large": "Large planned sale (144)",
    "signal.fund_consensus_13f": "Fund consensus (13F)",
    "signal.notable_fund_new_13f": "Notable fund, new position",
    "signal.buyback_8k": "Buyback authorized (8-K)",
    "signal.ceo_cfo_exit_8k": "CEO/CFO exit (8-K)",
    "signal.bankruptcy_8k": "Bankruptcy (8-K)",
    "signal.auditor_change_8k": "Auditor change (8-K)",
    "signal.late_filing_nt": "Late filing (NT)",
    "signal.short_crowded": "Crowded short",
    "signal.squeeze_setup": "Squeeze setup",
    "signal.ftd_persistent": "Persistent fails-to-deliver",
    # ---------------------------------------------------------- explanations
    "explain.form144_cluster": (
        "{n} insiders filed Form 144 (notice of a planned sale) for {company} within "
        "{window} days{total}. Sellers: {who}."
    ),
    "explain.form144_cluster.total": ", about {value} in total",
    "explain.form144_large": (
        "{seller} ({role}) plans to sell {value}{pct} of {company} (Form 144). "
        "Context only: this rule was not backtested."
    ),
    "explain.form144_large.pct": " ({pct} of the shares outstanding)",
    "explain.fund_consensus_13f": (
        "{delta} active funds now hold {company} ({before} → {now} of {total}) in the 13Fs "
        "for the quarter ended {period}: #{rank} breadth gain of the quarter."
    ),
    "explain.notable_fund_new_13f": (
        "{manager} opened a new position in {company} worth {weight} of its 13F for the "
        "quarter ended {period}."
    ),
    "explain.buyback_8k": "{company} announced a new share repurchase authorization (8-K).",
    "explain.ceo_cfo_exit_8k": "{company}: the {who} is leaving (8-K Item 5.02).",
    "explain.bankruptcy_8k": "{company} reported a bankruptcy or receivership (8-K Item 1.03).",
    "explain.auditor_change_8k": "{company} changed its auditor (8-K Item 4.01).",
    "explain.late_filing_nt": "{company} told the SEC its {report} will be late ({form}).",
    "explain.late_filing_nt.annual": "annual report (10-K)",
    "explain.late_filing_nt.quarterly": "quarterly report (10-Q)",
    "explain.short_crowded": (
        "Short interest in {ticker} rose {change} to {shares} shares ({dtc} days to cover) "
        "as of {settled}."
    ),
    "explain.squeeze_setup": (
        "Shorts in {ticker} are covering ({change}, {dtc} days to cover) while the price "
        "rose {move} in 10 sessions."
    ),
    "explain.ftd_persistent": (
        "{ticker} had fails-to-deliver above 0.5% of its shares on {days} consecutive "
        "settlement days (peak {peak} shares, {fraction} of the shares outstanding)."
    ),
    "explain.untested": " Not backtested.",
    # ---------------------------------------------------------------- events
    "event.form144": "{seller} ({role}) plans to sell {value}",
    "event.8k": "8-K · {items}",
    "event.8k.none": "8-K · no items listed",
    "event.nt_filing": "{form}: late {report}",
    "event.nt_filing.annual": "annual report",
    "event.nt_filing.quarterly": "quarterly report",
    "event.13f_filing": "{manager} filed its 13F for {period}: {positions} positions, {new} new",
    "event.13f_consensus": "13F consensus for {period}: {filers} active funds",
    "event.short_interest_release": (
        "FINRA short interest as of {settled}: {symbols} symbols, {flagged} flagged"
    ),
    "event.ftd_release": "SEC fails-to-deliver {file}: {rows} rows, {flagged} flagged",
    "event.role.affiliate": "affiliate",
    # ------------------------------------------------------------ 8-K items
    "item.1.01": "Material agreement",
    "item.1.02": "Agreement terminated",
    "item.1.03": "Bankruptcy",
    "item.1.05": "Cybersecurity incident",
    "item.2.01": "Acquisition/disposition completed",
    "item.2.02": "Earnings release",
    "item.2.03": "New debt",
    "item.2.04": "Debt acceleration",
    "item.2.05": "Exit costs",
    "item.2.06": "Impairment",
    "item.3.01": "Delisting notice",
    "item.3.02": "Unregistered equity sale",
    "item.3.03": "Shareholder rights changed",
    "item.4.01": "Auditor change",
    "item.4.02": "Non-reliance on financials",
    "item.5.01": "Change in control",
    "item.5.02": "Officer/director change",
    "item.5.03": "Bylaws/fiscal year",
    "item.5.07": "Shareholder vote",
    "item.7.01": "Reg FD disclosure",
    "item.8.01": "Other events",
    "item.9.01": "Exhibits",
    # ------------------------------------------------------------- rules (report)
    "sources.rule.form144_cluster": (
        "at least 3 distinct sellers file an original Form 144 for the same issuer within "
        "10 calendar days; fires on the filing date of the third; cooldown 30 days"
    ),
    "sources.rule.form144_large": (
        "one Form 144 worth ≥ US$ 10 mi or ≥ 1% of the units outstanding (not tested)"
    ),
    "sources.rule.fund_consensus_13f": (
        "top 30 stocks by breadth change among active 13F filers (20–500 positions, filed by "
        "the 45-day deadline, also filed the previous quarter), universe held by ≥ 20 of them; "
        "dated at the deadline"
    ),
    "sources.rule.notable_fund_new_13f": (
        "a manager from the fixed list opens a position absent from its previous 13F, worth "
        "≥ 1% of the filing; dated at the filing"
    ),
    "sources.rule.buyback_8k": (
        "8-K text contains one of the fixed phrases of a new repurchase authorization; "
        "cooldown 90 days"
    ),
    "sources.rule.ceo_cfo_exit_8k": (
        "8-K with Item 5.02 whose text says the CEO or CFO resigned, stepped down or was terminated"
    ),
    "sources.rule.bankruptcy_8k": "8-K with Item 1.03 (bankruptcy or receivership)",
    "sources.rule.auditor_change_8k": "8-K with Item 4.01 (change in certifying accountant)",
    "sources.rule.late_filing_nt": "original NT 10-K or NT 10-Q",
    "sources.rule.short_crowded": (
        "FINRA days to cover ≥ 7, short ≥ 1 mi shares, up ≥ 25% vs the previous report, "
        "average volume ≥ 100k; dated settlement + 10 business days"
    ),
    "sources.rule.squeeze_setup": (
        "days to cover ≥ 7, short down ≥ 15% and price up ≥ 20% in the 10 sessions up to the "
        "signal date"
    ),
    "sources.rule.ftd_persistent": (
        "fails ≥ 10k shares and ≥ 0.5% of shares outstanding on ≥ 5 consecutive settlement "
        "days in one SEC half-month file; dated when the file was posted"
    ),
    "sources.status.ok": "measured",
    "sources.status.no_ticker": "no ticker",
    "sources.status.no_prices": "no prices on Yahoo (delisted or unknown)",
    "sources.status.no_entry_price": "no price near the entry date",
    "sources.status.price_mismatch": "price mismatch",
    "sources.status.suspect_jump": "suspect jump (unadjusted reverse split)",
    # ------------------------------------------------------------------ report
    "sources.report.title": "New market signals: backtest {start} to {end}",
    "sources.report.generated": (
        "Generated on {when}. Rules, periods and verdict criteria were fixed beforehand in "
        "[`research/new-signals-plan.md`](../research/new-signals-plan.md). Prices: Yahoo "
        "Finance (adjusted), same cache and entry/exit engine as the insider backtest. "
        "No AI is used."
    ),
    "sources.report.no_data": "_No data._",
    "sources.report.h.verdict": "Verdict",
    "sources.report.verdict_intro": (
        "Primary horizon, excess return over SPY, **test period 2023–2025** (Form 144: "
        "2023-05 to 2025-12, the only electronic history). Costs: 0.2% round trip, 1.0% when "
        "the entry price is below US$ 5."
    ),
    "sources.report.long": "long",
    "sources.report.avoid": "avoid",
    "sources.report.months": "{n}m",
    "sources.report.verdict.use": "use",
    "sources.report.verdict.maybe": "maybe",
    "sources.report.verdict.discard": "discard",
    "sources.report.verdict.avoid": "avoid",
    "sources.report.verdict.maybe_avoid": "maybe (avoid)",
    "sources.report.verdict.insufficient": "insufficient data",
    "sources.report.reason.insufficient": (
        "{n} measured signals in {months} months (needs ≥ {min_n} in ≥ {min_months})"
    ),
    "sources.report.reason.use": "test mean and median > 0, t = {t}, the train period agrees",
    "sources.report.reason.maybe_t": "test mean and median > 0 but t = {t}",
    "sources.report.reason.maybe_train": (
        "test mean and median > 0 (t = {t}) but the train period disagrees"
    ),
    "sources.report.reason.discard_long": "test excess not positive in both mean and median",
    "sources.report.reason.avoid": "test mean and median < 0, t = {t}, the train period agrees",
    "sources.report.reason.maybe_avoid_t": "test mean and median < 0 but t = {t}",
    "sources.report.reason.maybe_avoid_train": (
        "test mean and median < 0 (t = {t}) but the train period disagrees"
    ),
    "sources.report.reason.discard_avoid": "test excess not negative in both mean and median",
    "sources.report.reason.untested": "context only",
    "sources.report.col.signal": "Signal",
    "sources.report.col.hypothesis": "Hypothesis",
    "sources.report.col.primary": "Primary",
    "sources.report.col.n_test": "N (test)",
    "sources.report.col.exc_mean": "Excess mean",
    "sources.report.col.exc_median": "Excess median",
    "sources.report.col.beats_spy": "Beats SPY",
    "sources.report.col.t": "t (monthly)",
    "sources.report.col.train_mean": "Train mean",
    "sources.report.col.iwm_mean": "vs IWM mean",
    "sources.report.col.iwm_median": "vs IWM median",
    "sources.report.col.verdict": "Verdict",
    "sources.report.col.period": "Period",
    "sources.report.col.horizon": "Horizon",
    "sources.report.col.n": "N",
    "sources.report.col.hit": "Hit rate",
    "sources.report.col.beats": "Beats {name}",
    "sources.report.col.net_mean": "Net mean",
    "sources.report.col.exc_winsor": "Excess winsor.",
    "sources.report.col.year": "Year",
    "sources.report.col.measured": "Measured",
    "sources.report.col.sub_penny": "Entry < US$ 0.01",
    "sources.report.col.under_dollar": "Entry < US$ 1",
    "sources.report.period.train": "train 2020–2022",
    "sources.report.period.test": "test 2023–2025",
    "sources.report.period.all": "all 2020–2025",
    "sources.report.period.f144_first": "2023-05 → 2024-06",
    "sources.report.period.f144_second": "2024-07 → 2025-12",
    "sources.report.period.f144_all": "all (2023-05 → 2025-12)",
    "sources.report.rule_line": (
        "Rule: {rule}. Hypothesis: {hypothesis}. Primary horizon: {months} month(s)."
    ),
    "sources.report.hyp_long": "beats the index",
    "sources.report.hyp_avoid": "lags the index",
    "sources.report.against": "Against {name}:",
    "sources.report.liquid_line": (
        "Liquid subset (price ≥ US$ 5, market value ≥ US$ 300 mi), test period, vs SPY:"
    ),
    "sources.report.funnel_line": "Funnel ({n} signals): {parts}.",
    "sources.report.by_year": "By year ({months}m vs SPY):",
    "sources.report.h.quality": "Data quality: sub-penny quotes",
    "sources.report.quality_text": (
        "Late filers, auditor changes and bankruptcies are mostly OTC shells. Their Yahoo "
        "series often show quotes of US$ 0.0001–0.001 that jump to cents or dollars (a single "
        "tick or an unadjusted reverse split), which becomes returns of thousands of percent. "
        "The insider backtest's jump filter deliberately ignores bases below US$ 0.01, so these "
        "pass. For these signals the **mean is not meaningful**: read the median, the "
        "winsorized mean and the liquid subset."
    ),
    "sources.report.how_to_read": (
        "How to read: *excess* = net return minus SPY over the same dates. *Beats SPY* = share "
        "of signals with positive excess. *t (monthly)* = t-statistic of the mean excess of "
        "monthly cohorts (one point per month, so clustered signals do not inflate it). "
        "*avoid* = names to stay away from (a filter, not a short-selling recommendation)."
    ),
    "sources.report.survivorship": (
        "Survivorship: Yahoo keeps almost no history for delisted companies. Signals on "
        "companies that later went bankrupt or were acquired are mostly unmeasured, which hits "
        "the *avoid* signals hardest (bankruptcies above all). See the funnel of each signal."
    ),
    "sources.report.h.liquid": "Secondary view: liquid subset",
    "sources.report.liquid_intro": (
        "The plan fixed a liquid subset (entry price ≥ US$ 5 and market value ≥ US$ 300 mi) as "
        "a reported view, not as the basis of the verdict. The same verdict rule applied to "
        "it, for reference:"
    ),
    "sources.report.h.funnel": "Data funnel",
    "sources.report.h.limitations": "Limitations",
    "sources.report.limitation.1": (
        "**Survivorship.** Prices come from Yahoo, which has almost no delisted tickers, and "
        "tickers come from today's SEC list. Bankruptcies, late filers and failing companies "
        "are the most likely to be missing, so the *avoid* signals are measured on the "
        "survivors and probably look less negative than they were."
    ),
    "sources.report.limitation.2": (
        "**Form 144 has 2.7 years of history** (electronic only since 2023-04-13), no train "
        "period, and only the count-based cluster rule is tested; the value-based "
        "`form144_large` is shown live but not tested."
    ),
    "sources.report.limitation.3": (
        "**Full-text search coverage.** The 8-K rules rely on EDGAR full-text search. A filing "
        "that words a buyback or a resignation differently is missed, and the item searches "
        'need the heading text ("Item 1.03") in a document of the filing.'
    ),
    "sources.report.limitation.4": (
        "**13F timing.** The consensus is dated at the 45-day deadline and uses only filings "
        "filed by then; positions are up to 4.5 months old by that date. CUSIPs are mapped to "
        "tickers through the SEC fails-to-deliver files, which only list securities that had "
        "fails at some point."
    ),
    "sources.report.limitation.5": (
        "**Short interest dating.** FINRA data is dated 10 business days after settlement to "
        "be safe; the real publication is usually 2–3 days earlier."
    ),
    "sources.report.limitation.6": (
        "**Fails-to-deliver dating** uses the later of the HTTP Last-Modified date and a "
        "conservative calendar rule; a file re-uploaded later only makes the date later."
    ),
    "sources.report.limitation.7": (
        "**Overlapping horizons and clustered signals.** The monthly-cohort t corrects part of "
        "it, not all. Eleven primary tests are run; about one false positive at 5% is expected "
        "by chance."
    ),
    "sources.report.limitation.8": (
        "**Idealized execution.** Close-to-close, fixed cost, no market impact; no signal here "
        "requires shorting."
    ),
    # --------------------------------------------------------------------- CLI
    "sources.cli.step.eightk": "8-K and NT: EDGAR full-text search, month by month",
    "sources.cli.step.form144": "Form 144: EDGAR full-text search, day by day (since 2023-04-13)",
    "sources.cli.step.ftd": "Fails-to-deliver: SEC half-month files (also the CUSIP → ticker map)",
    "sources.cli.step.thirteenf": "13F: SEC data sets, one zip at a time",
    "sources.cli.step.short": "Short interest: FINRA settlement dates",
    "sources.cli.step.prices": "Prices for {n} tickers (Yahoo, cached)",
    "sources.cli.prices_done": (
        "    {cached} cached, {downloaded} downloaded, {no_data} without data, {failed} failed"
    ),
    "cli.cycle.source_events": "{n} events from the extra sources",
}
