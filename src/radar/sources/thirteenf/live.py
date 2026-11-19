"""13F in live mode.

- Notable managers: the `getcurrent` 13F-HR feed is read every 15 minutes; a filing
  by a listed manager is downloaded, compared with its previous 13F and turned into
  `notable_fund_new_13f` signals.
- Fund consensus: after each quarter's 45-day deadline, a background job lists the
  13F-HR originals filed by the deadline (EDGAR full-text search), takes the previous
  quarter from the SEC data set, downloads the new reports a batch at a time and then
  applies the same `fund_consensus` rule as the backtest, dated at the deadline.
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta

from radar.edgar import normalize_cik, submission_txt_url
from radar.http import SecHttpError, decode

from ..base import THIRTEENF, MarketEvent, PollResult
from ..efts import search
from ..feeds import fetch_items
from .history import DATASET_PAGE_URL, dataset_links, zip_window
from .holdings import Holding, Report, parse_submission, read_dataset
from .managers import NOTABLE_MANAGERS
from .rules import (
    FUND_CONSENSUS_13F,
    filing_deadline,
    fund_consensus,
    notable_new_positions,
    previous_quarter_end,
    quarter_end,
)

log = logging.getLogger(__name__)

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
JOB_BATCH = 300


def report_from_rows(store, row) -> Report:
    report = Report(
        accession=row["accession"],
        cik=row["cik"],
        manager=row["manager"] or "",
        period=date.fromisoformat(row["period"]),
        filing_date=date.fromisoformat(row["filing_date"]),
        total_value=row["total_value"],
    )
    for p in store.positions(row["accession"]):
        report.shares[p["cusip"]] = p["shares"]
        report.values[p["cusip"]] = p["value"]
        report.names[p["cusip"]] = p["name"] or ""
    return report


def filing_event(report: Report, manager: str, new_positions: int) -> MarketEvent:
    return MarketEvent(
        source=THIRTEENF,
        kind="13f_filing",
        key=report.accession,
        event_date=report.filing_date,
        issuer_cik=report.cik,
        issuer_name=manager,
        title=(
            f"{manager} filed its 13F for {report.period.isoformat()}: "
            f"{report.positions} positions, {new_positions} new"
        ),
        data={
            "manager": manager,
            "period": report.period.isoformat(),
            "positions": report.positions,
            "new_positions": new_positions,
        },
    )


class ThirteenFSource:
    name = THIRTEENF
    interval_s = 900.0

    def poll(self, ctx) -> PollResult:
        result = PollResult()
        try:
            result = self._notable(ctx)
        except SecHttpError as exc:
            log.warning("13F feed unavailable: %s", exc)
        try:
            job = self._consensus_step(ctx)
            result.events += job.events
            result.signals += job.signals
        except SecHttpError as exc:
            log.warning("13F consensus job paused: %s", exc)
        return result

    # ------------------------------------------------------- notable managers

    def _previous(self, ctx, cik: str, period: date) -> Report | None:
        row = ctx.store.previous_report(cik, period)
        if row is not None:
            return report_from_rows(ctx.store, row)
        try:
            recent = json.loads(
                ctx.client.get_bytes(SUBMISSIONS_URL.format(cik=int(cik)), max_age=3600)
            )["filings"]["recent"]
        except (SecHttpError, ValueError, KeyError):
            return None
        for accession, form, report_date in zip(
            recent["accessionNumber"], recent["form"], recent["reportDate"], strict=False
        ):
            if form != "13F-HR" or not report_date or date.fromisoformat(report_date) >= period:
                continue
            raw = ctx.client.get_bytes(submission_txt_url(cik, accession))
            report = parse_submission(decode(raw), accession=accession, cik=cik)
            ctx.store.save_report(report)
            return report
        return None

    def _notable(self, ctx) -> PollResult:
        result = PollResult()
        items = fetch_items(
            ctx.client, "13F-HR", is_known=ctx.store.has_report, count=100, max_pages=2
        )
        for item in items:
            ref = item.ref
            cik = normalize_cik(ref.cik)
            if ref.form != "13F-HR" or cik not in NOTABLE_MANAGERS:
                continue
            if ctx.store.has_report(ref.accession):
                continue
            report = parse_submission(
                decode(ctx.client.get_bytes(ref.txt_url)),
                accession=ref.accession,
                filing_date=ref.filed_date,
                cik=cik,
            )
            previous = self._previous(ctx, cik, report.period)
            ctx.store.save_report(report)
            signals = []
            if previous is not None:
                pair = {(cik, previous.period): previous, (cik, report.period): report}
                signals = notable_new_positions(pair, ctx.resolve_cusip)
            result.signals += signals
            result.events.append(filing_event(report, NOTABLE_MANAGERS[cik], len(signals)))
        return result

    # ------------------------------------------------------- consensus job

    def _consensus_step(self, ctx) -> PollResult:
        result = PollResult()
        period = quarter_end(ctx.today - timedelta(days=91))
        deadline = filing_deadline(period)
        if ctx.today <= deadline:
            period = previous_quarter_end(period)
            deadline = filing_deadline(period)
        state_key = f"13f_consensus:{period.isoformat()}"
        state = ctx.store.get_state(state_key, {})
        if state.get("done"):
            return result

        if "pending" not in state:
            prior_period = previous_quarter_end(period)
            prior = self._prior_from_dataset(
                ctx, prior_period, filing_deadline(prior_period), deadline
            )
            if prior is None:
                return result  # the data set for the previous quarter is not out yet
            listed: dict[str, str] = {}
            for hit in search(
                ctx.client, forms="13F-HR", start=period + timedelta(days=1), end=deadline
            ):
                if hit.form == "13F-HR" and hit.ciks:
                    listed.setdefault(normalize_cik(hit.ciks[0]), hit.accession)
            pending = {cik: acc for cik, acc in listed.items() if cik in prior}
            state = {"pending": pending, "prior_period": prior_period.isoformat()}
            ctx.store.set_state(state_key, state)

        pending: dict[str, str] = state["pending"]
        batch = list(pending.items())[:JOB_BATCH]
        urls = {cik: submission_txt_url(cik, acc) for cik, acc in batch}
        payloads = ctx.client.fetch_many(urls.values())
        for cik, accession in batch:
            payload = payloads.get(urls[cik])
            if isinstance(payload, SecHttpError) and (payload.status_code or 500) >= 500:
                continue  # try again next round
            pending.pop(cik, None)
            if payload is None or isinstance(payload, SecHttpError):
                continue
            try:
                report = parse_submission(decode(payload), accession=accession, cik=cik)
            except ValueError:
                continue
            ctx.store.save_report(report)
        if pending:
            state["pending"] = pending
            ctx.store.set_state(state_key, state)
            result.note = f"13F consensus {period}: {len(pending)} filings to go"
            return result

        prior_period = date.fromisoformat(state["prior_period"])
        reports: dict[tuple[str, date], Holding] = {}
        for p in (prior_period, period):
            for row in ctx.store.reports_for(None, p):
                cusips = tuple(r["cusip"] for r in ctx.store.positions(row["accession"]))
                reports[(row["cik"], p)] = Holding(
                    row["accession"], row["cik"], p, date.fromisoformat(row["filing_date"]), cusips
                )
        signals, stats = fund_consensus(reports, period, ctx.resolve_cusip)
        result.signals += signals
        result.events.append(
            MarketEvent(
                source=THIRTEENF,
                kind="13f_consensus",
                key=f"consensus:{period.isoformat()}",
                event_date=ctx.today,
                title=(
                    f"13F consensus for {period.isoformat()}: "
                    f"{stats.active_filers} active funds, top "
                    f"{len(signals)} breadth gains"
                ),
                data={
                    "period": period.isoformat(),
                    "active_filers": stats.active_filers,
                    "tickers": [s.ticker for s in signals if s.ticker],
                },
            )
        )
        ctx.store.set_state(state_key, {"done": True, "signals": len(signals)})
        return result

    def _prior_from_dataset(
        self, ctx, prior_period: date, prior_deadline: date, deadline: date
    ) -> set[str] | None:
        """Load the previous quarter's reports from the SEC data set into the store."""
        page = ctx.client.get_text(DATASET_PAGE_URL, max_age=86_400)
        links = [
            link
            for link in dataset_links(page)
            if (w := zip_window(link)) and w[0] <= prior_deadline <= w[1]
        ]
        if not links:
            return None
        path = ctx.client.download("https://www.sec.gov" + links[0])
        ciks: set[str] = set()
        for report in read_dataset(path):
            if report.period != prior_period or report.filing_date > deadline:
                continue
            if report.positions > 3000:
                continue
            if not ctx.store.has_report(report.accession):
                ctx.store.save_report(report)
            ciks.add(report.cik)
        return ciks


__all__ = ["ThirteenFSource", "FUND_CONSENSUS_13F"]
