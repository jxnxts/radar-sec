"""Locale-aware formatting of numbers, money and dates.

English (`en`) follows US conventions: "$2.22M", "1,234.5", "12.3%", "Nov 18, 2026".
Brazilian Portuguese (`pt-BR`) swaps the separators and uses Brazilian units:
"US$ 2,22 mi", "1.234,5", "12,3%", "18/11/2026".
"""

from __future__ import annotations

from datetime import date

from radar.i18n import DEFAULT_LANG, PT_BR

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# Units for large amounts: (scale, en suffix, pt-BR suffix).
_SCALES = ((1e9, "B", " bi"), (1e6, "M", " mi"))


def _localize(number: str, lang: str) -> str:
    """Turns a US-formatted number into the locale's (1,234.5 → 1.234,5 in pt-BR)."""
    if lang != PT_BR:
        return number
    return number.replace(",", "§").replace(".", ",").replace("§", ".")


def na(lang: str = DEFAULT_LANG) -> str:
    """Placeholder for a missing value."""
    return "n/d" if lang == PT_BR else "n/a"


def _money(amount: str, lang: str, negative: bool = False) -> str:
    if lang == PT_BR:
        return f"US$ {'-' if negative else ''}{amount}"
    return f"{'-' if negative else ''}${amount}"


def usd(value: float | None, lang: str = DEFAULT_LANG) -> str:
    """Compact dollar amount: "$2.22M" / "US$ 2,22 mi"."""
    if value is None:
        return na(lang)
    magnitude = abs(value)
    negative = value < 0
    for scale, en_unit, pt_unit in _SCALES:
        if magnitude >= scale:
            scaled = magnitude / scale
            # Round amounts drop the decimals: "$300M", not "$300.00M".
            digits = 0 if abs(scaled - round(scaled)) < 0.005 else 2
            amount = _localize(f"{scaled:,.{digits}f}", lang)
            unit = pt_unit if lang == PT_BR else en_unit
            return _money(amount + unit, lang, negative)
    if magnitude >= 1e3:
        amount = _localize(f"{magnitude / 1e3:,.0f}", lang)
        return _money(amount + (" mil" if lang == PT_BR else "K"), lang, negative)
    return _money(_localize(f"{magnitude:,.2f}", lang), lang, negative)


def price(value: float | None, lang: str = DEFAULT_LANG) -> str:
    """Share price with cents: "$11.44" / "US$ 11,44"."""
    if value is None:
        return na(lang)
    return _money(_localize(f"{abs(value):,.2f}", lang), lang, value < 0)


def number(value: float | None, decimals: int = 0, lang: str = DEFAULT_LANG) -> str:
    return na(lang) if value is None else _localize(f"{value:,.{decimals}f}", lang)


def pct(
    value: float | None, decimals: int = 1, *, signed: bool = False, lang: str = DEFAULT_LANG
) -> str:
    """Formats a fraction (0.123 → "12.3%" / "12,3%")."""
    if value is None or value != value:  # None or NaN
        return na(lang)
    sign = "+" if signed else ""
    return _localize(f"{value * 100:{sign},.{decimals}f}", lang) + "%"


def pct_points(value: float | None, decimals: int = 2, lang: str = DEFAULT_LANG) -> str:
    """Formats a number already in percentage points (9.99 → "9.99%" / "9,99%")."""
    return na(lang) if value is None else _localize(f"{value:,.{decimals}f}", lang) + "%"


def day(value: date | None, lang: str = DEFAULT_LANG) -> str:
    """A calendar day: "Nov 18, 2026" / "18/11/2026"."""
    if not value:
        return na(lang)
    if lang == PT_BR:
        return value.strftime("%d/%m/%Y")
    return f"{_MONTHS[value.month - 1]} {value.day}, {value.year}"


def iso_day(value: str | None, lang: str = DEFAULT_LANG) -> str:
    """Like `day`, for an ISO date string ("2026-11-18"); missing → "n/a"."""
    return day(date.fromisoformat(value), lang) if value else na(lang)
