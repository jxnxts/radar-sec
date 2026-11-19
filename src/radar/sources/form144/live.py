"""Form 144 in live mode: `getcurrent` feed → XML → notices, events and signals."""

from __future__ import annotations

import logging
import re
from datetime import timedelta

from radar.edgar import normalize_cik
from radar.http import SecHttpError, decode

from ..base import FORM144, MarketEvent, PollResult
from ..feeds import fetch_items
from .parser import Form144ParseError, extract_xml, parse_form144
from .rules import CLUSTER_WINDOW_DAYS, FORM144_CLUSTER, Notice, detect_clusters, large_sale

log = logging.getLogger(__name__)

_REPORTING_CIK = re.compile(r"REPORTING-OWNER:.*?CENTRAL INDEX KEY:\s*(\d+)", re.S)


def seller_cik(text: str, feed_ciks: tuple[str, ...], xml_filer: str) -> str:
    """The seller: the feed's "Reporting" entry, else the header, else the XML filer."""
    if feed_ciks:
        return normalize_cik(feed_ciks[0])
    found = _REPORTING_CIK.search(text.split("</SEC-HEADER>", 1)[0])
    return normalize_cik(found.group(1)) if found else xml_filer


def notice_event(notice: Notice, url: str | None) -> MarketEvent:
    value = notice.market_value
    parts = [f"{notice.seller_name} ({', '.join(notice.relationships) or 'affiliate'})"]
    if value:
        parts.append(f"plans to sell US$ {value / 1e6:,.2f} mi")
    if notice.percent_outstanding:
        parts.append(f"{notice.percent_outstanding:.2f}% of shares")
    return MarketEvent(
        source=FORM144,
        kind="form144",
        key=notice.accession,
        event_date=notice.filing_date,
        issuer_cik=notice.issuer_cik,
        issuer_name=notice.issuer_name,
        ticker=notice.ticker,
        title=" · ".join(parts),
        url=url,
        data={
            "seller": notice.seller_name,
            "seller_cik": notice.seller_cik,
            "relationships": list(notice.relationships),
            "value": value,
            "units": notice.units,
            "percent_outstanding": notice.percent_outstanding,
            "approx_sale_date": notice.approx_sale_date.isoformat()
            if notice.approx_sale_date
            else None,
        },
    )


class Form144Source:
    name = FORM144
    interval_s = 60.0

    def __init__(self, *, count: int = 100, max_pages: int = 3):
        self.count = count
        self.max_pages = max_pages

    def poll(self, ctx) -> PollResult:
        result = PollResult()
        items = fetch_items(
            ctx.client,
            "144",
            is_known=ctx.store.has_notice,
            count=self.count,
            max_pages=self.max_pages,
        )
        new = [
            i for i in items if i.ref.form == "144" and not ctx.store.has_notice(i.ref.accession)
        ]
        if not new:
            return result
        payloads = ctx.client.fetch_many(i.ref.txt_url for i in new)
        touched: set[str] = set()
        for item in new:
            payload = payloads.get(item.ref.txt_url)
            if payload is None or isinstance(payload, SecHttpError):
                continue
            text = decode(payload)
            try:
                doc = parse_form144(extract_xml(text))
            except Form144ParseError as exc:
                log.warning("Form 144 %s: %s", item.ref.accession, exc)
                continue
            if doc.is_amendment or not doc.issuer_cik:
                continue
            notice = Notice(
                accession=item.ref.accession,
                issuer_cik=doc.issuer_cik,
                issuer_name=doc.issuer_name or item.ref.company,
                seller_cik=seller_cik(text, item.filer_ciks, doc.seller_cik),
                seller_name=doc.seller_name,
                filing_date=item.ref.filed_date,
                ticker=ctx.ticker_for(doc.issuer_cik),
                market_value=doc.market_value,
                percent_outstanding=doc.percent_of_outstanding,
                relationships=doc.relationships,
                units=doc.units_to_sell,
                units_outstanding=doc.units_outstanding,
                approx_sale_date=doc.approx_sale_date,
            )
            ctx.store.add_notice(notice)
            result.events.append(notice_event(notice, item.ref.url))
            if (signal := large_sale(notice)) is not None:
                result.signals.append(signal)
            touched.add(notice.issuer_cik)

        since = ctx.today - timedelta(days=CLUSTER_WINDOW_DAYS + 30)
        for issuer in touched:
            rows = ctx.store.notices(issuer, since)
            notices = [
                Notice(
                    accession=r["accession"],
                    issuer_cik=r["issuer_cik"],
                    issuer_name=r["issuer_name"] or "",
                    seller_cik=r["seller_cik"],
                    seller_name=r["seller_name"] or "",
                    filing_date=ctx.parse_date(r["filing_date"]),
                    ticker=r["ticker"] or "",
                    market_value=r["market_value"],
                    relationships=tuple(x for x in (r["relationships"] or "").split(", ") if x),
                )
                for r in rows
            ]
            prior = {issuer: ctx.prior_signal_dates(FORM144_CLUSTER, issuer)}
            for signal in detect_clusters(notices, prior_signals=prior):
                if (ctx.today - signal.signal_date).days <= CLUSTER_WINDOW_DAYS:
                    result.signals.append(signal)
        return result
