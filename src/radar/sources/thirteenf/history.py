"""13F history from the SEC Form 13F data sets, streamed one zip at a time.

The zips are grouped by filing date. Holding every manager's positions for six
years would not fit in memory, so each report is reduced to its set of CUSIPs and
a quarter is dropped once the next one has been computed.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from radar.models import Signal

from .holdings import Holding, Report, read_dataset
from .managers import NOTABLE_MANAGERS
from .rules import (
    ConsensusStats,
    Resolver,
    filing_deadline,
    first_reports,
    fund_consensus,
    notable_new_positions,
    previous_quarter_end,
)

log = logging.getLogger(__name__)

DATASET_PAGE_URL = "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets"
_QUARTER_ZIP = re.compile(r"(\d{4})q(\d)_form13f\.zip$")
_RANGE_ZIP = re.compile(r"(\d{2}[a-z]{3}\d{4})-(\d{2}[a-z]{3}\d{4})_form13f\.zip$")


def zip_window(name: str) -> tuple[date, date] | None:
    """Filing-date window covered by a data set zip, from its file name."""
    if m := _QUARTER_ZIP.search(name):
        year, quarter = int(m[1]), int(m[2])
        start = date(year, 3 * quarter - 2, 1)
        end_month = 3 * quarter
        nxt = date(year + (end_month == 12), end_month % 12 + 1, 1)
        return start, date.fromordinal(nxt.toordinal() - 1)
    if m := _RANGE_ZIP.search(name):
        return (datetime.strptime(m[1], "%d%b%Y").date(), datetime.strptime(m[2], "%d%b%Y").date())
    return None


def dataset_links(page_html: str) -> list[str]:
    return re.findall(r'href="(/files/[^"]+_form13f\.zip)"', page_html)


@dataclass
class ThirteenFHistory:
    consensus: list[Signal] = field(default_factory=list)
    notable: list[Signal] = field(default_factory=list)
    quarters: list[ConsensusStats] = field(default_factory=list)
    reports_read: int = 0


def load_history(
    paths: list[Path],
    resolve: Resolver,
    *,
    first_period: date,
    last_period: date,
    progress: Callable[[str], None] | None = None,
) -> ThirteenFHistory:
    """Signals for report quarters in [first_period, last_period] (quarter-end dates)."""
    ordered = sorted(
        ((w, p) for p in paths if (w := zip_window(p.name)) is not None), key=lambda x: x[0]
    )
    out = ThirteenFHistory()
    compact: dict[tuple[str, date], Holding] = {}
    names: dict[str, str] = {}
    notable: list[Report] = []
    done: set[date] = set()

    def ready_periods(loaded_until: date) -> list[date]:
        periods = sorted({p for (_, p) in compact})
        return [
            p
            for p in periods
            if p not in done
            and first_period <= p <= last_period
            and filing_deadline(p) <= loaded_until
        ]

    for (_window_start, window_end), path in ordered:
        if progress:
            progress(path.name)
        reports = read_dataset(path)
        out.reports_read += len(reports)
        for report in reports:
            if report.cik in NOTABLE_MANAGERS:
                notable.append(report)
            if report.positions > 3000:  # index-like giants are never "active" filers
                continue
            key = (report.cik, report.period)
            current = compact.get(key)
            if current is None or report.filing_date < current.filing_date:
                compact[key] = report.compact()
            for cusip, name in report.names.items():
                names.setdefault(cusip, name)
        del reports
        for period in ready_periods(window_end):
            signals, stats = fund_consensus(compact, period, resolve, issuer_names=names)
            out.consensus += signals
            out.quarters.append(stats)
            done.add(period)
            log.info(
                "13F %s: %d active filers, %d CUSIPs in the universe",
                period,
                stats.active_filers,
                stats.universe,
            )
            keep_from = previous_quarter_end(period)
            for key in [k for k in compact if k[1] < keep_from]:
                del compact[key]

    picked = first_reports(notable)
    out.notable = [
        s
        for s in notable_new_positions(picked, resolve)
        if first_period <= date.fromisoformat(s.details["period"]) <= last_period
    ]
    return out
