"""Minimal Schedule 13D parser: who bought, how much of the company and which issuer.

Two formats:
- since Dec 2024 the 13D is structured XML (`edgarSubmission`), read field by field;
- before that it is HTML/free text, from which we extract what we can using the
  cover page patterns ("NAME OF REPORTING PERSON",
  "PERCENT OF CLASS REPRESENTED BY AMOUNT IN ROW (11)").
"""

from __future__ import annotations

import html
import re
from datetime import date, datetime
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as ET

from radar.edgar import Submission, normalize_cik
from radar.models import SC13D_TYPES, Reporter, Schedule13D


class Sc13dParseError(ValueError):
    pass


# ------------------------------------------------------------------- XML (new)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(node: Element | None, name: str) -> Element | None:
    if node is None:
        return None
    for child in node.iter():
        if _local(child.tag) == name:
            return child
    return None


def _findall(node: Element | None, name: str) -> list[Element]:
    if node is None:
        return []
    return [child for child in node.iter() if _local(child.tag) == name]


def _text(node: Element | None, name: str) -> str:
    found = _find(node, name)
    return (found.text or "").strip() if found is not None else ""


def _number(text: str) -> float | None:
    cleaned = re.sub(r"[,%\s]", "", text or "")
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def _us_date(text: str) -> date | None:
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


def parse_13d_xml(xml: str | bytes) -> Schedule13D:
    try:
        root = ET.fromstring(xml.strip() if isinstance(xml, str) else xml)
    except ET.ParseError as exc:
        raise Sc13dParseError(f"invalid XML: {exc}") from exc
    if _local(root.tag) != "edgarSubmission":
        raise Sc13dParseError(f"unexpected document: <{_local(root.tag)}>")

    cover = _find(root, "coverPageHeader")
    issuer = _find(cover, "issuerInfo")
    reporters = tuple(
        Reporter(
            name=_text(node, "reportingPersonName"),
            cik=normalize_cik(_text(node, "reportingPersonCIK")),
            shares=_number(_text(node, "aggregateAmountOwned")),
            percent=_number(_text(node, "percentOfClass")),
        )
        for node in _findall(root, "reportingPersonInfo")
    )

    return Schedule13D(
        form=_text(root, "submissionType"),
        issuer_name=_text(issuer, "issuerName"),
        issuer_cik=normalize_cik(_text(issuer, "issuerCIK")),
        reporters=reporters,
        source_format="xml",
        cusip=_text(issuer, "issuerCusipNumber"),
        security_title=_text(cover, "securitiesClassTitle"),
        event_date=_us_date(_text(cover, "dateOfEvent")),
        purpose=_text(_find(root, "item4"), "transactionPurpose"),
    )


# --------------------------------------------------------------- HTML (legacy)

_BLOCK_END = re.compile(r"(?i)<(br|/p|/div|/tr|/td|/th|/h\d|/li|/table)[^>]*>")
_NAME_LABEL = re.compile(
    r"NAMES?\s+OF\s+REPORTING\s+PERSONS?(?:\s*\(?S\)?)?"
    r"(?:[\s.:]*I\.R\.S\.\s+IDENTIFICATION\s+NOS?\.?\s+OF\s+ABOVE\s+PERSONS?"
    r"(?:\s*\(ENTITIES ONLY\))?)?",
    re.I,
)
_PERCENT_LABEL = re.compile(r"PERCENT\s+OF\s+CLASS\s+REPRESENTED\s+BY\s+AMOUNT\s+IN\s+ROW", re.I)
_AMOUNT_LABEL = re.compile(r"AGGREGATE\s+AMOUNT\s+BENEFICIALLY\s+OWNED\s+BY\s+EACH", re.I)
_PERCENT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")
_SHARES = re.compile(r"\b(\d{1,3}(?:,\d{3})+|\d{4,})\b")
_EVENT_DATE = re.compile(r"([A-Z][a-z]+ \d{1,2}, \d{4})\s*\(\s*Date of Event", re.S)
_CUSIP = re.compile(r"CUSIP\s+(?:No\.?|Number)[\s:]*([0-9A-Z]{6,9})", re.I)
# Cover page lines that are labels/numbering, not someone's name.
_NOT_A_NAME = re.compile(
    r"^(\(?\d{1,2}\)?\.?|I\.R\.S\..*|S\.S\..*|\(ENTITIES ONLY\)|CHECK\b.*|SEC USE ONLY.*)$", re.I
)


def html_to_text(markup: str) -> str:
    """Converts the filing's HTML into plain text, one line per visual block."""
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", markup)
    text = _BLOCK_END.sub("\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def _following_lines(text: str, start: int, limit: int = 6) -> list[str]:
    return [line.strip() for line in text[start : start + 600].split("\n")[: limit + 1]]


def _first_name(text: str, start: int) -> str:
    for line in _following_lines(text, start):
        candidate = line.strip(" :-").lstrip(". ")
        if not candidate or _NOT_A_NAME.match(candidate):
            continue
        # The next cover page label ends the search: there was no name there.
        if re.match(r"(?i)check the appropriate box", candidate):
            break
        return candidate
    return ""


def parse_13d_legacy(markup: str, submission: Submission | None = None) -> Schedule13D:
    """Extracts what it can from an old 13D (HTML or plain text).

    It is heuristic: the cover pages have no formal structure. The issuer comes
    from the EDGAR header when available, which is reliable; names and
    percentages come from the text.
    """
    text = html_to_text(markup)

    name_marks = [m.end() for m in _NAME_LABEL.finditer(text)]
    reporters: list[Reporter] = []
    for i, start in enumerate(name_marks):
        end = name_marks[i + 1] if i + 1 < len(name_marks) else min(len(text), start + 6000)
        page = text[start:end]
        name = _first_name(text, start)
        if not name:
            continue

        percent = None
        if (pm := _PERCENT_LABEL.search(page)) and (
            value := _PERCENT.search(page[pm.end() : pm.end() + 200])
        ):
            percent = float(value.group(1))

        shares = None
        if (am := _AMOUNT_LABEL.search(page)) and (
            value := _SHARES.search(page[am.end() : am.end() + 200])
        ):
            shares = float(value.group(1).replace(",", ""))

        reporters.append(Reporter(name=name, shares=shares, percent=percent))

    # Without a recognizable cover page, we can still take the largest percentage after the label.
    if not reporters:
        for pm in _PERCENT_LABEL.finditer(text):
            if value := _PERCENT.search(text[pm.end() : pm.end() + 200]):
                reporters.append(Reporter(name="", percent=float(value.group(1))))

    form = issuer_name = issuer_cik = ""
    if submission is not None:
        form = submission.form
        if subject := submission.party("subject", "issuer"):
            issuer_name, issuer_cik = subject.name, subject.cik
        filer_ciks = {p.name.lower(): p.cik for p in submission.parties_with("filer")}
        reporters = [
            Reporter(r.name, filer_ciks.get(r.name.lower(), ""), r.shares, r.percent)
            for r in reporters
        ]
        if not any(r.name for r in reporters):
            # Unreadable cover page: at least record who filed, according to EDGAR.
            best = max((r.percent for r in reporters if r.percent is not None), default=None)
            reporters = [
                Reporter(p.name, p.cik, percent=best) for p in submission.parties_with("filer")
            ]

    event = _EVENT_DATE.search(text)
    event_date = None
    if event:
        try:
            event_date = datetime.strptime(event.group(1), "%B %d, %Y").date()
        except ValueError:
            event_date = None

    cusip = _CUSIP.search(text)
    return Schedule13D(
        form=form or "SC 13D",
        issuer_name=issuer_name,
        issuer_cik=issuer_cik,
        reporters=tuple(reporters),
        source_format="legacy",
        cusip=cusip.group(1) if cusip else "",
        event_date=event_date,
    )


# ------------------------------------------------------------------- entry point


def parse_13d(submission: Submission) -> Schedule13D:
    """Picks the right parser for the submission (new XML or old HTML/text)."""
    main = next((d for d in submission.documents if d.type in SC13D_TYPES), None)
    main = main or submission.primary_document
    if main is None:
        raise Sc13dParseError("submission has no documents")

    if (xml := main.xml) and "edgarSubmission" in xml[:2000]:
        parsed = parse_13d_xml(xml)
        subject = submission.party("subject", "issuer")
        # The EDGAR header fills in what the filer left blank.
        if subject and (not parsed.issuer_cik or not parsed.issuer_name):
            parsed = Schedule13D(
                form=parsed.form or submission.form,
                issuer_name=parsed.issuer_name or subject.name,
                issuer_cik=parsed.issuer_cik or subject.cik,
                reporters=parsed.reporters,
                source_format=parsed.source_format,
                cusip=parsed.cusip,
                security_title=parsed.security_title,
                event_date=parsed.event_date,
                purpose=parsed.purpose,
            )
        return parsed
    return parse_13d_legacy(main.text, submission)
