"""What happened to a company after a signal, read from its own SEC filing history.

Used only to value the exit of positions whose prices Yahoo no longer has (survivorship
correction), never to select signals. Rules are fixed in research/phase2-plan.md (addendum a).
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

ACQUISITION = "acquisition"
BANKRUPTCY = "bankruptcy"
DELISTED = "voluntary_delisting"
STOPPED = "stopped_filing"
ACTIVE = "active"
UNKNOWN = "unknown"

MERGER_FORMS = {
    "DEFM14A",
    "DEFM14C",
    "PREM14A",
    "PREM14C",
    "SC 14D9",
    "SC TO-T",
    "SC 13E3",
    "SC 14D9/A",
    "SC TO-T/A",
    "SC 13E3/A",
}
DELIST_FORMS = {"25", "25-NSE"}
DEREG_FORMS = {"15-12B", "15-12G", "15-15D", "15F-12B", "15F-12G", "15F-15D"}


@dataclass(frozen=True)
class Outcome:
    kind: str
    terminal: date | None  # delisting / deregistration date, or last filing date
    evidence: str = ""  # form(s) that decided the class
    merger_doc: tuple[str, str] | None = None  # (accession, primary document) of the merger doc


def compact_submissions(payload: dict, pages: list[dict]) -> dict:
    """The fields of the SEC submissions API that phase 2 keeps on disk."""
    keep = ("accessionNumber", "filingDate", "form", "items", "primaryDocument", "reportDate")
    return {
        "cik": str(payload.get("cik", "")).zfill(10),
        "name": payload.get("name"),
        "tickers": payload.get("tickers"),
        "pages": [{k: page.get(k, []) for k in keep} for page in pages],
    }


def _rows(payload: dict):
    for page in payload.get("pages", []):
        n = len(page.get("form", []))
        for i in range(n):
            yield (
                page["filingDate"][i],
                page["form"][i],
                page.get("items", [""] * n)[i] or "",
                page["accessionNumber"][i],
                page.get("primaryDocument", [""] * n)[i] or "",
            )


def classify(
    payload: dict, *, after: date, today: date | None = None, stale_days: int = 180
) -> Outcome:
    """Terminal event of the company after `after` (the signal date).

    A company with a filing in the last `stale_days` days is still active.
    """
    today = today or date.today()
    if not payload or "error" in payload:
        return Outcome(UNKNOWN, None, "no submissions")
    rows = sorted({r for r in _rows(payload)})
    if not rows:
        return Outcome(UNKNOWN, None, "empty history")
    parsed = [(date.fromisoformat(d), f, items, acc, doc) for d, f, items, acc, doc in rows]
    later = [r for r in parsed if r[0] > after]
    ends = [r for r in later if r[1] in DELIST_FORMS or r[1] in DEREG_FORMS]
    if ends:
        terminal, evidence = ends[0][0], ends[0][1]
    else:
        last = parsed[-1][0]
        if (today - last).days <= stale_days:
            return Outcome(ACTIVE, None, "still filing")
        if last <= after:
            return Outcome(UNKNOWN, None, "no filing after signal")
        terminal, evidence = last, "last filing"
    lo = terminal - timedelta(days=548)
    window = [r for r in parsed if lo <= r[0] <= terminal + timedelta(days=5)]
    if any(r[1].startswith("8-K") and "1.03" in r[2].split(",") for r in window):
        return Outcome(BANKRUPTCY, terminal, "8-K 1.03")
    merger = [r for r in window if r[1] in MERGER_FORMS]
    close = [r for r in window if r[0] >= terminal - timedelta(days=60) and r[1].startswith("8-K")]
    item_sets = [set(r[2].split(",")) for r in close]
    if merger or any("5.01" in s or {"2.01", "3.01"} <= s for s in item_sets):
        doc = None
        for r in reversed(merger):
            if r[1].split("/")[0] in {
                "DEFM14A",
                "SC 14D9",
                "SC TO-T",
                "DEFM14C",
                "SC 13E3",
                "PREM14A",
                "PREM14C",
            }:
                doc = (r[3], r[4])
                break
        ev = merger[-1][1] if merger else "8-K 5.01/2.01"
        return Outcome(ACQUISITION, terminal, ev, doc)
    if evidence in DELIST_FORMS or evidence in DEREG_FORMS:
        return Outcome(DELISTED, terminal, evidence)
    return Outcome(STOPPED, terminal, evidence)


class OutcomeBook:
    """Compact submissions files (`<cik>.json.gz`) in a folder, classified on demand."""

    def __init__(self, folder: Path, today: date | None = None):
        self.folder = folder
        self.today = today
        self._cache: dict[str, dict] = {}

    def payload(self, cik: str) -> dict:
        if cik not in self._cache:
            path = self.folder / f"{cik}.json.gz"
            self._cache[cik] = (
                json.loads(gzip.decompress(path.read_bytes())) if path.exists() else {}
            )
        return self._cache[cik]

    def outcome(self, cik: str, after: date) -> Outcome:
        return classify(self.payload(cik), after=after, today=self.today)
