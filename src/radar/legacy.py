"""Upgrades data written by the radar's first, Portuguese-only version.

Early databases, replay files and backtest CSVs stored Portuguese codes, keys
and labels. Everything here maps them to the English codes used today. The
functions are idempotent: data that is already English passes through unchanged.
The Portuguese strings below are stored values, not text shown to anyone.
"""

from __future__ import annotations

from typing import Any

FILING_STATUS = {
    "novo": "new",
    "processado": "processed",
    "ignorado": "skipped",
    "erro": "error",
}

SUMMARY_SOURCE = {"ia": "ai"}

SOURCE_FORMAT = {"legado": "legacy"}

SECTORS = {
    "Saúde": "Healthcare",
    "Tecnologia": "Technology",
    "Financeiro": "Financials",
    "Imobiliário": "Real Estate",
    "Energia": "Energy",
    "Utilidades": "Utilities",
    "Materiais": "Materials",
    "Indústria": "Industrials",
    "Consumo": "Consumer",
    "Comunicação": "Communication",
    "Serviços": "Services",
    "Sem setor": "Unclassified",
}

OUTCOME_STATUS = {
    "sem_ticker": "no_ticker",
    "sem_precos": "no_prices",
    "sem_preco_de_entrada": "no_entry_price",
    "preco_incompativel": "price_mismatch",
    "salto_suspeito": "suspect_jump",
    "sem_medicao": "unmeasured",
}

ROLES = {
    "diretor (conselho)": "Director",
    "executivo": "Officer",
    "Executivo": "Officer",
    "dono de 10%+": "10% owner",
    "diretor/executivo": "Director/Officer",
    "outro": "Other",
    "declarante": "13D filer",
    "declarante do 13D": "13D filer",
    "arquiva em conjunto": "Joint filer",
    "Declarante não identificado": "Unidentified filer",
}

TICKER_SOURCE = {"sec_atual": "sec_current"}

# Backtest signals CSV: old column → new column. Per-horizon columns are handled
# by `csv_column`.
CSV_COLUMNS = {
    "tipo": "type",
    "data_sinal": "signal_date",
    "ano": "year",
    "safra": "cohort",
    "emissor": "issuer",
    "ticker_fonte": "ticker_source",
    "valor_total": "total_value",
    "n_insiders_od": "n_officer_director",
    "preco_medio_compra": "avg_buy_price",
    "ultima_compra": "last_buy",
    "explicacao": "explanation",
    "data_entrada": "entry_date",
    "preco_entrada": "entry_price",
    "razao_preco_mercado": "market_price_ratio",
    "salto_suspeito": "suspect_jump",
    "acoes_em_circulacao": "shares_outstanding",
    "valor_de_mercado": "market_cap",
}
_CSV_PREFIXES = {"data_saida_": "exit_date_", "bruto_": "gross_", "exc_": "excess_"}

_COMMON_KEYS = {
    "valor_total": "total_value",
    "acoes": "shares",
    "preco_medio": "avg_price",
    "primeira_compra": "first_buy",
    "ultima_compra": "last_buy",
}
_DETAIL_KEYS = {
    "cluster_buy": {
        **_COMMON_KEYS,
        "n_insiders_od": "n_officer_director",
        "tem_ceo_cfo": "has_ceo_cfo",
    },
    "big_officer_buy": {
        **_COMMON_KEYS,
        "cargo": "role",
        "titulo": "title",
        "aumento_posicao": "stake_increase",
    },
    "activist_13d": {
        "declarante": "filer",
        "percentual": "percent",
        "acoes": "shares",
        "codeclarantes": "co_filers",
        "data_evento": "event_date",
        "formato": "source_format",
        "tom_ativista": "activist_tone",
        "proposito": "purpose",
    },
}
_INSIDER_KEYS = {"nome": "name", "cargo": "role", "valor": "value"}


def role(value: Any) -> Any:
    """A Portuguese role label → its English code; free-text titles pass through."""
    return ROLES.get(value, value) if isinstance(value, str) else value


def sector(value: str | None) -> str | None:
    return SECTORS.get(value, value) if value else value


def outcome_status(value: str | None) -> str | None:
    return OUTCOME_STATUS.get(value, value) if value else value


def _rename(item: dict[str, Any], keys: dict[str, str]) -> dict[str, Any]:
    return {keys.get(key, key): value for key, value in item.items()}


def upgrade_details(signal_type: str, details: dict[str, Any]) -> dict[str, Any]:
    """Signal details with English keys and role codes."""
    out = _rename(details, _DETAIL_KEYS.get(signal_type, {}))
    if signal_type == "cluster_buy":
        out["insiders"] = [
            {**(renamed := _rename(i, _INSIDER_KEYS)), "role": role(renamed.get("role", ""))}
            for i in out.get("insiders", [])
        ]
    elif signal_type == "big_officer_buy":
        out["insider"] = role(out.get("insider"))
    elif signal_type == "activist_13d":
        out["filer"] = role(out.get("filer"))
        if out.get("source_format") in SOURCE_FORMAT:
            out["source_format"] = SOURCE_FORMAT[out["source_format"]]
    return out


def upgrade_purchase_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**row, "role": role(row.get("role", ""))} for row in rows]


def upgrade_outcome(outcome: dict[str, Any]) -> dict[str, Any]:
    if not outcome:
        return outcome
    return {**outcome, "status": outcome_status(outcome.get("status"))}


def csv_column(name: str) -> str:
    """An old backtest CSV column name → the current one."""
    if name in CSV_COLUMNS:
        return CSV_COLUMNS[name]
    for old, new in _CSV_PREFIXES.items():
        if name.startswith(old):
            return new + name.removeprefix(old)
    return name


def is_legacy_csv(columns: list[str]) -> bool:
    return "tipo" in columns or "data_sinal" in columns
