"""Phase 2 report (Markdown) and the compact summary the dashboard reads (JSON).

The verdict rule is the pre-registered one (research/phase2-plan.md): only the 2023–2025
test split decides, at the 3-month horizon, against both SPY and IWM.
"""

from __future__ import annotations

import json
import math
import pickle
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from radar.config import Settings

REFERENCES = ("R1_cluster_buy", "R2_big_officer_buy")
LAZY_CANDIDATE = "V8_lazy_nonchangers(Q5)"
COMPARISON_ONLY = "V0_text_covered"
HORIZON = 3

LABELS = {
    "R1_cluster_buy": "R1 `cluster_buy` (phase 1)",
    "R2_big_officer_buy": "R2 `big_officer_buy` (phase 1)",
    "V0_insider_buy": "V0 `insider_buy` (base)",
    "V1_opportunistic_buy": "V1 `opportunistic_buy`",
    "V2_first_buy": "V2 `first_buy`",
    "V3_stake_jump": "V3 `stake_jump`",
    "V4_dip_buy": "V4 `dip_buy`",
    "V5_csuite_cluster": "V5 `csuite_cluster`",
    "V6_opportunistic_dip": "V6 `opportunistic_dip`",
    "V7_first_big_stake": "V7 `first_big_stake`",
    "V0_text_covered": "V0 restricted to the text universe",
    "V9_insider_buy_text_ok": "V9 `insider_buy_text_ok`",
    "V8_lazy_nonchangers(Q5)": "V8 `lazy_nonchangers` (Q5)",
    "lazy_Q1_changers": "Lazy Q1 (most change, info only)",
    "lazy_all": "Lazy universe, all quintiles (info only)",
}


# ------------------------------------------------------------------------ formatting
def _missing(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def pct(x, digits: int = 1, sign: bool = True) -> str:
    if _missing(x):
        return "n/a"
    text = f"{x * 100:+.{digits}f}%" if sign else f"{x * 100:.{digits}f}%"
    return text.replace("-", "−")


def num(x, digits: int = 2) -> str:
    return "n/a" if _missing(x) else f"{x:+.{digits}f}".replace("-", "−")


def intf(x) -> str:
    return f"{int(x):,}"


def label(key: str) -> str:
    base, _, param = key.partition("@")
    text = LABELS.get(key, LABELS.get(base, base))
    return f"{text} ({param})" if param else text


# --------------------------------------------------------------------------- results
def _load(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def _block(res: dict, key: str, mode: str = "corrected") -> dict:
    entry = res.get(key, {})
    return entry.get(mode, entry)  # the text-signal results have no mode level


def events(res: dict, key: str, months: int = HORIZON, mode: str = "corrected") -> dict:
    return _block(res, key, mode).get("events", {}).get(str(months), {})


def portfolio(res: dict, key: str, months: int = HORIZON, mode: str = "corrected") -> dict:
    return _block(res, key, mode).get("portfolio", {}).get(str(months), {})


@dataclass
class Results:
    train: dict
    test: dict
    lazy_train: dict
    lazy_test: dict
    frozen: dict

    @classmethod
    def load(cls, data_dir: Path) -> Results:
        return cls(
            _load(data_dir / "train.json"),
            _load(data_dir / "test.json"),
            _load(data_dir / "lazy_train.json"),
            _load(data_dir / "lazy_test.json"),
            _load(data_dir / "frozen_params.json"),
        )

    def of(self, key: str, split: str) -> dict:
        if key.startswith(("V8", "lazy")):
            return self.lazy_train if split == "train" else self.lazy_test
        return self.train if split == "train" else self.test

    def candidates(self) -> list[str]:
        """Test-period variants with the frozen parameters, then the text candidate."""
        keys = []
        for key in self.test:
            if not key.startswith(("R", "V")):
                continue
            base, _, param = key.partition("@")
            if param and self.frozen:
                stake = base in ("V3_stake_jump", "V7_first_big_stake")
                wanted = self.frozen["stake"] if stake else self.frozen["dip"]
                if param != f"{wanted:.0%}":
                    continue
            keys.append(key)
        return keys + ([LAZY_CANDIDATE] if LAZY_CANDIDATE in self.lazy_test else [])


def verdict(key: str, train: dict, test: dict) -> tuple[str, str]:
    """use / maybe / discard, exactly as pre-registered."""
    e, p, pt = events(test, key), portfolio(test, key), portfolio(train, key)
    if not e.get("n") or not p.get("months"):
        return "discard", "no test data"

    def above(block: dict, name: str, level: float = 0.0) -> bool:
        value = block.get(name)
        return not _missing(value) and value > level

    def at_least(name: str, level: float) -> bool:
        value = p.get(name)
        return not _missing(value) and value >= level

    medians = above(e, "median_spy") and above(e, "median_iwm")
    if medians and at_least("t_spy", 2) and at_least("t_iwm", 2):
        return "use", "passes both conditions in test"
    positive = all(above(b, f"exc_{x}") for b in (p, pt) for x in ("spy", "iwm"))
    t_values = [p.get("t_spy"), p.get("t_iwm")]
    t_min = min((t for t in t_values if not _missing(t)), default=0.0)
    one = (above(e, "median_spy") and at_least("t_spy", 2)) or (
        above(e, "median_iwm") and at_least("t_iwm", 2)
    )
    if positive and (1 <= t_min < 2 or one):
        return "maybe", "positive in train and test, not significant on both benchmarks"
    return "discard", "fails the pre-registered criterion"


# --------------------------------------------------------------------- report text
def _survivorship(data_dir: Path) -> dict:
    """The correction's numbers on the phase-1 signals, all six years together."""
    frames = {}
    for split in ("train", "test"):
        path = data_dir / f"{split}_frames.pkl"
        if path.exists():
            with open(path, "rb") as handle:
                frames.update({(split, *k): v for k, v in pickle.load(handle).items()})
    pick = [(s, k) for s in ("train", "test") for k in REFERENCES]
    fixed = [frames[(s, k, "corrected")] for s, k in pick if (s, k, "corrected") in frames]
    raw = [frames[(s, k, "raw")] for s, k in pick if (s, k, "raw") in frames]
    if not fixed:
        return {}
    fixed, raw = pd.concat(fixed), pd.concat(raw)
    only = fixed[fixed.how_3m.astype(str).ne("yahoo") & fixed.net_3m.notna()]
    how = fixed.how_3m.astype(str).str.split("|").str[0]
    excess = only.exc_spy_3m.astype(float)
    return {
        "generated": len(fixed),
        "raw": int(raw.net_3m.notna().sum()),
        "corrected": int(fixed.net_3m.notna().sum()),
        "outcomes": fixed[fixed.source == "sec"].outcome.value_counts().to_dict(),
        "how": how[how.ne("") & how.ne("yahoo")].value_counts().to_dict(),
        "median_raw": float(raw.exc_spy_3m.astype(float).median()),
        "median_corrected": float(fixed.exc_spy_3m.astype(float).median()),
        "only_n": len(only),
        "only_median": float(excess.median()),
        "only_beats": float((excess > 0).mean()),
        "still": int(fixed.net_3m.isna().sum()),
    }


def _funnel(data_dir: Path) -> list[tuple[str, str]]:
    trades, base_path = data_dir / "trades.parquet", data_dir / "base_filings.pkl"
    if not trades.exists() or not base_path.exists():
        return []
    lines, filings = duckdb.sql(
        f"SELECT count(*), count(DISTINCT acc) FROM '{trades}' "
        "WHERE code = 'P' AND filing_date BETWEEN '2020-01-01' AND '2025-12-31'"
    ).fetchall()[0]
    base = pd.read_pickle(base_path)
    base = base[(base.filing_date >= "2020-01-01") & (base.filing_date <= "2025-12-31")]
    return [
        ("Code-P lines in original Form 4s, 2020–2025", intf(lines)),
        ("Form 4s with a code-P line", intf(filings)),
        (
            "Base filings: officer or director, common stock, ≥ US$ 50k "
            "(before the 30-day cooldown)",
            intf(len(base)),
        ),
        ("… opportunistic (Cohen, Malloy & Pomorski)", intf(int(base.opportunistic.sum()))),
        ("… first purchase in 24 months", intf(int(base.first_buy.sum()))),
        ("… stake increase ≥ 20%", intf(int((base.stake_inc >= 0.2).sum()))),
        (
            "Signals per variant after the cooldown, and how many were measured",
            "see the train vs test table",
        ),
    ]


def _verdict_notes(results: Results) -> list[str]:
    if not results.test:
        return []
    r2 = portfolio(results.test, "R2_big_officer_buy")
    r2_train = portfolio(results.train, "R2_big_officer_buy")
    return [
        "Closest call: R2 `big_officer_buy` (the phase-1 rule, unchanged) earned "
        f"{pct(r2.get('exc_iwm'), 2)} a month over IWM in 2023–2025 (t {num(r2.get('t_iwm'), 1)}), "
        f"but {pct(r2.get('exc_spy'), 2)} against SPY (t {num(r2.get('t_spy'), 1)}) and a negative "
        "median excess against both. It beat small caps, not the market, and the typical signal "
        "still lost: it fails the pre-registered rule. It was not a candidate in train either "
        f"(t {num(r2_train.get('t_iwm'), 1)} against IWM).",
        "The 10-K text signal went the wrong way in the test period: the least-changed "
        "quintile (V8) lagged SPY by a significant margin, and the top-minus-bottom spread that "
        "was positive in train turned negative. An equal-weighted basket of US stocks above "
        "US$ 300 million lagged a cap-weighted SPY led by a handful of mega-caps in 2023–2025; "
        "the text signal did not overcome that.",
    ]


def _survivorship_text(s: dict) -> list[str]:
    if not s:
        return []
    outcomes = ", ".join(f"{k.replace('_', ' ')} {intf(v)}" for k, v in s["outcomes"].items())
    how = ", ".join(f"{k.replace('_', ' ')} {intf(v)}" for k, v in s["how"].items())
    share = s["generated"]
    return [
        f"Phase-1 signals 2020–2025: {intf(s['generated'])} generated. At 3 months, Yahoo alone "
        f"measures {intf(s['raw'])} ({s['raw'] / share:.0%}); with the SEC-based correction, "
        f"{intf(s['corrected'])} ({s['corrected'] / share:.0%}). {intf(s['still'])} remain "
        "unmeasured, mostly companies that left the exchange years after the signal and have no "
        "insider trade near the horizon date.",
        "What happened to the companies without Yahoo prices, from their own SEC filings: "
        f"{outcomes}.",
        f"How the corrected 3-month exits were valued: {how}. Most terminal events (mergers, "
        "bankruptcies) happen long after a 3- or 6-month horizon, so the price tape does most of "
        "the work.",
        f"The {intf(s['only_n'])} signals measured only thanks to the correction did **worse** "
        f"than the rest: median 3-month excess vs SPY {pct(s['only_median'])}, "
        f"{s['only_beats']:.0%} beat the index. Putting them back moves the median excess of all "
        f"phase-1 signals from {pct(s['median_raw'])} to {pct(s['median_corrected'])}. "
        "Survivorship bias was flattering phase 1, not hiding a winner.",
        "Price tape accuracy (checked on signals Yahoo does price, see plan addendum b): median "
        "error about +1% against Yahoo, 90th percentile absolute error about 20%. The tape is a "
        "noisy but unbiased-in-the-median substitute; treat corrected numbers as approximate.",
    ]


PARAM_TEXT = (
    "Only two free parameters, each picked by the higher train-period monthly excess vs IWM "
    "(differences under 0.1 percentage point go to the stricter value): stake increase "
    "X = **20%** (10%: +0.37%, 20%: +0.40% a month) and drawdown Y = **30%** (20%: −0.79%, "
    "30%: −0.59%). See plan addenda (d) and (e)."
)

LAZY_TEXT = (
    "Universe: 10-K filers with a current ticker, Yahoo prices and a market value ≥ "
    "US$ 300 million on the filing date (shares outstanding from XBRL frames × Yahoo close). "
    "Each 10-K is compared with the previous one (cosine similarity of word counts) and ranked "
    "against all universe filings of the previous 12 months. Positions are entered after the "
    "filing and held 3 months."
)

LIMITATIONS = (
    "**Survivorship correction is approximate.** It uses Form 4 prices (noisy, about 20% error "
    "at the 90th percentile), merger considerations from Form 4 code D or proxy text, and −100% "
    "for bankruptcies. About 17% of phase-1 signals remain unmeasured.",
    "**The text universe is survivorship-biased**: it starts from today's SEC ticker list and "
    "Yahoo, so companies that disappeared before 2026 are missing. Only 10-Ks were compared (no "
    "10-Q), on the whole document; the hidden inline-XBRL header stayed in the text (mostly "
    "numbers, which are dropped).",
    "**Drawdown needs Yahoo history**, so issuers without it can never be a V4/V6 signal.",
    "**Execution is idealized**: close-to-close, fixed costs (0.2%, 1% below US$ 5), no market "
    "impact, no taxes. Microcaps would cost more.",
    "**Three years of test data** is 36 monthly observations: an effect of 0.3% a month would "
    "need years more to reach t = 2. The test rejects strong effects; it cannot prove a small "
    "one is absent.",
    "**Opportunistic classification** follows Cohen, Malloy & Pomorski and only covers insiders "
    "with three prior years of trades (about 13% of base filings).",
    "**Code P is not only open-market buying**: private placements and offerings at a fixed "
    "price also use it.",
)

REPRODUCE = """```bash
uv run radar phase2 collect          # SEC datasets and filings, prices (hours the first time)
uv run radar phase2 run --split train
uv run radar phase2 freeze --stake 0.2 --dip 0.3
uv run radar phase2 run --split test
uv run radar phase2 report
```"""


# ----------------------------------------------------------------------- rendering
def _row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def render(data_dir: Path, stamp: str) -> str:
    """The Markdown report from the result files in `data_dir` (data/phase2)."""
    r = Results.load(data_dir)
    keys = r.candidates()
    out: list[str] = []
    w = out.append

    w(f"# Radar SEC — phase 2 backtest ({stamp})\n")
    w(
        "Train: signals filed 2020-01-01 to 2022-12-31. Test: 2023-01-01 to 2025-12-31, run once "
        "per variant after the parameters were frozen. Pre-registration: "
        "[`research/phase2-plan.md`](../research/phase2-plan.md). Data: SEC Insider Transactions "
        "Data Sets 2016Q4–2025Q4, SEC submissions API, EDGAR 10-K documents, XBRL frames, Yahoo "
        "Finance daily prices. No AI anywhere in the backtest.\n"
    )

    w("## Verdict\n")
    verdicts = [(k, *verdict(k, r.of(k, "train"), r.of(k, "test"))) for k in keys]
    used = [k for k, v, _ in verdicts if v == "use"]
    maybe = [k for k, v, _ in verdicts if v == "maybe"]
    if used:
        names = ", ".join(label(k) for k in used)
        w(f"**{len(used)} variant(s) passed the pre-registered out-of-sample test**: {names}.\n")
    else:
        extra = ""
        if maybe:
            extra = (
                " "
                + ", ".join(label(k) for k in maybe)
                + ' ended as "maybe" (watch, do not trade).'
            )
        w(
            "**No variant passed the pre-registered out-of-sample test.** None combined a "
            "positive median excess return against both SPY and IWM with a Newey-West t ≥ 2 on "
            f"both benchmarks in 2023–2025.{extra}\n"
        )
    w("Test period (2023–2025), 3-month holding, survivorship-corrected, after costs:\n")
    w(
        _row(
            [
                "Variant",
                "Signals measured",
                "Median excess vs SPY",
                "Median excess vs IWM",
                "Portfolio excess/month vs SPY (t)",
                "vs IWM (t)",
                "Alpha/month vs IWM (t)",
                "Verdict",
            ]
        )
    )
    w("|---|---|---|---|---|---|---|---|")
    for key, code, _ in verdicts:
        e, p = events(r.of(key, "test"), key), portfolio(r.of(key, "test"), key)
        w(
            _row(
                [
                    label(key),
                    intf(e.get("n", 0)),
                    pct(e.get("median_spy")),
                    pct(e.get("median_iwm")),
                    f"{pct(p.get('exc_spy'), 2)} ({num(p.get('t_spy'), 1)})",
                    f"{pct(p.get('exc_iwm'), 2)} ({num(p.get('t_iwm'), 1)})",
                    f"{pct(p.get('alpha_iwm'), 2)} ({num(p.get('t_alpha_iwm'), 1)})",
                    f"**{code}**",
                ]
            )
        )
    w("")
    w(
        "Pass criterion (fixed before the test run): median per-signal excess > 0 against SPY "
        "and IWM, and Newey-West t ≥ 2 of the mean monthly excess of the calendar portfolio "
        'against SPY and IWM, at the 3-month horizon, in 2023–2025. "maybe" = positive mean '
        "monthly excess against both benchmarks in train and in test, with test t between 1 and "
        "2 or a pass on only one benchmark.\n"
    )
    for note in _verdict_notes(r):
        w(note + "\n")

    funnel = _funnel(data_dir)
    if funnel:
        w("## Funnel\n")
        w("| Step | Count |")
        w("|---|---|")
        for step, count in funnel:
            w(_row([step, count]))
        w("")

    w("## Survivorship correction\n")
    for line in _survivorship_text(_survivorship(data_dir)):
        w(line + "\n")
    w("Effect on the phase-1 signals (3 months, after costs):\n")
    w(
        _row(
            [
                "Signal",
                "Period",
                "Measured without correction",
                "With correction",
                "Median excess vs SPY: without → with",
                "Portfolio excess/month vs SPY: without → with (t)",
            ]
        )
    )
    w("|---|---|---|---|---|---|")
    for key in (*REFERENCES, "V0_insider_buy"):
        for split in ("train", "test"):
            res = r.of(key, split)
            generated = res.get(key, {}).get("generated", 0)
            if not generated:
                continue
            er, ec = events(res, key, mode="raw"), events(res, key)
            pr, pc = portfolio(res, key, mode="raw"), portfolio(res, key)
            w(
                _row(
                    [
                        label(key),
                        split,
                        f"{intf(er.get('n', 0))} of {intf(generated)}",
                        f"{intf(ec.get('n', 0))} of {intf(generated)}",
                        f"{pct(er.get('median_spy'))} → {pct(ec.get('median_spy'))}",
                        f"{pct(pr.get('exc_spy'), 2)} ({num(pr.get('t_spy'), 1)}) → "
                        f"{pct(pc.get('exc_spy'), 2)} ({num(pc.get('t_spy'), 1)})",
                    ]
                )
            )
    w("")

    w("## Parameters chosen on train\n")
    w(PARAM_TEXT + "\n")

    w("## Train vs test, every variant (3 months)\n")
    w(
        _row(
            [
                "Variant",
                "Split",
                "Generated",
                "Measured",
                "Of which corrected",
                "Mean net return",
                "Median excess vs SPY",
                "vs IWM",
                "Beats SPY",
                "Months",
                "Avg positions",
                "Excess/month vs SPY (t)",
                "vs IWM (t)",
                "Alpha vs SPY (t)",
                "Alpha vs IWM (t)",
            ]
        )
    )
    w("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    every = [k for k in r.test if k.startswith(("R", "V"))]
    for key in [*every, LAZY_CANDIDATE, "lazy_Q1_changers", "lazy_all"]:
        for split in ("train", "test"):
            res = r.of(key, split)
            if key not in res:
                continue
            e, p = events(res, key), portfolio(res, key)
            positions = p.get("avg_positions")
            w(
                _row(
                    [
                        label(key),
                        split,
                        intf(res[key].get("generated", 0)),
                        intf(e.get("n", 0)),
                        intf(e.get("n_corrected", 0)),
                        pct(e.get("mean_net")),
                        pct(e.get("median_spy")),
                        pct(e.get("median_iwm")),
                        pct(e.get("beats_spy"), 0, False),
                        str(p.get("months", "")),
                        "n/a" if _missing(positions) else f"{positions:.0f}",
                        f"{pct(p.get('exc_spy'), 2)} ({num(p.get('t_spy'), 1)})",
                        f"{pct(p.get('exc_iwm'), 2)} ({num(p.get('t_iwm'), 1)})",
                        f"{pct(p.get('alpha_spy'), 2)} ({num(p.get('t_alpha_spy'), 1)})",
                        f"{pct(p.get('alpha_iwm'), 2)} ({num(p.get('t_alpha_iwm'), 1)})",
                    ]
                )
            )
    w("")
    w(
        "Excess and alpha are per month. t uses Newey-West standard errors with 3 lags. Alpha is "
        "the intercept of the portfolio return minus the T-bill rate regressed on the benchmark "
        "return minus the T-bill rate.\n"
    )

    w("## Other horizons (test)\n")
    w(
        _row(
            [
                "Variant",
                "Horizon",
                "Median excess vs SPY",
                "vs IWM",
                "Excess/month vs SPY (t)",
                "vs IWM (t)",
            ]
        )
    )
    w("|---|---|---|---|---|---|")
    for key in keys:
        res = r.of(key, "test")
        for months in (1, 6):
            e, p = events(res, key, months), portfolio(res, key, months)
            w(
                _row(
                    [
                        label(key),
                        f"{months}m",
                        pct(e.get("median_spy")),
                        pct(e.get("median_iwm")),
                        f"{pct(p.get('exc_spy'), 2)} ({num(p.get('t_spy'), 1)})",
                        f"{pct(p.get('exc_iwm'), 2)} ({num(p.get('t_iwm'), 1)})",
                    ]
                )
            )
    w("")

    w("## By year (median excess vs SPY, 3 months, per signal)\n")
    years = list(range(2020, 2026))
    w(_row(["Variant", *(str(y) for y in years)]))
    w("|---|" + "---|" * len(years))
    for key in keys:
        cells = []
        for year in years:
            res = r.of(key, "train" if year <= 2022 else "test")
            stats = _block(res, key).get("by_year", {}).get(str(year), {}).get("3", {})
            n = stats.get("n")
            cells.append(f"{pct(stats.get('median_spy'))} ({n})" if n else "n/a")
        w(_row([label(key), *cells]))
    w("")
    w("Number of measured signals in parentheses.\n")

    w("## Lazy Prices (10-K text change)\n")
    w(LAZY_TEXT + "\n")
    if r.lazy_test:
        w("| Year | 10-K filings ranked | Companies |")
        w("|---|---|---|")
        for res in (r.lazy_train, r.lazy_test):
            for year, u in sorted(res.get("universe", {}).items()):
                w(_row([year, intf(u["filings"]), intf(u["companies"])]))
        w("")
        for split, res in (("train", r.lazy_train), ("test", r.lazy_test)):
            spread = res.get("spread_Q5_minus_Q1", {})
            w(
                f"- {split}: top-minus-bottom quintile spread {pct(spread.get('mean_month'), 2)} "
                f"a month (t {num(spread.get('t'), 1)}, {spread.get('months')} months)."
            )
        w("")

    w("## Limitations\n")
    for i, text in enumerate(LIMITATIONS, 1):
        w(f"{i}. {text}")
    w("")
    w("## Reproducing\n")
    w(REPRODUCE)
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------------- summary
def _numbers(res: dict, key: str) -> dict:
    e, p = events(res, key), portfolio(res, key)
    return {
        "n": e.get("n", 0),
        "median_spy": e.get("median_spy"),
        "median_iwm": e.get("median_iwm"),
        "exc_spy": p.get("exc_spy"),
        "t_spy": p.get("t_spy"),
        "exc_iwm": p.get("exc_iwm"),
        "t_iwm": p.get("t_iwm"),
    }


def _clean(value):
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def summary(data_dir: Path, stamp: str) -> dict:
    """What the dashboard shows: test-period numbers and verdict per variant, plus the
    survivorship correction's effect on the phase-1 signals."""
    r = Results.load(data_dir)
    variants = []
    for key in r.candidates():
        if key == COMPARISON_ONLY:
            continue
        variants.append(
            {
                "key": key.partition("@")[0].replace("(Q5)", ""),
                "verdict": verdict(key, r.of(key, "train"), r.of(key, "test"))[0],
                "train": _numbers(r.of(key, "train"), key),
                "test": _numbers(r.of(key, "test"), key),
            }
        )
    s = _survivorship(data_dir)
    return _clean(
        {
            "date": stamp,
            "report": f"phase2-{stamp}.md",
            "horizon_months": HORIZON,
            "train": {"start": "2020-01-01", "end": "2022-12-31"},
            "test": {"start": "2023-01-01", "end": "2025-12-31"},
            "passed": [v["key"] for v in variants if v["verdict"] == "use"],
            "variants": variants,
            "survivorship": {
                "generated": s["generated"],
                "measured_raw": s["raw"],
                "measured_corrected": s["corrected"],
                "median_spy_raw": s["median_raw"],
                "median_spy_corrected": s["median_corrected"],
            }
            if s
            else None,
        }
    )


def write_reports(settings: Settings, stamp: str | None = None) -> list[Path]:
    """reports/phase2-<date>.md and reports/phase2-<date>.json from data/phase2."""
    data_dir = settings.data_dir / "phase2"
    if not (data_dir / "test.json").exists():
        raise RuntimeError("no test results yet: run `radar phase2 run --split test` first")
    stamp = stamp or date.today().isoformat()
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    md = settings.reports_dir / f"phase2-{stamp}.md"
    md.write_text(render(data_dir, stamp), encoding="utf-8")
    js = settings.reports_dir / f"phase2-{stamp}.json"
    js.write_text(json.dumps(summary(data_dir, stamp), indent=1) + "\n", encoding="utf-8")
    return [md, js]
