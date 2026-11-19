"""Form 144 (notice of proposed sale of securities) from its XML primary document."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from defusedxml import ElementTree as ET

from radar.edgar import normalize_cik

# Form 144 relationship labels → the role codes the rest of the radar uses.
ROLE_CODES = {
    "10% Securityholder": "10% owner",
    "Officer": "Officer",
    "Director": "Director",
    "Other": "Other",
}


class Form144ParseError(ValueError):
    pass


@dataclass(frozen=True)
class Form144:
    issuer_cik: str
    issuer_name: str
    seller_name: str
    seller_cik: str  # filer CIK (the seller files for themselves or through an agent)
    relationships: tuple[str, ...]  # "Officer", "Director", "10% Securityholder"...
    security_class: str
    units_to_sell: float | None
    market_value: float | None  # aggregate market value of the units to be sold (US$)
    units_outstanding: float | None
    approx_sale_date: date | None
    exchange: str
    acquisition_nature: tuple[str, ...]  # how the shares were acquired (RSU, option, purchase...)
    plan_adoption_dates: tuple[date, ...]  # Rule 10b5-1 plan adoption, when declared
    notice_date: date | None
    is_amendment: bool = False

    @property
    def percent_of_outstanding(self) -> float | None:
        if not self.units_to_sell or not self.units_outstanding:
            return None
        return 100.0 * self.units_to_sell / self.units_outstanding


def _strip_ns(root) -> None:
    for node in root.iter():
        if isinstance(node.tag, str) and "}" in node.tag:
            node.tag = node.tag.split("}", 1)[1]


def _num(text: str | None) -> float | None:
    if not text:
        return None
    try:
        return float(text.replace(",", "").strip())
    except ValueError:
        return None


def _date(text: str | None) -> date | None:
    if not text:
        return None
    text = text.strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def extract_xml(submission_text: str) -> str:
    """The `<XML>` block of the Form 144 document inside an EDGAR `.txt` submission."""
    for block in re.findall(r"<XML>(.*?)</XML>", submission_text, re.S | re.I):
        if "edgarSubmission" in block and ("issuerInfo" in block or "noOfUnitsSold" in block):
            return block.strip()
    raise Form144ParseError("no Form 144 XML document in the submission")


def parse_form144(xml: str) -> Form144:
    try:
        root = ET.fromstring(xml.encode() if isinstance(xml, str) else xml)
    except ET.ParseError as exc:
        raise Form144ParseError(f"invalid XML: {exc}") from exc
    _strip_ns(root)
    issuer = root.find(".//issuerInfo")
    if issuer is None:
        raise Form144ParseError("missing issuerInfo")
    info = root.find(".//securitiesInformation")
    submission_type = (root.findtext(".//submissionType") or "144").strip()

    def text(node, path: str) -> str:
        return ((node.findtext(path) if node is not None else "") or "").strip()

    natures = tuple(
        t
        for n in root.findall(".//securitiesToBeSold")
        if (t := text(n, "natureOfAcquisitionTransaction"))
    )
    plans = tuple(d for n in root.iter("planAdoptionDates") if (d := _date(n.text))) + tuple(
        d for n in root.iter("planAdoptionDate") if (d := _date(n.text))
    )
    return Form144(
        issuer_cik=normalize_cik(text(issuer, "issuerCik")),
        issuer_name=text(issuer, "issuerName"),
        seller_name=text(issuer, "nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold"),
        seller_cik=normalize_cik(text(root, ".//filerCredentials/cik")),
        relationships=tuple(
            ROLE_CODES.get((n.text or "").strip(), (n.text or "").strip())
            for n in issuer.iter("relationshipToIssuer")
            if n.text
        ),
        security_class=text(info, "securitiesClassTitle"),
        units_to_sell=_num(text(info, "noOfUnitsSold")),
        market_value=_num(text(info, "aggregateMarketValue")),
        units_outstanding=_num(text(info, "noOfUnitsOutstanding")),
        approx_sale_date=_date(text(info, "approxSaleDate")),
        exchange=text(info, "securitiesExchangeName"),
        acquisition_nature=natures,
        plan_adoption_dates=plans,
        notice_date=_date(text(root, ".//noticeSignature/noticeDate")),
        is_amendment=submission_type.endswith("/A"),
    )
