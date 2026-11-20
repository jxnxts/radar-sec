"""8-K and NT 10-K/10-Q in live mode.

Items come from the feed summary; the filing text is downloaded only for the items
whose rules read text (buybacks, executive exits, merger agreements). With a
`PressReleaseCollector`, the EX-99 exhibits (press releases) of each new 8-K also
become news items (see radar.sources.news.exhibits).
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime

from radar.http import SecHttpError, decode

from ..base import EIGHTK, MarketEvent, PollResult
from ..feeds import FeedItem, fetch_items
from ..news.exhibits import FilingInfo, PressReleaseCollector
from .rules import NT_FORMS, SPECS, Filing8K, detect
from .text import (
    BUYBACK_PHRASES,
    EXIT_PHRASES,
    ITEM_LABELS,
    MERGER_PHRASE,
    TEXT_ITEMS,
    exit_titles,
    find_phrases,
    items_from_header,
    items_from_summary,
    plain_text,
    quote_around,
)

log = logging.getLogger(__name__)

NT_INTERVAL_S = 900.0


def classify_text(filing: Filing8K, raw: str) -> Filing8K:
    """Fill the text-based flags of a filing from its `.txt` submission."""
    items = filing.items or items_from_header(raw)
    text = plain_text(raw)
    buyback = tuple(find_phrases(text, BUYBACK_PHRASES))
    exits = tuple(find_phrases(text, EXIT_PHRASES)) if "5.02" in items else ()
    merger = "1.01" in items and MERGER_PHRASE in text
    excerpt = ""
    for phrase in (*buyback[:1], *exits[:1], *((MERGER_PHRASE,) if merger else ())):
        excerpt = quote_around(text, phrase)
        if excerpt:
            break
    return replace(
        filing,
        items=items,
        buyback_phrases=buyback,
        exit_phrases=exits,
        exit_titles=tuple(exit_titles(list(exits))),
        merger=merger,
        excerpt=excerpt,
    )


def filing_event(filing: Filing8K, url: str | None) -> MarketEvent:
    flags = []
    if filing.buyback_phrases:
        flags.append("buyback")
    if filing.exit_titles:
        flags.append("exit")
    if filing.merger:
        flags.append("merger")
    if "2.02" in filing.items:
        flags.append("earnings")
    if filing.form in NT_FORMS:
        title = (
            f"{filing.form}: late {'annual' if filing.form == 'NT 10-K' else 'quarterly'} report"
        )
        kind = "nt_filing"
    else:
        labels = [ITEM_LABELS.get(i, i) for i in filing.items if i != "9.01"]
        title = f"8-K · {'; '.join(labels) or 'no items listed'}"
        kind = "8k"
    return MarketEvent(
        source=EIGHTK,
        kind=kind,
        key=filing.accession,
        event_date=filing.filing_date,
        issuer_cik=filing.cik,
        issuer_name=filing.name,
        ticker=filing.ticker,
        title=title,
        url=url,
        data={
            "form": filing.form,
            "items": list(filing.items),
            "item_labels": [ITEM_LABELS.get(i, i) for i in filing.items],
            "flags": flags,
            "exit_titles": list(filing.exit_titles),
            "excerpt": filing.excerpt,
        },
    )


class EightKSource:
    name = EIGHTK
    interval_s = 60.0

    def __init__(
        self,
        *,
        count: int = 100,
        max_pages: int = 3,
        press_releases: PressReleaseCollector | None = None,
    ):
        self.count = count
        self.max_pages = max_pages
        self.press_releases = press_releases
        self._last_nt: datetime | None = None

    def health(self) -> dict | None:
        """Press-release counters for /api/health (None when that part is off)."""
        return self.press_releases.health() if self.press_releases else None

    def _known(self, ctx, accession: str) -> bool:
        return ctx.store.has_event(EIGHTK, accession)

    def poll(self, ctx) -> PollResult:
        result = PollResult()
        items: list[FeedItem] = fetch_items(
            ctx.client,
            "8-K",
            is_known=lambda a: self._known(ctx, a),
            count=self.count,
            max_pages=self.max_pages,
        )
        now = datetime.now(UTC)
        if self._last_nt is None or (now - self._last_nt).total_seconds() >= NT_INTERVAL_S:
            self._last_nt = now
            for form in sorted(NT_FORMS):
                try:
                    items += fetch_items(
                        ctx.client,
                        form,
                        is_known=lambda a: self._known(ctx, a),
                        count=40,
                        max_pages=1,
                        retries=0,
                    )
                except SecHttpError as exc:  # the NT feeds are slow; next round tries again
                    log.info("feed %s unavailable: %s", form, exc)

        new = [
            i
            for i in items
            if i.ref.form in ("8-K", *NT_FORMS) and not self._known(ctx, i.ref.accession)
        ]
        filings: dict[str, Filing8K] = {}
        need_text: list[FeedItem] = []
        for item in new:
            ref = item.ref
            filing = Filing8K(
                accession=ref.accession,
                form=ref.form,
                cik=ref.cik,
                name=ref.company,
                filing_date=ref.filed_date,
                ticker=ctx.ticker_for(ref.cik),
                items=items_from_summary(item.summary),
            )
            filings[ref.accession] = filing
            if ref.form == "8-K" and set(filing.items) & TEXT_ITEMS:
                need_text.append(item)
        payloads = ctx.client.fetch_many(i.ref.txt_url for i in need_text)
        texts: dict[str, str] = {}
        for item in need_text:
            payload = payloads.get(item.ref.txt_url)
            if payload is None or isinstance(payload, SecHttpError):
                continue
            texts[item.ref.accession] = decode(payload)
            filings[item.ref.accession] = classify_text(
                filings[item.ref.accession], texts[item.ref.accession]
            )

        urls = {i.ref.accession: i.ref.url for i in new}
        for filing in filings.values():
            result.events.append(filing_event(filing, urls.get(filing.accession)))
        prior = {
            (kind, f.cik): ctx.prior_signal_dates(kind, f.cik)
            for f in filings.values()
            for kind in SPECS
        }
        result.signals += detect(filings.values(), prior_signals=prior)
        if self.press_releases is not None:
            self._press_releases(ctx, new, filings, texts, result)
        return result

    def _press_releases(
        self,
        ctx,
        new: list[FeedItem],
        filings: dict[str, Filing8K],
        texts: dict[str, str],
        result: PollResult,
    ) -> None:
        """EX-99 exhibits of the new 8-Ks, stored as news (a failure never stops the 8-Ks)."""
        infos = {
            i.ref.accession: FilingInfo(
                accession=i.ref.accession,
                form=i.ref.form,
                cik=i.ref.cik,
                name=i.ref.company,
                ticker=filings[i.ref.accession].ticker,
                index_url=i.ref.url,
                accepted_at=i.ref.accepted_at,
                items=filings[i.ref.accession].items,
            )
            for i in new
            if i.ref.form == "8-K"
        }
        news_before = len(result.records)
        try:
            self.press_releases.collect(
                ctx,
                result,
                from_text=[(infos[a], raw) for a, raw in texts.items() if a in infos],
                need_index=[info for a, info in infos.items() if a not in texts],
            )
        except Exception:  # noqa: BLE001 - press releases are extra; 8-K events still count
            log.exception("8-K press releases failed")
        stored = len(result.records) - news_before
        if stored:
            result.note = f"{stored} press release(s) from EX-99 exhibits"
