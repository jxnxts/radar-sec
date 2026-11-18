"""Reading EDGAR's complete submission file (.txt in SGML format).

Every filing has an `<accession>.txt` with a header listing the parties
involved and every document (XML, HTML, exhibits) embedded. Downloading that
file costs a single request and works for both Form 4 and 13D.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime

_DOCUMENT = re.compile(r"<DOCUMENT>(.*?)</DOCUMENT>", re.S)
_TAG = re.compile(r"^<(TYPE|SEQUENCE|FILENAME|DESCRIPTION)>(.*)$", re.M)
_TEXT = re.compile(r"<TEXT>(.*?)(?:</TEXT>|\Z)", re.S)
_XML = re.compile(r"<XML>\s*(.*?)\s*</XML>", re.S)
_HEADER = re.compile(r"<SEC-HEADER>(.*?)</SEC-HEADER>", re.S)

# Header sections that identify a party and its role in the filing.
_PARTY_SECTIONS = {
    "SUBJECT COMPANY": "subject",
    "ISSUER": "issuer",
    "FILED BY": "filer",
    "REPORTING-OWNER": "owner",
    "FILER": "filer",
}


@dataclass(frozen=True)
class Party:
    role: str  # subject | issuer | filer | owner
    name: str
    cik: str


@dataclass(frozen=True)
class Document:
    type: str
    filename: str
    description: str
    text: str

    @property
    def xml(self) -> str | None:
        match = _XML.search(self.text)
        return match.group(1) if match else None


@dataclass(frozen=True)
class Submission:
    accession: str
    form: str
    filed_date: date | None
    accepted_at: datetime | None
    parties: tuple[Party, ...] = ()
    documents: tuple[Document, ...] = field(default_factory=tuple)

    def party(self, *roles: str) -> Party | None:
        for role in roles:
            for p in self.parties:
                if p.role == role:
                    return p
        return None

    def parties_with(self, role: str) -> list[Party]:
        return [p for p in self.parties if p.role == role]

    @property
    def primary_document(self) -> Document | None:
        return self.documents[0] if self.documents else None


def normalize_cik(cik: str | int | None) -> str:
    """CIK without leading zeros ("0000936395" → "936395")."""
    text = str(cik or "").strip()
    return text.lstrip("0") if text.strip("0") else ""


def accession_nodash(accession: str) -> str:
    return accession.replace("-", "")


def submission_txt_url(cik: str, accession: str) -> str:
    return (
        f"https://www.sec.gov/Archives/edgar/data/{normalize_cik(cik)}/"
        f"{accession_nodash(accession)}/{accession}.txt"
    )


def filing_index_url(cik: str, accession: str) -> str:
    return (
        f"https://www.sec.gov/Archives/edgar/data/{normalize_cik(cik)}/"
        f"{accession_nodash(accession)}/{accession}-index.htm"
    )


def _header_value(header: str, label: str) -> str:
    match = re.search(rf"^\s*{re.escape(label)}:\s*(.+?)\s*$", header, re.M)
    return match.group(1).strip() if match else ""


def _parse_parties(header: str) -> tuple[Party, ...]:
    parties: list[Party] = []
    role: str | None = None
    name = ""
    for raw in header.splitlines():
        line = raw.strip()
        if not line:
            continue
        section = line.rstrip(":").strip()
        if line.endswith(":") and section in _PARTY_SECTIONS:
            role, name = _PARTY_SECTIONS[section], ""
            continue
        if role is None:
            continue
        if line.startswith("COMPANY CONFORMED NAME:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("CENTRAL INDEX KEY:"):
            parties.append(Party(role, name, normalize_cik(line.split(":", 1)[1])))
            role = None  # the rest of the block (addresses, former names) is irrelevant
    return tuple(parties)


def parse_submission(text: str) -> Submission:
    header_match = _HEADER.search(text)
    header = header_match.group(1) if header_match else text[:20000]

    filed_raw = _header_value(header, "FILED AS OF DATE")
    filed = datetime.strptime(filed_raw, "%Y%m%d").date() if len(filed_raw) == 8 else None

    accepted: datetime | None = None
    acc_match = re.search(r"<ACCEPTANCE-DATETIME>(\d{14})", text[:2000])
    if acc_match:
        accepted = datetime.strptime(acc_match.group(1), "%Y%m%d%H%M%S")

    documents: list[Document] = []
    for block in _DOCUMENT.findall(text):
        tags = {k: v.strip() for k, v in _TAG.findall(block[:2000])}
        body = _TEXT.search(block)
        documents.append(
            Document(
                type=tags.get("TYPE", ""),
                filename=tags.get("FILENAME", ""),
                description=tags.get("DESCRIPTION", ""),
                text=body.group(1) if body else "",
            )
        )

    return Submission(
        accession=_header_value(header, "ACCESSION NUMBER"),
        form=_header_value(header, "CONFORMED SUBMISSION TYPE"),
        filed_date=filed,
        accepted_at=accepted,
        parties=_parse_parties(header),
        documents=tuple(documents),
    )
