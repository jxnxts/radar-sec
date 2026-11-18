"""Languages and message catalogs.

The radar speaks English by default and Brazilian Portuguese on request. Every
human-facing sentence lives in a per-language catalog (`radar.locales`); code
looks it up by key with `t(key, lang, **values)`. Stored data (database, replay
file, CSV) always uses English codes, and text is rendered from it on demand.
"""

from __future__ import annotations

from collections.abc import Callable

from radar.locales import en, pt_br

EN = "en"
PT_BR = "pt-BR"
LANGS: tuple[str, ...] = (EN, PT_BR)
DEFAULT_LANG = EN

CATALOGS: dict[str, dict[str, str]] = {EN: en.MESSAGES, PT_BR: pt_br.MESSAGES}

_ALIASES = {
    "en": EN,
    "en-us": EN,
    "en_us": EN,
    "english": EN,
    "pt": PT_BR,
    "pt-br": PT_BR,
    "pt_br": PT_BR,
}


def normalize_lang(value: str | None) -> str:
    """Canonical language code ("en-US" → "en", "pt_br" → "pt-BR").

    Raises ValueError for a language the radar does not speak.
    """
    if value is None or not str(value).strip():
        return DEFAULT_LANG
    key = str(value).strip().lower()
    if key in _ALIASES:
        return _ALIASES[key]
    raise ValueError(f"unsupported language '{value}' (use one of: {', '.join(LANGS)})")


def t(key: str, lang: str = DEFAULT_LANG, /, **values: object) -> str:
    """The message `key` in `lang`, formatted with `values`.

    A key missing from a catalog falls back to English; a key missing everywhere
    is returned as is, so a typo shows up on screen instead of crashing.
    """
    template = CATALOGS.get(lang, CATALOGS[EN]).get(key)
    if template is None:
        template = CATALOGS[EN].get(key, key)
    return template.format(**values) if values else template


def has(key: str, lang: str = DEFAULT_LANG) -> bool:
    return key in CATALOGS.get(lang, {})


def localized[T](render: Callable[[str], T]) -> dict[str, T]:
    """`{lang: render(lang)}` for every supported language (the API's localized maps)."""
    return {lang: render(lang) for lang in LANGS}


def role_label(role: str | None, lang: str = DEFAULT_LANG) -> str:
    """A role code ("Director", "10% owner"...) in `lang`; free-text titles pass through."""
    text = role or ""
    key = f"role.{text}"
    return t(key, lang) if has(key, EN) else text


def signal_label(signal_type: str, lang: str = DEFAULT_LANG) -> str:
    key = f"signal.{signal_type}"
    return t(key, lang) if has(key, EN) else signal_type
