"""Funds and other non-operating investment vehicles, kept out of the insider buy signals.

When a director of a closed-end fund buys fund shares, that is not the "insider
knows the business" bet `cluster_buy` and `big_officer_buy` look for: the fund's
price follows its portfolio, and its directors and adviser often buy as a matter of
policy. So these issuers are dropped from both rules, live and in the backtest.

How an issuer is recognized as a fund, from the SEC registry (submissions JSON):

1. Its SIC code is in `fund_sic_codes` (default 6722, open-end management
   investment offices, and 6726, unit investment trusts and closed-end management
   investment offices). 6798 (REITs) is NOT a fund: REITs are operating companies.
2. Or it has no SIC ("" or "0000", which is what registered funds usually carry:
   BNY Mellon Strategic Municipals and BNY Mellon Strategic Municipal Bond Fund both
   show "0000") and its recent filings include the periodic reports only registered
   investment companies file (N-CSR, NPORT-P, N-CEN...). Business development
   companies file 10-Q/10-K instead and stay in, as operating companies.
3. Or, when the registry gave no answer and the SIC is missing, the issuer name looks
   like a fund (a tight heuristic, see `looks_like_fund_name`).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from radar.config import SignalConfig
from radar.models import Signal
from radar.signals import BIG_OFFICER_BUY, CLUSTER_BUY

# Signal types the exclusion applies to: "insiders buying" means something else at a fund.
FUND_EXCLUDED_TYPES = frozenset({CLUSTER_BUY, BIG_OFFICER_BUY})

# SIC values that mean "no SIC assigned".
NO_SIC = frozenset({"", "0000"})

# Periodic reports filed only by registered investment companies (Investment Company
# Act of 1940). N-PX is left out on purpose: institutional managers file it too.
INVESTMENT_COMPANY_FORMS = frozenset(
    {
        "N-CSR",
        "N-CSRS",
        "N-CSR/A",
        "N-CSRS/A",
        "NPORT-P",
        "NPORT-P/A",
        "NPORT-EX",
        "N-CEN",
        "N-CEN/A",
        "N-Q",
        "N-30B-2",
        "N-30D",
        "N-23C3A",
    }
)

# Name heuristic (only used when the SIC is missing). Each pattern needs a fund word
# next to a word that says what the fund holds, so "Fundamental Global" or a plain
# "Holdings Trust" stay out.
_HOLDS = (
    r"municipals?|muni|income|bond|credit|dividend|equity|yield|total return|premium"
    r"|tax[- ]?(?:free|exempt|advantaged)|preferred|floating rate|loan|securities"
)
_FUND_DESCRIPTOR = (
    _HOLDS + r"|opportunit(?:y|ies)|strategic|global|infrastructure|treasury|government"
    r"|emerging markets?|allocation|closed[- ]end|interval|private|growth|value"
)
_GAP = r"(?:[\s,&-]+\w+){0,4}?[\s,&-]+"  # up to four words in between
_FUND_NAME = re.compile(
    rf"\b(?:{_FUND_DESCRIPTOR})\b{_GAP}funds?\b"  # "Municipal Income Fund", "Equity Fund"
    rf"|\b(?:{_HOLDS})\b{_GAP}trust\b"  # "Municipal Income Trust", "Credit Trust"
    r"|\bclosed[- ]end\b"
    r"|\binterval fund\b"
    r"|\bmunicipals\b",  # "Strategic Municipals, Inc." (plural: a fund, not a muni issuer)
    re.I,
)
# Operating companies whose names share fund words (REITs, royalty trusts, banks).
_NOT_FUND_NAME = re.compile(
    r"\b(?:realty|reit|real estate investment trust|properties|royalty|bancorp|bank|bancshares)\b",
    re.I,
)


def looks_like_fund_name(name: str | None) -> bool:
    """True for names that clearly belong to a fund ("Municipal Income Fund", "Credit Trust")."""
    if not name:
        return False
    text = " ".join(name.split())
    if _NOT_FUND_NAME.search(text):
        return False
    return bool(_FUND_NAME.search(text))


def files_as_investment_company(forms: Iterable[str]) -> bool:
    """True if any of the filer's recent forms is a registered-fund periodic report."""
    return any((form or "").strip().upper() in INVESTMENT_COMPANY_FORMS for form in forms)


def is_fund(
    name: str | None,
    sic: str | None,
    investment_company: bool | None,
    cfg: SignalConfig,
) -> bool:
    """Whether an issuer is a fund under `cfg` (see the module docstring for the order)."""
    if not cfg.exclude_funds:
        return False
    code = (sic or "").strip()
    if code in {str(c).strip() for c in cfg.fund_sic_codes}:
        return True
    if investment_company:
        return True
    if code not in NO_SIC:
        return False  # an operating company with a real SIC: the name does not matter
    return cfg.fund_name_heuristic and looks_like_fund_name(name)


@dataclass(frozen=True)
class IssuerProfile:
    """What the SEC registry says about an issuer: SIC code and fund-like filings."""

    sic: str
    investment_company: bool | None = None


ProfileOf = Callable[[str], IssuerProfile | None]
FundCheck = Callable[[str, str], bool]


class FundClassifier:
    """`(cik, name) -> bool`, asking `profile_of` once per CIK.

    `profile_of` returns None when the registry has no answer; then only the name
    heuristic decides. Without `profile_of`, only the name is used.
    """

    def __init__(self, cfg: SignalConfig, profile_of: ProfileOf | None = None):
        self.cfg = cfg
        self._profile_of = profile_of
        self._known: dict[str, bool] = {}

    def __call__(self, cik: str, name: str) -> bool:
        if not self.cfg.exclude_funds:
            return False
        key = (cik or "").lstrip("0")
        if key and key in self._known:
            return self._known[key]
        profile = self._profile_of(key) if self._profile_of and key else None
        verdict = is_fund(
            name,
            profile.sic if profile else None,
            profile.investment_company if profile else None,
            self.cfg,
        )
        if key and profile is not None:
            self._known[key] = verdict  # without a registry answer, ask again next time
        return verdict


def split_funds(
    signals: Iterable[Signal], is_fund_issuer: FundCheck | None
) -> tuple[list[Signal], list[Signal]]:
    """(kept, dropped): insider buy signals of funds go to `dropped`; the rest is kept."""
    kept: list[Signal] = []
    dropped: list[Signal] = []
    for signal in signals:
        if (
            is_fund_issuer is not None
            and signal.type in FUND_EXCLUDED_TYPES
            and is_fund_issuer(signal.issuer_cik, signal.issuer_name)
        ):
            dropped.append(signal)
        else:
            kept.append(signal)
    return kept, dropped
