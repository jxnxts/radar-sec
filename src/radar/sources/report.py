"""Report of the new-signals backtest, in Markdown, in every language the radar speaks.

Numbers, tables and the verdict come from the measured frame; every sentence comes
from the catalogs (`sources.report.*` keys in `radar/locales/sources_*.py`).
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from radar import fmt
from radar.backtest.returns import OK
from radar.i18n import DEFAULT_LANG, EN, signal_label, t

from . import evaluate as ev
from .base import LONG
from .specs import FORM144_HALVES, FORM144_PERIOD, SPECS, TESTED


def report_name(stamp: str, lang: str = DEFAULT_LANG) -> str:
    return f"new-signals-{stamp}.md" if lang == EN else f"new-signals-{stamp}.{lang}.md"


class _Text:
    def __init__(self, lang: str):
        self.lang = lang

    def __call__(self, key: str, **values: object) -> str:
        return t(f"sources.report.{key}", self.lang, **values)

    def p(self, value, signed: bool = True) -> str:
        if value is None or pd.isna(value):
            return fmt.na(self.lang)
        return fmt.pct(value, 1, signed=signed, lang=self.lang)

    def n(self, value) -> str:
        return fmt.number(value, lang=self.lang)

    def tv(self, value) -> str:
        if value is None or pd.isna(value):
            return fmt.na(self.lang)
        return fmt.number(value, 1, lang=self.lang)

    def table(self, headers: list[str], rows: list[list[str]]) -> str:
        if not rows:
            return self("no_data")
        out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
        out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
        return "\n".join(out)


def verdict_of(
    kind: str, ok: pd.DataFrame, benchmark: str = "spy"
) -> tuple[ev.Verdict, dict, dict | None]:
    """The pre-registered verdict of one signal (primary horizon, test period)."""
    spec = SPECS[kind]
    group = ok[ok["type"] == kind]
    months = spec.primary_months or 3
    if spec.source == "form144":
        whole = ev.horizon_stats(ev.in_period(group, FORM144_PERIOD), months, benchmark)
        return ev.verdict(spec.direction, whole, None), whole, None
    test = ev.horizon_stats(ev.in_period(group, ev.TEST), months, benchmark)
    train = ev.horizon_stats(ev.in_period(group, ev.TRAIN), months, benchmark)
    return ev.verdict(spec.direction, test, train), test, train


def _hypothesis(tx: _Text, kind: str) -> str:
    return tx("long") if SPECS[kind].direction == LONG else tx("avoid")


def _verdict_label(tx: _Text, v: ev.Verdict) -> str:
    return tx(f"verdict.{v.code}")


def _verdict_reason(tx: _Text, v: ev.Verdict) -> str:
    return tx(f"reason.{v.reason_key}", **v.values)


def _verdict_rows(tx: _Text, ok: pd.DataFrame) -> list[list[str]]:
    rows = []
    for kind in TESTED:
        spec = SPECS[kind]
        v, test, train = verdict_of(kind, ok)
        _, iwm, _ = verdict_of(kind, ok, "iwm")
        rows.append(
            [
                f"`{kind}`",
                _hypothesis(tx, kind),
                tx("months", n=spec.primary_months),
                tx.n(test.get("n", 0)),
                tx.p(test.get("exc_mean")),
                tx.p(test.get("exc_median")),
                tx.p(test.get("beats"), signed=False),
                tx.tv(test.get("t_cohort")),
                tx.p(train.get("exc_mean")) if train else "—",
                tx.p(iwm.get("exc_mean")),
                tx.p(iwm.get("exc_median")),
                f"**{_verdict_label(tx, v)}**",
            ]
        )
    return rows


def _verdict_headers(tx: _Text) -> list[str]:
    return [
        tx(f"col.{c}")
        for c in (
            "signal",
            "hypothesis",
            "primary",
            "n_test",
            "exc_mean",
            "exc_median",
            "beats_spy",
            "t",
            "train_mean",
            "iwm_mean",
            "iwm_median",
            "verdict",
        )
    ]


def _periods(tx: _Text, kind: str) -> list[tuple[str, tuple[date, date]]]:
    if SPECS[kind].source == "form144":
        return [
            (tx("period.f144_first"), FORM144_HALVES[0]),
            (tx("period.f144_second"), FORM144_HALVES[1]),
            (tx("period.f144_all"), FORM144_PERIOD),
        ]
    return [
        (tx("period.train"), ev.TRAIN),
        (tx("period.test"), ev.TEST),
        (tx("period.all"), (ev.TRAIN[0], ev.TEST[1])),
    ]


def _signal_section(tx: _Text, kind: str, measured: pd.DataFrame) -> list[str]:
    spec = SPECS[kind]
    group = measured[measured["type"] == kind]
    group_ok = group[group["status"] == OK]
    lines = [
        f"## `{kind}` — {signal_label(kind, tx.lang)}",
        "",
        tx(
            "rule_line",
            rule=t(f"sources.rule.{kind}", tx.lang),
            hypothesis=tx("hyp_long") if spec.direction == LONG else tx("hyp_avoid"),
            months=spec.primary_months,
        ),
        "",
    ]
    headers_base = [
        "period",
        "horizon",
        "n",
        "hit",
        "beats",
        "net_mean",
        "exc_mean",
        "exc_median",
        "exc_winsor",
        "t",
    ]
    for bench in ("spy", "iwm"):
        rows = []
        for label, period in _periods(tx, kind):
            sub = ev.in_period(group_ok, period)
            for months in ev.HORIZONS:
                st = ev.horizon_stats(sub, months, bench)
                if not st.get("n"):
                    rows.append([label, tx("months", n=months), "0"] + ["—"] * 7)
                    continue
                rows.append(
                    [
                        label,
                        tx("months", n=months),
                        tx.n(st["n"]),
                        tx.p(st["hit"], False),
                        tx.p(st["beats"], False),
                        tx.p(st["mean"]),
                        f"**{tx.p(st['exc_mean'])}**",
                        f"**{tx.p(st['exc_median'])}**",
                        tx.p(st["exc_winsor"]),
                        tx.tv(st["t_cohort"]),
                    ]
                )
        name = bench.upper()
        headers = [tx(f"col.{h}", name=name) for h in headers_base]
        lines += [tx("against", name=name), "", tx.table(headers, rows), ""]

    test_period = FORM144_PERIOD if spec.source == "form144" else ev.TEST
    liquid = ev.in_period(ev.liquid(group_ok), test_period)
    liq_rows = []
    for months in ev.HORIZONS:
        st = ev.horizon_stats(liquid, months)
        if st.get("n"):
            liq_rows.append(
                [
                    tx("months", n=months),
                    tx.n(st["n"]),
                    tx.p(st["beats"], False),
                    tx.p(st["exc_mean"]),
                    tx.p(st["exc_median"]),
                    tx.tv(st["t_cohort"]),
                ]
            )
    lines += [
        tx("liquid_line"),
        "",
        tx.table(
            [
                tx(f"col.{h}", name="SPY")
                for h in ("horizon", "n", "beats", "exc_mean", "exc_median", "t")
            ],
            liq_rows,
        ),
        "",
    ]

    total = len(group)
    if total:
        counts = group["status"].value_counts()
        parts = [
            f"{t(f'sources.status.{status}', tx.lang)} {tx.n(n)} ({tx.p(n / total, False)})"
            for status, n in counts.items()
        ]
        lines += [tx("funnel_line", parts="; ".join(parts), n=tx.n(total)), ""]

    months = spec.primary_months or 3
    year_rows = []
    for year, sub in group_ok.groupby("year"):
        st = ev.horizon_stats(sub, months)
        if st.get("n"):
            year_rows.append(
                [str(year), tx.n(st["n"]), tx.p(st["exc_mean"]), tx.p(st["exc_median"])]
            )
    lines += [
        tx("by_year", months=months),
        "",
        tx.table(
            [tx("col.year"), tx("col.n"), tx("col.exc_mean"), tx("col.exc_median")], year_rows
        ),
        "",
    ]
    return lines


def _data_quality(tx: _Text, ok: pd.DataFrame) -> list[str]:
    price = pd.to_numeric(ok["entry_raw_price"], errors="coerce")
    rows = []
    for kind in TESTED:
        group = ok["type"] == kind
        n = int(group.sum())
        if not n:
            continue
        cents = int((group & (price < 0.01)).sum())
        dollar = int((group & (price < 1.0)).sum())
        rows.append(
            [
                f"`{kind}`",
                tx.n(n),
                f"{tx.n(cents)} ({tx.p(cents / n, False)})",
                f"{tx.n(dollar)} ({tx.p(dollar / n, False)})",
            ]
        )
    return [
        f"### {tx('h.quality')}",
        "",
        tx("quality_text"),
        "",
        tx.table(
            [tx("col.signal"), tx("col.measured"), tx("col.sub_penny"), tx("col.under_dollar")],
            rows,
        ),
        "",
    ]


def render(
    measured: pd.DataFrame,
    funnel: dict[str, dict],
    start: date,
    end: date,
    generated: datetime,
    lang: str = DEFAULT_LANG,
) -> str:
    tx = _Text(lang)
    ok = measured[measured["status"] == OK]
    lines = [
        f"# {tx('title', start=start.isoformat(), end=end.isoformat())}",
        "",
        tx("generated", when=generated.strftime("%Y-%m-%d %H:%M")),
        "",
        f"## {tx('h.verdict')}",
        "",
        tx("verdict_intro"),
        "",
        tx.table(_verdict_headers(tx), _verdict_rows(tx, ok)),
        "",
    ]
    for kind in TESTED:
        v, _, _ = verdict_of(kind, ok)
        lines.append(f"- `{kind}`: **{_verdict_label(tx, v)}** — {_verdict_reason(tx, v)}.")
    lines += [
        "",
        tx("how_to_read"),
        "",
        f"> {tx('survivorship')}",
        "",
        f"### {tx('h.liquid')}",
        "",
        tx("liquid_intro"),
        "",
        tx.table(_verdict_headers(tx), _verdict_rows(tx, ev.liquid(ok))),
        "",
        *_data_quality(tx, ok),
    ]
    for kind in TESTED:
        lines += _signal_section(tx, kind, measured)
    if funnel:
        lines += [f"## {tx('h.funnel')}", ""]
        for source, info in funnel.items():
            items = ", ".join(
                f"{key} {tx.n(value) if isinstance(value, int) else value}"
                for key, value in info.items()
            )
            lines.append(f"- **{source}**: {items}")
        lines.append("")
    lines += [f"## {tx('h.limitations')}", ""]
    lines += [f"{i}. {tx(f'limitation.{i}')}" for i in range(1, 9)]
    lines.append("")
    return "\n".join(lines)
