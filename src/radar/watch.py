"""Monitoring pipeline: feed → new filings → parse → signals → summary → alerts."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

from radar.alerts import Alerter, dispatch
from radar.config import Settings
from radar.db import ERROR, PROCESSED, SKIPPED, Database
from radar.edgar import filing_index_url, normalize_cik, parse_submission, submission_txt_url
from radar.feed import feed_url, fetch_current
from radar.funds import NO_SIC, FundClassifier, IssuerProfile, split_funds
from radar.http import SecClient, SecHttpError, decode
from radar.models import FORM4_TYPES, SC13D_TYPES, FilingRef, Signal
from radar.parsers.form4 import Form4ParseError, parse_form4
from radar.parsers.sc13d import Sc13dParseError, parse_13d
from radar.sectors import SectorLookup, sector_for_sic
from radar.signals import (
    BIG_OFFICER_BUY,
    CLUSTER_BUY,
    detect_activist_13d,
    detect_big_officer_buys,
    detect_cluster_buys,
)
from radar.summary import Summarizer
from radar.tickers import TickerMap

if TYPE_CHECKING:
    from radar.forward import ForwardRecorder
    from radar.sources.runner import SourceRunner

log = logging.getLogger(__name__)

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
MAX_CONTEXT_FILINGS = 6


class WatchListener(Protocol):
    """Whoever wants to follow the cycle as it happens (the dashboard, for example)."""

    def stage(self, name: str, pending: int) -> None:
        """Stage change: "feeds", "filings", "signals"; `pending` is the filing queue."""

    def filing(self, ref: FilingRef) -> None:
        """A new filing finished being handled (processed, skipped or failed)."""

    def signal(self, signal: Signal) -> None:
        """A new signal was stored, summarized and alerted."""

    def prepare(self, signals: list[Signal]) -> None:
        """The recent signals about to be published (optional): a chance to batch lookups."""

    def market_event(self, event_id: int, event: object) -> None:
        """A new event of an extra source (Form 144, 8-K, 13F, short data) was stored."""


@dataclass
class WatchResult:
    seen: int = 0
    new_filings: int = 0
    processed: int = 0
    backfilled: int = 0
    errors: int = 0
    signals: list[Signal] = field(default_factory=list)
    stored_only: int = 0  # old signals stored without alerting
    source_events: int = 0  # new events of the extra sources (radar.sources)
    excluded_funds: int = 0  # insider buy signals dropped because the issuer is a fund


class Watcher:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        client: SecClient,
        alerters: list[Alerter],
        summarizer: Summarizer,
        *,
        today: date | None = None,
        listener: WatchListener | None = None,
        sources: SourceRunner | None = None,
        recorder: ForwardRecorder | None = None,
    ):
        self.listener = listener
        self.sources = sources
        # Forward-test log: every stored signal, plus the daily price snapshot.
        self.recorder = recorder
        self.settings = settings
        self.db = db
        self.client = client
        self.alerters = alerters
        self.summarizer = summarizer
        self.tickers = TickerMap(client)
        # SIC and fund filings of each issuer (also the dashboard's sectors).
        self.sectors = SectorLookup(client)
        self.funds = FundClassifier(settings.signals, self.issuer_profile)
        self._today = today

    @property
    def today(self) -> date:
        return self._today or date.today()

    # ------------------------------------------------------------------ cycle

    def run_once(self) -> WatchResult:
        result = WatchResult()
        self._notify("stage", "feeds", 0)
        self._collect(result)

        candidates: list[Signal] = []
        touched_issuers: set[str] = set()
        pending = self.db.pending_filings()
        self._notify("stage", "filings", len(pending))
        # Downloads run in parallel (within the SEC limit); the rest is sequential.
        payloads = self.client.fetch_many(ref.txt_url for ref in pending)
        for ref in pending:
            payload = payloads[ref.txt_url]
            self._process(ref, payload, result, candidates, touched_issuers)
            # A filing that could not be downloaded is not news for the dashboard yet.
            if not isinstance(payload, SecHttpError):
                self._notify("filing", ref)

        self._notify("stage", "signals", 0)
        for issuer in sorted(touched_issuers):
            if self.settings.sec.backfill_issuer:
                self._backfill_issuer(issuer, result)
            candidates += self._form4_signals(issuer, result)

        if self.sources is not None:
            self._notify("stage", "sources", 0)
            tick = self.sources.tick(
                on_event=lambda event_id, event: self._notify("market_event", event_id, event)
            )
            result.source_events += len(tick.events)
            candidates += tick.signals

        self._publish(candidates, result)
        if self.recorder is not None:
            try:
                self.recorder.maybe_snapshot()
            except Exception:  # the forward log never stops the cycle
                log.exception("forward price snapshot failed")
        return result

    def _notify(self, event: str, *args: object) -> None:
        """Notifies the listener, if any. A broken listener never brings the cycle down."""
        handler = getattr(self.listener, event, None) if self.listener is not None else None
        if handler is None:
            return
        try:
            handler(*args)
        except Exception:
            log.exception("monitor listener failed on '%s'", event)

    # -------------------------------------------------------------- collection

    def _collect(self, result: WatchResult) -> None:
        cfg = self.settings.sec
        wanted = FORM4_TYPES | SC13D_TYPES
        # The 13D feeds take several seconds to answer; in parallel the cycle lasts as
        # long as the slowest one, not the sum of all.
        counts = {
            form: cfg.feed_count if form in FORM4_TYPES else cfg.feed_count_13d
            for form in cfg.feed_forms
        }
        first_urls = {form: feed_url(form, count=counts[form]) for form in cfg.feed_forms}
        # A feed that does not answer is not worth insisting on: the next cycle retries.
        first_pages = self.client.fetch_many(first_urls.values(), max_age=0, retries=1)
        for form in cfg.feed_forms:
            try:
                first_page = first_pages[first_urls[form]]
                if isinstance(first_page, SecHttpError):
                    raise first_page
                refs = fetch_current(
                    self.client,
                    form,
                    is_known=self.db.has_filing,
                    count=counts[form],
                    max_pages=cfg.feed_max_pages,
                    first_page=first_page,
                )
            except SecHttpError as exc:
                log.error("could not read the '%s' feed: %s", form, exc)
                result.errors += 1
                continue
            for ref in refs:
                if ref.form not in wanted:
                    continue
                result.seen += 1
                if self.db.add_filing(ref):
                    result.new_filings += 1

    # -------------------------------------------------------------- processing

    def _process(
        self,
        ref: FilingRef,
        payload: bytes | SecHttpError,
        result: WatchResult,
        candidates: list[Signal],
        touched_issuers: set[str],
    ) -> None:
        if isinstance(payload, SecHttpError):
            # Transient failure: the filing stays pending and goes into the next cycle.
            if payload.status_code in (None, 429) or (payload.status_code or 0) >= 500:
                log.warning("failed to download %s (will retry): %s", ref.accession, payload)
            else:
                self.db.mark_filing(ref.accession, ERROR, str(payload))
            result.errors += 1
            return
        text = decode(payload)

        try:
            submission = parse_submission(text)
            filed = submission.filed_date or ref.filed_date
            if ref.form in FORM4_TYPES:
                document = next(
                    (d for d in submission.documents if d.xml and "ownershipDocument" in d.xml),
                    None,
                )
                if document is None:
                    self.db.mark_filing(ref.accession, SKIPPED, "Form 4 without structured XML")
                    return
                form4 = parse_form4(document.xml or "")
                self.db.save_form4(ref.accession, filed, form4)
                if form4.purchases and not form4.is_amendment and form4.issuer_cik:
                    touched_issuers.add(form4.issuer_cik)
            else:
                doc = parse_13d(submission)
                self.db.save_13d(ref.accession, doc)
                signal = detect_activist_13d(
                    doc,
                    accession=ref.accession,
                    filing_date=filed,
                    cfg=self.settings.signals,
                    ticker=self.tickers.get(doc.issuer_cik) if doc.issuer_cik else "",
                )
                if signal is not None:
                    candidates.append(signal)
        except (Form4ParseError, Sc13dParseError, ValueError, KeyError) as exc:
            log.warning("could not parse %s: %s", ref.accession, exc)
            self.db.mark_filing(ref.accession, ERROR, f"{exc.__class__.__name__}: {exc}"[:500])
            result.errors += 1
            return

        self.db.mark_filing(ref.accession, PROCESSED)
        result.processed += 1

    def _backfill_issuer(self, issuer_cik: str, result: WatchResult) -> None:
        """Fetches the issuer's recent Form 4s that the monitor has not seen yet.

        Without it, on the first run cluster_buy would only see purchases filed
        after the radar started running.
        """
        cfg = self.settings.signals
        since = self.today - timedelta(days=cfg.cluster_window_days + cfg.cooldown_days)
        try:
            raw = self.client.get_bytes(SUBMISSIONS_URL.format(cik=int(issuer_cik)), max_age=600)
            recent = json.loads(raw)["filings"]["recent"]
        except (SecHttpError, ValueError, KeyError) as exc:
            log.warning("no recent history for issuer %s: %s", issuer_cik, exc)
            return

        rows = zip(
            recent.get("accessionNumber", []),
            recent.get("form", []),
            recent.get("filingDate", []),
            strict=False,
        )
        wanted: dict[str, date] = {}
        for accession, form, filed_raw in rows:
            if form != "4" or self.db.has_form4(accession):
                continue
            try:
                filed = date.fromisoformat(filed_raw)
            except ValueError:
                continue
            if filed >= since:
                wanted[accession] = filed

        urls = {acc: submission_txt_url(issuer_cik, acc) for acc in wanted}
        payloads = self.client.fetch_many(urls.values())
        for accession, filed in wanted.items():
            payload = payloads[urls[accession]]
            if isinstance(payload, SecHttpError):
                log.warning("backfill: failed on %s: %s", accession, payload)
                continue
            try:
                submission = parse_submission(decode(payload))
                document = next(
                    (d for d in submission.documents if d.xml and "ownershipDocument" in d.xml),
                    None,
                )
                if document is None:
                    continue
                form4 = parse_form4(document.xml or "")
            except (Form4ParseError, ValueError) as exc:
                log.warning("backfill: failed on %s: %s", accession, exc)
                continue
            filed = submission.filed_date or filed
            self.db.add_filing(
                FilingRef(
                    accession=accession,
                    form="4",
                    cik=normalize_cik(issuer_cik),
                    company=form4.issuer_name,
                    filed_date=filed,
                    url=filing_index_url(issuer_cik, accession),
                    accepted_at=submission.accepted_at,
                )
            )
            self.db.save_form4(accession, filed, form4)
            self.db.mark_filing(accession, PROCESSED)
            result.backfilled += 1

    # ----------------------------------------------------------------- signals

    def issuer_profile(self, cik: str) -> IssuerProfile | None:
        """SIC and fund filings of an issuer: from the database, else from the SEC registry."""
        stored = self.db.issuer_profile(cik)
        if stored is not None and (stored[0].strip() not in NO_SIC or stored[1] is not None):
            return IssuerProfile(*stored)
        found = self.sectors.profile(cik)
        if found is None:
            return None
        self.db.set_sector(cik, found.sic, sector_for_sic(found.sic), found.investment_company)
        self.sectors.flush()
        return found

    def _form4_signals(self, issuer_cik: str, result: WatchResult | None = None) -> list[Signal]:
        filings = self.db.purchase_filings(issuer_cik)
        cfg = self.settings.signals
        signals = detect_cluster_buys(
            filings,
            cfg,
            prior_signals={issuer_cik: self.db.prior_signal_dates(CLUSTER_BUY, issuer_cik)},
        ) + detect_big_officer_buys(
            filings,
            cfg,
            prior_signals={issuer_cik: self.db.prior_signal_dates(BIG_OFFICER_BUY, issuer_cik)},
        )
        if not signals:
            return signals
        kept, dropped = split_funds(signals, self.funds)
        if dropped:
            log.info(
                "%d insider buy signal(s) of %s dropped: the issuer is a fund",
                len(dropped),
                dropped[0].issuer_name or issuer_cik,
            )
            if result is not None:
                result.excluded_funds += len(dropped)
        return kept

    def _publish(self, candidates: list[Signal], result: WatchResult) -> None:
        """Stores new signals; summarizes and alerts only the recent ones.

        Signals rebuilt from history (older than the cluster window) are stored to
        keep the cooldown consistent, but without an alert. The summary column keeps
        the English text; the signal object carries the configured language.
        """
        max_age = timedelta(days=self.settings.signals.cluster_window_days)
        fresh = [
            s
            for s in candidates
            if self.today - s.signal_date <= max_age and not self.db.has_signal(s.dedupe_key)
        ]
        if fresh:
            self._notify("prepare", fresh)
        for signal in sorted(candidates, key=lambda s: (s.signal_date, -s.score)):
            if not self.db.add_signal(signal):
                continue
            stale = self.today - signal.signal_date > max_age
            if self.recorder is not None:
                self.recorder.signal(signal, alerted=not stale)
            if stale:
                result.stored_only += 1
                continue
            self.summarizer.summarize(signal, self._filing_context(signal))
            self.db.set_summary(signal, *self.summarizer.stored(signal))
            if dispatch(self.alerters, signal):
                self.db.mark_alerted(signal)
            result.signals.append(signal)
            self._notify("signal", signal)

    def _filing_context(self, signal: Signal) -> dict | None:
        """Data of the Form 4s behind the signal, so the summary can say who bought what."""
        accessions = signal.details.get("accessions") or [signal.trigger_accession]
        filings = [c for a in accessions[:MAX_CONTEXT_FILINGS] if (c := self.db.form4_context(a))]
        return {"filings": filings} if filings else None


def parse_since(text: str, *, now: datetime | None = None) -> date:
    """Turns "7d", "24h", "2w", "3m" or an ISO date into the cutoff date."""
    now = now or datetime.now()
    value = text.strip().lower()
    units = {
        "h": timedelta(hours=1),
        "d": timedelta(days=1),
        "w": timedelta(weeks=1),
        "m": timedelta(days=30),
    }
    if value[-1:] in units and value[:-1].isdigit():
        return (now - int(value[:-1]) * units[value[-1]]).date()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"invalid period: '{text}'. Use something like 7d, 24h, 2w, 3m or 2025-01-31."
        ) from exc
