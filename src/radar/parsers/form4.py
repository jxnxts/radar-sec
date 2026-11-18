"""Form 4 parser (`ownershipDocument` XML)."""

from __future__ import annotations

from datetime import date
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as ET

from radar.edgar import normalize_cik
from radar.models import Form4, Owner, Transaction


class Form4ParseError(ValueError):
    pass


def _text(node: Element | None, path: str) -> str:
    """Text of an element, accepting both `<x>v</x>` and `<x><value>v</value></x>`."""
    if node is None:
        return ""
    child = node.find(path)
    if child is None:
        return ""
    value = child.find("value")
    return ((value.text if value is not None else child.text) or "").strip()


def _flag(node: Element | None, path: str) -> bool:
    return _text(node, path).lower() in {"1", "true"}


def _number(text: str) -> float | None:
    try:
        return float(text.replace(",", "")) if text else None
    except ValueError:
        return None


def _date(text: str) -> date | None:
    # Some filings carry the date with a timezone suffix ("2024-05-01-05:00").
    try:
        return date.fromisoformat(text[:10]) if text else None
    except ValueError:
        return None


def parse_form4(xml: str | bytes) -> Form4:
    try:
        root = ET.fromstring(xml.strip() if isinstance(xml, str) else xml)
    except ET.ParseError as exc:
        raise Form4ParseError(f"invalid XML: {exc}") from exc
    if root.tag != "ownershipDocument":
        raise Form4ParseError(f"unexpected document: <{root.tag}>")

    issuer = root.find("issuer")
    owners: list[Owner] = []
    for node in root.findall("reportingOwner"):
        rel = node.find("reportingOwnerRelationship")
        owners.append(
            Owner(
                cik=normalize_cik(_text(node, "reportingOwnerId/rptOwnerCik")),
                name=_text(node, "reportingOwnerId/rptOwnerName"),
                is_director=_flag(rel, "isDirector"),
                is_officer=_flag(rel, "isOfficer"),
                is_ten_percent_owner=_flag(rel, "isTenPercentOwner"),
                is_other=_flag(rel, "isOther"),
                officer_title=_text(rel, "officerTitle"),
            )
        )

    transactions: list[Transaction] = []
    for node in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        transactions.append(
            Transaction(
                security_title=_text(node, "securityTitle"),
                date=_date(_text(node, "transactionDate")),
                code=_text(node, "transactionCoding/transactionCode").upper(),
                shares=_number(_text(node, "transactionAmounts/transactionShares")),
                price=_number(_text(node, "transactionAmounts/transactionPricePerShare")),
                acquired_disposed=_text(
                    node, "transactionAmounts/transactionAcquiredDisposedCode"
                ).upper(),
                shares_after=_number(
                    _text(node, "postTransactionAmounts/sharesOwnedFollowingTransaction")
                ),
                ownership=_text(node, "ownershipNature/directOrIndirectOwnership").upper(),
            )
        )

    footnotes = tuple(
        (fn.text or "").strip() for fn in root.findall("footnotes/footnote") if fn.text
    )

    return Form4(
        document_type=_text(root, "documentType"),
        issuer_cik=normalize_cik(_text(issuer, "issuerCik")),
        issuer_name=_text(issuer, "issuerName"),
        issuer_ticker=_text(issuer, "issuerTradingSymbol").upper(),
        period_of_report=_date(_text(root, "periodOfReport")),
        owners=tuple(owners),
        transactions=tuple(transactions),
        remarks=_text(root, "remarks"),
        footnotes=footnotes,
    )
