"""Classifies the insider's position from the free-text title reported on Form 4."""

from __future__ import annotations

import re

_CEO = re.compile(r"\b(ceo|chief\s+executive(\s+officer)?|principal\s+executive\s+officer)\b", re.I)
_CFO = re.compile(r"\b(cfo|chief\s+financ\w*(\s+officer)?|principal\s+financial\s+officer)\b", re.I)
_FORMER = re.compile(r"\b(former|ex-|retired)", re.I)
_SEE_REMARKS = re.compile(r"see\s+remarks?", re.I)


def classify_title(title: str | None, remarks: str | None = None) -> tuple[bool, bool]:
    """Returns (is_ceo, is_cfo).

    The title is free text typed by the filer ("President & CEO",
    "Interim CFO", "See Remarks"...). When it points to the remarks, we look
    for the position there. Titles of former executives do not count.
    """
    text = (title or "").strip()
    if _SEE_REMARKS.search(text) and remarks:
        text = f"{text} {remarks[:300]}"
    if not text or _FORMER.search(text):
        return False, False
    return bool(_CEO.search(text)), bool(_CFO.search(text))
