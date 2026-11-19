"""13F-HR holdings: the SEC quarterly data sets (history) and the information-table XML
of a single filing (live), both reduced to the same `Report` shape."""

from __future__ import annotations

import io
import re
import sys
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from defusedxml import ElementTree as ET

from radar.edgar import normalize_cik


@dataclass
class Report:
    """One 13F-HR: the manager's long share positions for a quarter.

    `shares[cusip]` and `values[cusip]` are summed over the rows of the filing (a manager
    reports the same CUSIP once per sub-manager or discretion type). Values are only
    compared inside one filing: the SEC switched the column from thousands to dollars
    in January 2023.
    """

    accession: str
    cik: str
    manager: str
    period: date  # quarter end
    filing_date: date
    shares: dict[str, float] = field(default_factory=dict)
    values: dict[str, float] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)  # CUSIP → issuer name
    total_value: float = 0.0  # all rows, including options and principal amounts

    @property
    def positions(self) -> int:
        return len(self.shares)

    @property
    def cusips(self):
        return self.shares.keys()

    def compact(self) -> Holding:
        return Holding(
            self.accession,
            self.cik,
            self.period,
            self.filing_date,
            tuple(sys.intern(c) for c in self.shares),
        )

    def weight(self, cusip: str) -> float:
        return self.values.get(cusip, 0.0) / self.total_value if self.total_value else 0.0


@dataclass(frozen=True)
class Holding:
    """A report reduced to its set of CUSIPs (enough for the breadth consensus)."""

    accession: str
    cik: str
    period: date
    filing_date: date
    cusips: tuple[str, ...]

    @property
    def positions(self) -> int:
        return len(self.cusips)


def normalize_cusip(value: str | None) -> str:
    text = re.sub(r"[^0-9A-Za-z]", "", str(value or "")).upper()
    return text if len(text) == 9 else ""


def _sec_date(text: str) -> date | None:
    try:
        return datetime.strptime(text.strip(), "%d-%b-%Y").date()
    except (AttributeError, ValueError):
        return None


def read_dataset(path: Path, *, keep: set[str] | None = None) -> list[Report]:
    """Original 13F-HR reports in one SEC data set zip (amendments are skipped).

    `keep` limits the managers (by CIK) to save memory; None reads all of them.
    """
    with zipfile.ZipFile(path) as archive:
        # Some zips keep the tables inside a folder ("01JUN2025-31AUG2025_form13f/...").
        members = {n.rsplit("/", 1)[-1].upper(): n for n in archive.namelist()}

        def table(name: str, usecols: list[str], chunksize: int | None = None):
            handle = archive.open(members[f"{name}.TSV"])
            return pd.read_csv(
                io.TextIOWrapper(handle, encoding="utf-8", errors="replace"),
                sep="\t",
                dtype=str,
                usecols=usecols,
                quoting=3,
                on_bad_lines="skip",
                keep_default_na=False,
                chunksize=chunksize,
            )

        sub = table(
            "SUBMISSION",
            ["ACCESSION_NUMBER", "FILING_DATE", "SUBMISSIONTYPE", "CIK", "PERIODOFREPORT"],
        )
        sub = sub[sub["SUBMISSIONTYPE"] == "13F-HR"]
        cover = table("COVERPAGE", ["ACCESSION_NUMBER", "ISAMENDMENT", "FILINGMANAGER_NAME"])
        sub = sub.merge(cover, on="ACCESSION_NUMBER", how="left")
        sub = sub[sub["ISAMENDMENT"].fillna("").str.upper() != "Y"]
        sub["CIK"] = sub["CIK"].map(normalize_cik)
        if keep is not None:
            sub = sub[sub["CIK"].isin(keep)]
        accessions = set(sub["ACCESSION_NUMBER"])

        # The information table has millions of rows: read it in chunks and keep only
        # the aggregates.
        totals_parts: list[pd.Series] = []
        long_parts: list[pd.DataFrame] = []
        for info in table(
            "INFOTABLE",
            [
                "ACCESSION_NUMBER",
                "NAMEOFISSUER",
                "CUSIP",
                "VALUE",
                "SSHPRNAMT",
                "SSHPRNAMTTYPE",
                "PUTCALL",
            ],
            chunksize=500_000,
        ):
            info = info[info["ACCESSION_NUMBER"].isin(accessions)]
            if info.empty:
                continue
            value = pd.to_numeric(info["VALUE"], errors="coerce").fillna(0.0)
            shares = pd.to_numeric(info["SSHPRNAMT"], errors="coerce").fillna(0.0)
            totals_parts.append(value.groupby(info["ACCESSION_NUMBER"]).sum())
            mask = (
                (info["SSHPRNAMTTYPE"].str.upper() == "SH") & (info["PUTCALL"] == "") & (shares > 0)
            )
            part = pd.DataFrame(
                {
                    "ACCESSION_NUMBER": info["ACCESSION_NUMBER"][mask],
                    "CUSIP": info["CUSIP"][mask].map(normalize_cusip),
                    "shares": shares[mask],
                    "value": value[mask],
                    "name": info["NAMEOFISSUER"][mask],
                }
            )
            part = part[part["CUSIP"] != ""]
            long_parts.append(
                part.groupby(["ACCESSION_NUMBER", "CUSIP"]).agg(
                    shares=("shares", "sum"), value=("value", "sum"), name=("name", "first")
                )
            )
    totals = pd.concat(totals_parts).groupby(level=0).sum().to_dict() if totals_parts else {}
    if long_parts:
        grouped = (
            pd.concat(long_parts)
            .groupby(level=[0, 1])
            .agg(shares=("shares", "sum"), value=("value", "sum"), name=("name", "first"))
        )
    else:
        grouped = pd.DataFrame(
            columns=["shares", "value", "name"],
            index=pd.MultiIndex.from_tuples([], names=["a", "c"]),
        )

    by_accession: dict[str, pd.DataFrame] = {
        acc: frame.droplevel(0) for acc, frame in grouped.groupby(level=0)
    }
    reports: list[Report] = []
    for row in sub.itertuples(index=False):
        period, filed = _sec_date(row.PERIODOFREPORT), _sec_date(row.FILING_DATE)
        if period is None or filed is None:
            continue
        frame = by_accession.get(row.ACCESSION_NUMBER)
        report = Report(
            accession=row.ACCESSION_NUMBER,
            cik=row.CIK,
            manager=row.FILINGMANAGER_NAME or "",
            period=period,
            filing_date=filed,
            total_value=float(totals.get(row.ACCESSION_NUMBER, 0.0)),
        )
        if frame is not None:
            report.shares = frame["shares"].to_dict()
            report.values = frame["value"].to_dict()
            report.names = frame["name"].to_dict()
        reports.append(report)
    return reports


def _strip_ns(root) -> None:
    for node in root.iter():
        if isinstance(node.tag, str) and "}" in node.tag:
            node.tag = node.tag.split("}", 1)[1]


def parse_submission(
    text: str, *, accession: str = "", filing_date: date | None = None, cik: str = ""
) -> Report:
    """A 13F-HR `.txt` submission (cover page XML + information table XML)."""
    blocks = re.findall(r"<XML>(.*?)</XML>", text, re.S | re.I)
    cover_xml = next((b for b in blocks if "edgarSubmission" in b), "")
    table_xml = next((b for b in blocks if "informationTable" in b), "")
    if not table_xml:
        raise ValueError("13F-HR without an information table")
    manager, period = "", None
    if cover_xml:
        cover = ET.fromstring(cover_xml.strip().encode())
        _strip_ns(cover)
        manager = (cover.findtext(".//filingManager/name") or "").strip()
        raw = (
            cover.findtext(".//periodOfReport")
            or cover.findtext(".//reportCalendarOrQuarter")
            or ""
        ).strip()
        for fmt in ("%m-%d-%Y", "%m/%d/%Y", "%Y-%m-%d"):
            try:
                period = datetime.strptime(raw, fmt).date()
                break
            except ValueError:
                continue
        cik = cik or normalize_cik(cover.findtext(".//filerCredentials/cik"))
    if not accession:
        found = re.search(r"ACCESSION NUMBER:\s*(\S+)", text)
        accession = found.group(1) if found else ""
    if filing_date is None:
        found = re.search(r"FILED AS OF DATE:\s*(\d{8})", text)
        filing_date = datetime.strptime(found.group(1), "%Y%m%d").date() if found else None
    if period is None or filing_date is None:
        raise ValueError("13F-HR without period or filing date")

    root = ET.fromstring(table_xml.strip().encode())
    _strip_ns(root)
    report = Report(
        accession=accession, cik=cik, manager=manager, period=period, filing_date=filing_date
    )
    for row in root.iter("infoTable"):
        value = float((row.findtext("value") or "0").replace(",", "") or 0)
        report.total_value += value
        kind = (row.findtext(".//sshPrnamtType") or "").strip().upper()
        if kind != "SH" or (row.findtext("putCall") or "").strip():
            continue
        cusip = normalize_cusip(row.findtext("cusip"))
        shares = float((row.findtext(".//sshPrnamt") or "0").replace(",", "") or 0)
        if not cusip or shares <= 0:
            continue
        report.shares[cusip] = report.shares.get(cusip, 0.0) + shares
        report.values[cusip] = report.values.get(cusip, 0.0) + value
        report.names.setdefault(cusip, (row.findtext("nameOfIssuer") or "").strip())
    return report
