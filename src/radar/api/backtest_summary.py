"""Backtest summary for the dashboard, read from the Markdown reports.

The reports versioned in `reports/` are the source: the dashboard shows the same
numbers the operator would read in them, without recomputing anything. Numbers
come from the English report (`backtest-<date>.md`); the verdict and caveat come
from every language's report (`backtest-<date>.pt-BR.md`...) as a localized map.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from radar.backtest.report import report_name
from radar.i18n import DEFAULT_LANG, LANGS, PT_BR, t
from radar.signals import SIGNAL_LABELS

_HEADING = re.compile(r"^(#{1,3})\s+(.*)$")
_HORIZON = re.compile(r"^(\d+)m$")
_PERIOD = re.compile(r"(\d{4}-\d{2}-\d{2})\D+(\d{4}-\d{2}-\d{2})")
_REPORT = re.compile(r"backtest-(\d{4}-\d{2}-\d{2})\.md")


def _r(key: str, lang: str, **values: object) -> str:
    return t(f"report.{key}", lang, **values)


def number(text: str, lang: str = DEFAULT_LANG) -> float | None:
    """A number as the report writes it: "4,903", "+0.8%", "**-6.5%**" (pt-BR: "4.903", "+0,8%")."""
    raw = text.replace("*", "").replace("`", "").strip()
    raw = raw.split(" (")[0].strip()  # "4,903 (74%)" → "4,903"
    if not raw or raw in {"n/a", "n/d", "—", "-"}:
        return None
    percent = raw.endswith("%")
    raw = raw.rstrip("%").replace("US$", "").replace("$", "").replace("+", "")
    if lang == PT_BR:
        raw = raw.replace(".", "").replace(",", ".")
    else:
        raw = raw.replace(",", "")
    raw = raw.replace("−", "-").strip()
    try:
        value = float(raw)
    except ValueError:
        return None
    return round(value / 100, 6) if percent else value


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def parse_sections(markdown: str) -> dict[str, dict[str, Any]]:
    """Splits the report by heading and extracts the text and tables of each section."""
    sections: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] = {"text": [], "tables": []}
    sections[""] = current
    table: list[list[str]] | None = None

    def flush() -> None:
        nonlocal table
        if table and len(table) >= 2:
            header, rows = table[0], table[2:]
            current["tables"].append(
                [dict(zip(header, row, strict=False)) for row in rows if len(row) == len(header)]
            )
        table = None

    for line in markdown.splitlines():
        heading = _HEADING.match(line)
        if heading:
            flush()
            current = {"text": [], "tables": []}
            sections[heading.group(2).strip()] = current
        elif line.lstrip().startswith("|"):
            table = (table or []) + [_cells(line)]
        else:
            flush()
            if line.strip():
                current["text"].append(line.strip())
    flush()
    return sections


def _result_rows(table: list[dict[str, str]], benchmark: str, lang: str) -> list[dict[str, Any]]:
    rows = []
    for row in table:
        horizon = _HORIZON.match(row.get(_r("col.horizon", lang), ""))
        if not horizon:
            continue

        def pick(*keys: str, source: dict[str, str] = row) -> float | None:
            for key in keys:
                name = key if key == "N" else _r(key, lang, name=benchmark)
                if name in source:
                    return number(source[name], lang)
            return None

        kind = row.get(_r("col.signal", lang), "").strip("` ")
        rows.append(
            {
                "type": kind,
                "label": SIGNAL_LABELS.get(kind, kind),
                "horizon_months": int(horizon.group(1)),
                "n": int(pick("N") or 0),
                "hit_rate": pick("col.hit_rate"),
                "beats": pick("col.beats"),
                "ret_mean": pick("col.mean_return"),
                "ret_median": pick("col.median"),
                "bench_mean": pick("col.bench_mean"),
                "excess_mean": pick("col.excess_mean", "col.excess_mean_vs"),
                "excess_median": pick("col.excess_median", "col.excess_median_vs"),
                "t_stat": pick("col.t_cohort"),
            }
        )
    return rows


def _first_table(sections: dict[str, dict[str, Any]], prefix: str) -> list[dict[str, str]]:
    for title, section in sections.items():
        if title.startswith(prefix) and section["tables"]:
            return section["tables"][0]
    return []


def _heading_prefix(key: str, lang: str, **values: object) -> str:
    """The fixed start of a heading (before its first number placeholder)."""
    return _r(key, lang, **values).split("{", 1)[0]


def verdict_texts(markdown: str, lang: str = DEFAULT_LANG) -> tuple[str, str]:
    """(verdict headline, survivorship caveat) of a report, without Markdown emphasis."""
    sections = parse_sections(markdown)
    text = sections.get(_r("h.verdict", lang), {}).get("text", [])
    verdict = text[0].replace("**", "") if text else ""
    caveat = next((line.lstrip("> ") for line in text if line.startswith(">")), "")
    return verdict, caveat


def parse_report(markdown: str, *, name: str = "", lang: str = DEFAULT_LANG) -> dict[str, Any]:
    sections = parse_sections(markdown)
    title = next((s for s in sections if s.startswith("Backtest")), "")
    period = _PERIOD.search(title)
    generated = re.search(
        re.escape(_r("generated", lang, generated="\0", first="", last="").split("\0")[0])
        + r"([\d/: -]+?)\.",
        markdown,
    )

    verdict, caveat = verdict_texts(markdown, lang)

    main = _result_rows(_first_table(sections, _r("h.results", lang)), "SPY", lang)
    iwm = _result_rows(_first_table(sections, _r("h.against", lang, name="IWM")), "IWM", lang)
    cap_heading = _heading_prefix("h.liquid_cap", lang, price="{", cap="")
    liquid = _result_rows(_first_table(sections, cap_heading), "SPY", lang)

    by_year = []
    year_col = _r("col.year", lang)
    for row in _first_table(sections, _r("h.year_excess", lang, name="SPY")):
        year = number(row.get(year_col, ""), lang)
        if year is None:
            continue
        by_year.append(
            {
                "type": row.get(_r("col.signal", lang), ""),
                "year": int(year),
                "n": int(number(row.get("N", ""), lang) or 0),
                **{
                    f"excess_{stat}_{months}m": number(
                        row.get(_r(f"col.{stat}_m", lang, months=months), ""), lang
                    )
                    for months in (1, 3, 6)
                    for stat in ("mean", "median")
                },
            }
        )

    funnel: dict[str, Any] = {}
    funnel_tables = sections.get(_r("h.funnel", lang), {}).get("tables", [])
    if len(funnel_tables) > 1:
        gen_col, meas_col = _r("col.generated", lang), _r("col.measured", lang)
        generated_total = sum(number(r.get(gen_col, ""), lang) or 0 for r in funnel_tables[1])
        measured_total = sum(number(r.get(meas_col, ""), lang) or 0 for r in funnel_tables[1])
        if generated_total:
            funnel = {
                "generated": int(generated_total),
                "measured": int(measured_total),
                "unmeasured": int(generated_total - measured_total),
                "unmeasured_share": (generated_total - measured_total) / generated_total,
            }

    t_values = [row["t_stat"] for row in main if row["t_stat"] is not None]
    medians = [row["excess_median"] for row in main if row["excess_median"] is not None]
    beats = [row["beats"] for row in main if row["beats"] is not None]
    return {
        "report": name,
        "period": {"start": period.group(1), "end": period.group(2)} if period else None,
        "generated_at": generated.group(1).strip() if generated else None,
        "benchmark": "SPY",
        # The report is the reference: if the median excess is negative at every
        # horizon, the typical signal lost to the index.
        "beats_benchmark": bool(medians) and all(value > 0 for value in medians),
        "verdict": {lang: verdict},
        "caveat": {lang: caveat},
        "rows": main,
        "rows_iwm": iwm,
        "rows_liquid": liquid,
        "by_year": by_year,
        "funnel": funnel,
        "max_t": max(t_values) if t_values else None,
        "best_beats": max(beats) if beats else None,
        "cost_roundtrip": 0.002,
    }


def latest_report(reports_dir: Path) -> Path | None:
    """The latest English report (`backtest-<date>.md`)."""
    files = sorted(p for p in reports_dir.glob("backtest-*.md") if _REPORT.fullmatch(p.name))
    return files[-1] if files else None


_PHASE2 = re.compile(r"phase2-(\d{4}-\d{2}-\d{2})\.json")


def load_phase2(reports_dir: Path) -> dict[str, Any] | None:
    """The latest phase-2 summary (`phase2-<date>.json`, written by `radar phase2 report`)."""
    files = sorted(p for p in reports_dir.glob("phase2-*.json") if _PHASE2.fullmatch(p.name))
    if not files:
        return None
    try:
        return json.loads(files[-1].read_text(encoding="utf-8"))
    except ValueError:
        return None


def load_summary(reports_dir: Path) -> dict[str, Any] | None:
    path = latest_report(reports_dir)
    if path is None:
        return None
    summary = parse_report(path.read_text(encoding="utf-8"), name=path.name)
    summary["phase2"] = load_phase2(reports_dir)
    stamp = _REPORT.fullmatch(path.name).group(1)  # type: ignore[union-attr]
    for lang in LANGS:
        if lang == DEFAULT_LANG:
            continue
        translated = reports_dir / report_name(stamp, lang)
        if translated.exists():
            verdict, caveat = verdict_texts(translated.read_text(encoding="utf-8"), lang)
        else:  # no translated report: fall back to the English text
            verdict, caveat = summary["verdict"][DEFAULT_LANG], summary["caveat"][DEFAULT_LANG]
        summary["verdict"][lang] = verdict
        summary["caveat"][lang] = caveat
    return summary
