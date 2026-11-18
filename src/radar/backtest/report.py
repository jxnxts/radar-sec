"""Backtest report in Markdown, in English or Brazilian Portuguese.

Every sentence comes from the message catalogs (`report.*` keys) and every
number goes through the locale-aware `fmt`, so both languages carry exactly the
same figures. The verdict text is generated from the numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd

from radar import fmt
from radar.backtest.datasets import LoadStats
from radar.backtest.metrics import (
    BEATS,
    CONCENTRATED,
    NO_DATA,
    WEAK,
    horizon_stats,
    summarize,
    verdict_for,
)
from radar.backtest.returns import (
    NO_ENTRY,
    NO_PRICES,
    NO_TICKER,
    OK,
    PRICE_MISMATCH,
    STATUSES,
    SUSPECT_JUMP,
)
from radar.config import Settings
from radar.i18n import DEFAULT_LANG, PT_BR, t
from radar.signals import BIG_OFFICER_BUY, CLUSTER_BUY

DASH = "—"


@dataclass
class ReportContext:
    start: date
    end: date
    settings: Settings
    load: LoadStats
    quarters: list[tuple[int, int]]  # (year, quarter) of each dataset read
    signals: pd.DataFrame  # every signal, measured or not
    price_failures: int = 0
    generated_at: datetime | None = None
    csv_name: str = ""


def report_name(stamp: str, lang: str = DEFAULT_LANG) -> str:
    """File name of the report: `backtest-<stamp>.md` (English) or `.pt-BR.md`."""
    return f"backtest-{stamp}.md" if lang == DEFAULT_LANG else f"backtest-{stamp}.{lang}.md"


def quarter_label(quarter: tuple[int, int], lang: str = DEFAULT_LANG) -> str:
    year, q = quarter
    return t("report.quarter", lang, year=year, q=q)


def generated_label(moment: datetime, lang: str = DEFAULT_LANG) -> str:
    return moment.strftime("%d/%m/%Y %H:%M" if lang == PT_BR else "%Y-%m-%d %H:%M")


class _Text:
    """Shortcuts bound to one language."""

    def __init__(self, lang: str):
        self.lang = lang

    def __call__(self, key: str, **values: object) -> str:
        return t(f"report.{key}", self.lang, **values)

    def p(self, value: float | None, signed: bool = True) -> str:
        return fmt.pct(value, 1, signed=signed, lang=self.lang)

    def pct(self, value: float | None, decimals: int = 1) -> str:
        return fmt.pct(value, decimals, lang=self.lang)

    def n(self, value: float | None, decimals: int = 0) -> str:
        return fmt.number(value, decimals, lang=self.lang)

    def t_value(self, value: float | None) -> str:
        if value is None or value != value:
            return fmt.na(self.lang)
        return fmt.number(value, 1, lang=self.lang)

    def usd(self, value: float | None) -> str:
        return fmt.usd(value, self.lang)

    def price(self, value: float | None) -> str:
        return fmt.price(value, self.lang)

    def table(self, headers: list[str], rows: list[list[str]]) -> str:
        if not rows:
            return self("no_data")
        out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
        out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
        return "\n".join(out)


def _stats_table(tx: _Text, frame: pd.DataFrame, horizons: tuple[int, ...], bench: str) -> str:
    name = bench.upper()
    rows = []
    for row in summarize(frame, horizons, bench).to_dict("records"):
        if not row.get("n"):
            rows.append([row["type"], f"{row['horizon']}m", "0"] + [DASH] * 12)
            continue
        rows.append(
            [
                row["type"],
                f"{row['horizon']}m",
                tx.n(row["n"]),
                tx.p(row["hit_rate"], signed=False),
                tx.p(row["beats"], signed=False),
                tx.p(row["mean"]),
                tx.p(row["median"]),
                tx.p(row["std"], signed=False),
                tx.p(row["worst"]),
                tx.p(row["best"]),
                tx.p(row["bench_mean"]),
                f"**{tx.p(row['excess_mean'])}**",
                f"**{tx.p(row['excess_median'])}**",
                tx.p(row["excess_winsor"]),
                tx.t_value(row["t_cohort"]),
            ]
        )
    return tx.table(
        [
            tx("col.signal"),
            tx("col.horizon"),
            "N",
            tx("col.hit_rate"),
            tx("col.beats", name=name),
            tx("col.mean_return"),
            tx("col.median"),
            tx("col.std"),
            tx("col.worst"),
            tx("col.best"),
            tx("col.bench_mean", name=name),
            tx("col.excess_mean"),
            tx("col.excess_median"),
            tx("col.excess_winsor"),
            tx("col.t_cohort"),
        ],
        rows,
    )


def _short_table(tx: _Text, frame: pd.DataFrame, horizons: tuple[int, ...], bench: str) -> str:
    name = bench.upper()
    rows = []
    for row in summarize(frame, horizons, bench).to_dict("records"):
        if not row.get("n"):
            rows.append([row["type"], f"{row['horizon']}m", "0"] + [DASH] * 5)
            continue
        rows.append(
            [
                row["type"],
                f"{row['horizon']}m",
                tx.n(row["n"]),
                tx.p(row["hit_rate"], signed=False),
                tx.p(row["beats"], signed=False),
                tx.p(row["mean"]),
                f"**{tx.p(row['excess_mean'])}**",
                f"**{tx.p(row['excess_median'])}**",
            ]
        )
    return tx.table(
        [
            tx("col.signal"),
            tx("col.horizon"),
            "N",
            tx("col.hit_rate"),
            tx("col.beats", name=name),
            tx("col.mean_return"),
            tx("col.excess_mean_vs", name=name),
            tx("col.excess_median_vs", name=name),
        ],
        rows,
    )


def build_verdict(
    measured: pd.DataFrame,
    horizons: tuple[int, ...],
    benchmark: str,
    lang: str = DEFAULT_LANG,
) -> list[str]:
    """Verdict sentences, one per signal and horizon, plus the overall conclusion."""
    tx = _Text(lang)
    name = benchmark.upper()
    lines: list[str] = []
    codes: list[str] = []
    medians: list[float] = []
    for signal in (CLUSTER_BUY, BIG_OFFICER_BUY):
        group = measured[measured["type"] == signal]
        for months in horizons:
            stats = horizon_stats(group, months, benchmark) if len(group) else {"n": 0}
            code = verdict_for(stats)
            codes.append(code)
            if not stats.get("n"):
                lines.append(tx("verdict.line_empty", signal=signal, months=months))
                continue
            phrase = tx(f"verdict.{code}", name=name, t=tx.t_value(stats["t_cohort"]))
            medians.append(stats["excess_median"])
            lines.append(
                tx(
                    "verdict.line",
                    signal=signal,
                    months=months,
                    n=tx.n(stats["n"]),
                    mean=tx.p(stats["excess_mean"]),
                    median=tx.p(stats["excess_median"]),
                    name=name,
                    beats=tx.p(stats["beats"], signed=False),
                    phrase=phrase[0].upper() + phrase[1:],
                )
            )

    if not codes or all(c == NO_DATA for c in codes):
        headline = tx("headline.no_data")
    elif any(c == BEATS for c in codes):
        wins = sum(c == BEATS for c in codes)
        headline = tx("headline.beats", name=name, wins=wins, total=len(codes))
    elif any(c == WEAK for c in codes):
        headline = tx("headline.weak", name=name)
    elif any(c == CONCENTRATED for c in codes):
        typical = tx(
            "headline.typical_loses" if all(m <= 0 for m in medians) else "headline.never_both"
        )
        headline = tx("headline.concentrated", name=name, typical=typical)
    else:
        headline = tx("headline.no_beat", name=name)
    return [headline, "", *lines]


def render_report(ctx: ReportContext, lang: str = DEFAULT_LANG) -> str:
    tx = _Text(lang)
    cfg = ctx.settings
    bt, sig = cfg.backtest, cfg.signals
    horizons = bt.horizons_months
    bench = bt.benchmark.lower()
    name = bt.benchmark.upper()
    signals = ctx.signals
    measured = signals[signals["status"] == OK]
    generated = generated_label(ctx.generated_at or datetime.now(), lang)
    longest = max(horizons)

    out: list[str] = [
        "# " + tx("title", start=ctx.start.isoformat(), end=ctx.end.isoformat()),
        "",
        tx(
            "generated",
            generated=generated,
            first=quarter_label(ctx.quarters[0], lang),
            last=quarter_label(ctx.quarters[-1], lang),
        ),
        "",
        "## " + tx("h.verdict"),
        "",
        *build_verdict(measured, horizons, bench, lang),
        "",
        "> " + tx("caveat"),
        "",
        "## " + tx("h.how_to_read"),
        "",
        tx("how.return", cost=tx.pct(bt.cost_roundtrip, 1)),
        tx("how.excess", name=name),
        tx("how.hit_rate", name=name),
        tx("how.median"),
        tx("how.winsor"),
        tx("how.t"),
        "",
        "## " + tx("h.rules"),
        "",
        tx(
            "rules.cluster",
            min=sig.cluster_min_insiders,
            days=sig.cluster_window_days,
            value=tx.usd(sig.cluster_min_value),
        ),
        tx("rules.officer", value=tx.usd(sig.officer_min_value)),
        tx("rules.cooldown", days=sig.cooldown_days),
        tx("rules.dating"),
        tx("rules.activist"),
        tx("rules.amendments"),
        "",
        "## " + tx("h.funnel"),
        "",
        _funnel(tx, ctx),
        "",
        "## " + tx("h.results"),
        "",
        tx("results.intro"),
        "",
        _stats_table(tx, measured, horizons, bench),
        "",
    ]

    for extra in bt.extra_benchmarks:
        out += [
            "## " + tx("h.against", name=extra.upper()),
            "",
            tx("against.intro", bench=name, name=extra.upper()),
            "",
            _short_table(tx, measured, horizons, extra.lower()),
            "",
        ]

    liquid = measured[measured["avg_buy_price"] >= bt.min_price]
    with_cap = measured[measured["market_cap"].notna()]
    large = with_cap[
        (with_cap["avg_buy_price"] >= bt.min_price) & (with_cap["market_cap"] >= bt.min_market_cap)
    ]
    coverage = len(with_cap) / len(measured) if len(measured) else 0.0
    out += [
        "## " + tx("h.liquidity"),
        "",
        tx("liquidity.intro"),
        "",
        "### " + tx("h.liquid_price", price=tx.price(bt.min_price)),
        "",
        tx("liquid_price.count", n=tx.n(len(liquid)), total=tx.n(len(measured))),
        "",
        _short_table(tx, liquid, horizons, bench),
        "",
        "### " + tx("h.liquid_cap", price=tx.price(bt.min_price), cap=tx.usd(bt.min_market_cap)),
        "",
        tx("liquid_cap.intro", coverage=tx.pct(coverage, 0), n=tx.n(len(large))),
        "",
        _short_table(tx, large, horizons, bench),
        "",
        "### " + tx("h.officers_directors"),
        "",
        tx("officers_directors.intro", min=sig.cluster_min_insiders),
        "",
        _short_table(
            tx,
            measured[
                (measured["type"] == CLUSTER_BUY)
                & (measured["n_officer_director"] >= sig.cluster_min_insiders)
            ],
            horizons,
            bench,
        ),
        "",
        "## " + tx("h.by_year"),
        "",
        "### " + tx("h.year_counts"),
        "",
        _per_year_counts(tx, signals),
        "",
        "### " + tx("h.year_excess", name=name),
        "",
        _per_year_excess(tx, measured, horizons, bench),
        "",
        "## " + tx("h.score"),
        "",
        tx("score.intro"),
        "",
        _score_table(tx, measured, horizons, bench),
        "",
        "## " + tx("h.extremes"),
        "",
        tx("extremes.intro", months=longest),
        "",
        _extremes_table(tx, measured, longest),
        "",
        "## " + tx("h.limitations"),
        "",
        *_limitations(tx, ctx, measured, coverage),
        "",
        "## " + tx("h.files"),
        "",
        tx("files.csv", csv=ctx.csv_name),
        tx("files.redo", start=ctx.start.isoformat(), end=ctx.end.isoformat()),
        "",
    ]
    return "\n".join(out)


def _funnel(tx: _Text, ctx: ReportContext) -> str:
    signals = ctx.signals
    load = ctx.load
    rows = [
        [tx("funnel.form4"), tx.n(load.form4_filings)],
        [tx("funnel.buy_rows"), tx.n(load.purchase_rows)],
        [tx("funnel.non_common"), tx.n(load.excluded_non_common)],
        [tx("funnel.bad_dates"), tx.n(load.excluded_bad_dates)],
        [tx("funnel.valid"), tx.n(load.purchase_filings)],
    ]
    table = tx.table([tx("col.step"), tx("col.count")], rows)

    by_type = []
    for signal in (CLUSTER_BUY, BIG_OFFICER_BUY):
        group = signals[signals["type"] == signal]
        total = len(group)
        row = [signal, tx.n(total)]
        for status in (OK, NO_TICKER, NO_PRICES, NO_ENTRY, PRICE_MISMATCH, SUSPECT_JUMP):
            count = int((group["status"] == status).sum())
            share = f" ({tx.pct(count / total, 0)})" if total else ""
            row.append(f"{tx.n(count)}{share}")
        by_type.append(row)
    status_table = tx.table(
        [
            tx("col.signal"),
            tx("col.generated"),
            tx("col.measured"),
            tx("col.no_ticker"),
            tx("col.no_prices"),
            tx("col.no_entry_price"),
            tx("col.price_mismatch"),
            tx("col.suspect_jump"),
        ],
        by_type,
    )
    legend = "\n".join(f"- **{tx(f'status.{status}')}**" for status in STATUSES if status != OK)
    jumps = signals[signals["status"] == SUSPECT_JUMP]
    jump_note = ""
    if len(jumps):
        listed = ", ".join(
            f"{row.ticker} ({row.signal_date}, {tx.n(row.suspect_jump, 0)}x)"
            for row in jumps.itertuples(index=False)
        )
        jump_note = "\n\n" + tx("funnel.jumps", listed=listed)
    return f"{table}\n\n{status_table}\n\n{tx('funnel.reasons')}\n\n{legend}{jump_note}"


def _per_year_counts(tx: _Text, signals: pd.DataFrame) -> str:
    if signals.empty:
        return tx("no_data")
    years = sorted(signals["year"].unique())
    rows = []
    for signal in (CLUSTER_BUY, BIG_OFFICER_BUY):
        group = signals[signals["type"] == signal]
        subsets = ((tx("generated_row"), group), (tx("measured_row"), group[group["status"] == OK]))
        for label, subset in subsets:
            counts = subset.groupby("year").size()
            rows.append(
                [signal, label] + [tx.n(int(counts.get(y, 0))) for y in years] + [tx.n(len(subset))]
            )
    return tx.table([tx("col.signal"), "", *[str(y) for y in years], tx("col.total")], rows)


def _per_year_excess(
    tx: _Text, measured: pd.DataFrame, horizons: tuple[int, ...], bench: str
) -> str:
    if measured.empty:
        return tx("no_data")
    headers = [tx("col.signal"), tx("col.year"), "N"]
    for months in horizons:
        headers += [tx("col.mean_m", months=months), tx("col.median_m", months=months)]
    rows = []
    for signal in (CLUSTER_BUY, BIG_OFFICER_BUY):
        group = measured[measured["type"] == signal]
        for year, subset in group.groupby("year", sort=True):
            row = [signal, str(year), tx.n(len(subset))]
            for months in horizons:
                excess = subset[f"excess_{bench}_{months}m"].dropna()
                row += [tx.p(excess.mean()), tx.p(excess.median())] if len(excess) else [DASH] * 2
            rows.append(row)
    return tx.table(headers, rows)


def _score_table(tx: _Text, measured: pd.DataFrame, horizons: tuple[int, ...], bench: str) -> str:
    headers = [tx("col.signal"), tx("col.score_band"), "N"]
    for months in horizons:
        headers += [tx("col.excess_mean_m", months=months), tx("col.median_m", months=months)]
    bands = ("low", "mid", "high")
    rows = []
    for signal in (CLUSTER_BUY, BIG_OFFICER_BUY):
        group = measured[measured["type"] == signal]
        if len(group) < 30:
            continue
        ranks = group["score"].rank(method="first")
        band_of = pd.qcut(ranks, 3, labels=list(bands))
        for band in bands:
            subset = group[band_of == band]
            low, high = subset["score"].min(), subset["score"].max()
            label = f"{tx(f'band.{band}')} ({tx.n(low)}–{tx.n(high)})"
            row = [signal, label, tx.n(len(subset))]
            for months in horizons:
                excess = subset[f"excess_{bench}_{months}m"].dropna()
                row += [tx.p(excess.mean()), tx.p(excess.median())] if len(excess) else [DASH] * 2
            rows.append(row)
    return tx.table(headers, rows)


def _extremes_table(tx: _Text, measured: pd.DataFrame, months: int, count: int = 5) -> str:
    column = f"ret_{months}m"
    rows = []
    for signal in (CLUSTER_BUY, BIG_OFFICER_BUY):
        group = measured[(measured["type"] == signal) & measured[column].notna()]
        ranked = group.sort_values(column, ascending=False)
        for label, subset in ((tx("best"), ranked.head(count)), (tx("worst"), ranked.tail(count))):
            for row in subset.itertuples(index=False):
                rows.append(
                    [
                        signal,
                        label,
                        row.ticker,
                        str(row.issuer)[:40],
                        str(row.signal_date),
                        tx.price(row.avg_buy_price),
                        tx.usd(row.total_value),
                        tx.p(getattr(row, column)),
                    ]
                )
    return tx.table(
        [
            tx("col.signal"),
            "",
            "Ticker",
            tx("col.company"),
            tx("col.signal_date"),
            tx("col.price_paid"),
            tx("col.amount_bought"),
            tx("col.return_m", months=months),
        ],
        rows,
    )


def _limitations(
    tx: _Text, ctx: ReportContext, measured: pd.DataFrame, coverage: float
) -> list[str]:
    signals = ctx.signals
    bt = ctx.settings.backtest
    total = len(signals)

    def count(status: str) -> str:
        return tx.n(int((signals["status"] == status).sum()))

    dropped = total - len(measured)
    share = tx.pct(dropped / total, 0) if total else fmt.na(tx.lang)
    missing_exit = {
        months: int((measured[f"ret_{months}m"].isna()).sum()) for months in bt.horizons_months
    }
    penny = int((measured["avg_buy_price"] < bt.min_price).sum())

    lines = [
        tx(
            "limits.survivorship",
            dropped=tx.n(dropped),
            total=tx.n(total),
            share=share,
            no_prices=count(NO_PRICES),
            no_ticker=count(NO_TICKER),
            no_entry=count(NO_ENTRY),
            mismatch=count(PRICE_MISMATCH),
            jumps=count(SUSPECT_JUMP),
        ),
        tx(
            "limits.delisted",
            missing=", ".join(
                tx("limits.delisted_item", n=tx.n(v), months=k) for k, v in missing_exit.items()
            ),
        ),
        tx(
            "limits.microcaps",
            n=tx.n(penny),
            price=tx.price(bt.min_price),
            cost=tx.pct(bt.cost_roundtrip, 1),
        ),
        tx("limits.market_cap", coverage=tx.pct(coverage, 0)),
        tx("limits.overlap"),
        tx("limits.benchmark", name=bt.benchmark.upper()),
        tx("limits.execution"),
        tx("limits.code_p"),
        tx(
            "limits.manual",
            low=tx.n(bt.price_check_min_ratio, 1),
            high=tx.n(bt.price_check_max_ratio, 1),
        ),
        tx(
            "limits.yahoo",
            ratio=tx.n(bt.price_jump_ratio, 0),
            below=tx.price(bt.price_jump_below),
        ),
        tx("limits.ticker"),
        tx("limits.parameters"),
    ]
    if ctx.price_failures:
        lines.append(tx("limits.downloads", n=tx.n(ctx.price_failures)))
    return lines
