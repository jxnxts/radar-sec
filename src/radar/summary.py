"""Short signal summary: AI when available, a template whenever it fails.

The AI is only called for fired signals (never for every filing), at most once
per filing + signal type + language (cached in SQLite), and within an hourly cap
on calls, because the subscription has a quota.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from radar import ai, fmt
from radar.config import AIConfig
from radar.db import Database
from radar.i18n import DEFAULT_LANG, LANGS, role_label, signal_label, t
from radar.models import Signal
from radar.signals import ACTIVIST_13D, BIG_OFFICER_BUY, CLUSTER_BUY, explain

log = logging.getLogger(__name__)

MAX_CONTEXT_CHARS = 6000
AI = "ai"
TEMPLATE = "template"

Generator = Callable[..., str]


def template_summary(signal: Signal, lang: str = DEFAULT_LANG) -> str:
    """Deterministic 3-4 line summary, used without AI or when it fails."""
    d = signal.details
    name = signal.issuer_name + (f" ({signal.ticker})" if signal.ticker else "")
    filed = fmt.day(signal.signal_date, lang)

    if signal.type == CLUSTER_BUY:
        top = ", ".join(
            f"{i.get('name', '')} ({role_label(i.get('role'), lang)})"
            for i in d.get("insiders", [])[:3]
        )
        return "\n".join(
            [
                t("summary.cluster.who", lang, n=d.get("n_insiders"), name=name, top=top),
                t(
                    "summary.cluster.amount",
                    lang,
                    value=fmt.usd(d.get("total_value"), lang),
                    price=fmt.price(d.get("avg_price"), lang),
                ),
                t(
                    "summary.cluster.context",
                    lang,
                    first=fmt.iso_day(d.get("first_buy"), lang),
                    last=fmt.iso_day(d.get("last_buy"), lang),
                    filed=filed,
                ),
                t("summary.cluster.pattern", lang),
            ]
        )
    if signal.type == BIG_OFFICER_BUY:
        lines = [
            t(
                "summary.officer.who",
                lang,
                insider=role_label(d.get("insider"), lang),
                role=role_label(d.get("role"), lang),
                name=name,
            ),
            t(
                "summary.officer.amount",
                lang,
                value=fmt.usd(d.get("total_value"), lang),
                shares=fmt.number(d.get("shares"), lang=lang),
                price=fmt.price(d.get("avg_price"), lang),
            ),
            t(
                "summary.officer.context",
                lang,
                last=fmt.iso_day(d.get("last_buy"), lang),
                filed=filed,
            ),
        ]
        if d.get("stake_increase") is not None:
            lines.append(
                t("summary.officer.increase", lang, pct=fmt.pct(d["stake_increase"], lang=lang))
            )
        return "\n".join(lines)
    if signal.type == ACTIVIST_13D:
        shares = d.get("shares")
        lines = [
            t("summary.activist.who", lang, filer=role_label(d.get("filer"), lang), name=name),
            t(
                "summary.activist.amount",
                lang,
                pct=fmt.pct_points(d.get("percent"), lang=lang),
                shares=(
                    t("summary.activist.shares", lang, shares=fmt.number(shares, lang=lang))
                    if shares
                    else ""
                ),
            ),
            t(
                "summary.activist.context",
                lang,
                filed=filed,
                event=(
                    t("summary.activist.event", lang, day=fmt.iso_day(d["event_date"], lang))
                    if d.get("event_date")
                    else ""
                ),
            ),
        ]
        if d.get("activist_tone"):
            lines.append(t("summary.activist.tone", lang))
        return "\n".join(lines)
    return explain(signal, lang)


def localized_summaries(
    signal: Signal, cached_ai: dict[str, str] | None = None
) -> tuple[dict[str, str], dict[str, str]]:
    """`({lang: summary}, {lang: source})` for every language.

    A cached AI summary wins in its language; the other languages get the template.
    """
    cached_ai = cached_ai or {}
    texts: dict[str, str] = {}
    sources: dict[str, str] = {}
    for lang in LANGS:
        if cached_ai.get(lang):
            texts[lang], sources[lang] = cached_ai[lang], AI
        else:
            texts[lang], sources[lang] = template_summary(signal, lang), TEMPLATE
    return texts, sources


def build_prompt(signal: Signal, context: dict[str, Any] | None = None, lang: str = "en") -> str:
    """Builds the prompt: the rule that fired, the numbers and the relevant filing excerpt."""
    details = {k: v for k, v in signal.details.items() if k != "purpose"}
    filing_text = json.dumps(context, ensure_ascii=False, indent=1) if context else ""
    if purpose := signal.details.get("purpose"):
        filing_text += f"\n\n{t('prompt.purpose', lang)}\n{purpose}"
    filing_text = filing_text.strip()[:MAX_CONTEXT_CHARS]
    company = signal.issuer_name + (f" ({signal.ticker})" if signal.ticker else "")

    return t(
        "prompt.body",
        lang,
        label=signal_label(signal.type, lang),
        type=signal.type,
        company=company,
        date=signal.signal_date.isoformat(),
        score=signal.score,
        explanation=explain(signal, lang),
        numbers=json.dumps(details, ensure_ascii=False),
        filing=filing_text or t("prompt.no_text", lang),
    )


class Summarizer:
    """Fills `signal.summary` in the configured language: cache, AI or template."""

    def __init__(
        self,
        db: Database,
        config: AIConfig,
        *,
        lang: str = DEFAULT_LANG,
        generate: Generator = ai.generate,
    ):
        self.db = db
        self.config = config
        self.lang = lang
        self._generate = generate
        self._cap_warned = False

    def summarize(self, signal: Signal, context: dict[str, Any] | None = None) -> Signal:
        signal.summary, signal.summary_source = self._resolve(signal, context)
        return signal

    def stored(self, signal: Signal) -> tuple[str, str]:
        """The English summary kept in `signals.summary`: a cached AI text or the template.

        Never calls the AI: other languages are rendered on demand by the API.
        """
        cached = self.db.cached_ai_summary(signal.trigger_accession, signal.type, "en")
        if cached:
            return cached, AI
        return template_summary(signal, "en"), TEMPLATE

    def _resolve(self, signal: Signal, context: dict[str, Any] | None) -> tuple[str, str]:
        fallback = (template_summary(signal, self.lang), TEMPLATE)
        if not self.config.enabled:
            return fallback

        cached = self.db.cached_ai_summary(signal.trigger_accession, signal.type, self.lang)
        if cached:
            return cached, AI

        used = self.db.ai_calls_last_hour()
        if used >= self.config.max_calls_per_hour:
            if not self._cap_warned:  # one warning per run is enough
                log.warning(
                    "AI: hourly cap of %d calls reached; using the template summary",
                    self.config.max_calls_per_hour,
                )
                self._cap_warned = True
            return fallback

        try:
            text = self._generate(
                build_prompt(signal, context, self.lang),
                model=self.config.model,
                timeout=self.config.timeout_seconds,
                system_prompt=ai.system_prompt(self.lang),
            )
        except ai.AIError as exc:
            self.db.record_ai_call(ok=False)
            log.warning("AI unavailable (%s); using the template summary", exc)
            return fallback
        except Exception as exc:  # extra safety: the AI must never break the system
            self.db.record_ai_call(ok=False)
            log.warning("AI failed unexpectedly (%r); using the template summary", exc)
            return fallback

        self.db.record_ai_call(ok=True)
        self.db.store_ai_summary(
            signal.trigger_accession, signal.type, self.config.model, text, self.lang
        )
        return text, AI
