"""Configuration: environment variables (.env) and tunable parameters (radar.toml)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields, is_dataclass, replace
from pathlib import Path
from typing import Any

from dotenv import find_dotenv, load_dotenv

from radar.i18n import DEFAULT_LANG, normalize_lang


class ConfigError(RuntimeError):
    """Configuration error with a message meant for the end user."""


@dataclass(frozen=True)
class SignalConfig:
    """Signal rule thresholds. They apply equally to `watch` and the backtest."""

    cluster_window_days: int = 14
    cluster_min_insiders: int = 2
    cluster_min_value: float = 100_000.0
    officer_min_value: float = 250_000.0
    activist_min_percent: float = 5.0
    # After a signal, the same type does not fire again for the same issuer during
    # this period (avoids counting the same wave of purchases several times).
    cooldown_days: int = 30
    # Drop closed-end funds and similar vehicles from cluster_buy and big_officer_buy
    # (see radar.funds): their directors buying fund shares is not an insider bet.
    exclude_funds: bool = True
    # SIC codes treated as funds: 6722 (open-end investment offices) and 6726 (unit
    # investment trusts and closed-end investment offices). 6798 (REITs) is not a fund.
    fund_sic_codes: tuple[str, ...] = ("6722", "6726")
    # When the SIC is missing, also recognize obvious fund names ("Municipal Income Fund").
    fund_name_heuristic: bool = True


@dataclass(frozen=True)
class SecConfig:
    requests_per_second: float = 8.0  # the SEC limit is 10/s
    max_retries: int = 5
    timeout_seconds: float = 30.0
    # "SCHEDULE 13D" is the form name since Dec 2024 and also covers amendments.
    # The old name, "SC 13D", no longer receives filings: its feed is always empty
    # and slow to answer, so it is left out by default (it can be added here).
    feed_forms: tuple[str, ...] = ("4", "SCHEDULE 13D")
    feed_count: int = 100  # entries per page of the Form 4 feed
    # For rare forms the SEC takes longer the larger the requested page.
    feed_count_13d: int = 40
    feed_max_pages: int = 5
    # On seeing a P purchase, fetch the issuer's recent Form 4s so cluster_buy can
    # see purchases made before monitoring started.
    backfill_issuer: bool = True


@dataclass(frozen=True)
class AIConfig:
    enabled: bool = True
    model: str = "haiku"
    timeout_seconds: float = 90.0
    max_calls_per_hour: int = 30


@dataclass(frozen=True)
class SourcesConfig:
    """Extra signal sources polled by `radar watch` and `radar serve` (see radar.sources)."""

    # Any of "form144", "eightk", "thirteenf", "short"; an empty list turns them all off.
    enabled: tuple[str, ...] = ("form144", "eightk", "thirteenf", "short")


@dataclass(frozen=True)
class BacktestConfig:
    cost_roundtrip: float = 0.002  # 0.2% round trip
    horizons_months: tuple[int, ...] = (1, 3, 6)
    benchmark: str = "SPY"
    extra_benchmarks: tuple[str, ...] = ("IWM",)
    min_price: float = 5.0
    min_market_cap: float = 300_000_000.0
    # Tolerance (in trading sessions) to find the entry/exit price of the stock.
    price_tolerance_days: int = 5
    # Price reported in the Form 4 vs. market close: outside this range the signal
    # is discarded (reused ticker, typo, another security).
    price_check_min_ratio: float = 0.5
    price_check_max_ratio: float = 2.0
    # Day-over-day jump that betrays a reverse split Yahoo did not adjust: price
    # multiplied by `price_jump_ratio` or more, starting below `price_jump_below`
    # dollars (stocks trading under $1 are the ones that do reverse splits).
    price_jump_ratio: float = 5.0
    price_jump_below: float = 1.0
    # Yahoo blocks bursts: small batches at a steady pace get through unblocked.
    price_batch_size: int = 20
    price_requests_per_second: float = 2.0


@dataclass(frozen=True)
class Settings:
    # Language for AI summaries, alerts and CLI output ("en" or "pt-BR").
    lang: str = DEFAULT_LANG
    data_dir: Path = Path("data")
    reports_dir: Path = Path("reports")
    signals: SignalConfig = field(default_factory=SignalConfig)
    sec: SecConfig = field(default_factory=SecConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    sources: SourcesConfig = field(default_factory=SourcesConfig)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "radar.sqlite"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"


_ENV_LOADED = False


def load_env() -> None:
    """Loads the .env of the current directory (or an ancestor) only once."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    path = find_dotenv(usecwd=True)
    if path:
        load_dotenv(path, override=False)
    _ENV_LOADED = True


def _coerce(current: Any, value: Any, where: str) -> Any:
    if isinstance(current, tuple):
        if not isinstance(value, list | tuple):
            raise ConfigError(f"{where}: expected a list")
        return tuple(value)
    if isinstance(current, bool):
        if not isinstance(value, bool):
            raise ConfigError(f"{where}: expected true/false")
        return value
    if isinstance(current, float):
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ConfigError(f"{where}: expected a number")
        return float(value)
    if isinstance(current, int):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(f"{where}: expected an integer")
        return value
    if isinstance(current, Path):
        return Path(str(value))
    if isinstance(current, str):
        return str(value)
    return value


def _apply(section: Any, data: dict[str, Any], where: str) -> Any:
    known = {f.name for f in fields(section)}
    changes: dict[str, Any] = {}
    for key, value in data.items():
        if key not in known:
            raise ConfigError(f"{where}: unknown key '{key}'")
        current = getattr(section, key)
        if is_dataclass(current):
            if not isinstance(value, dict):
                raise ConfigError(f"{where}.{key}: expected a table")
            changes[key] = _apply(current, value, f"{where}.{key}")
        else:
            changes[key] = _coerce(current, value, f"{where}.{key}")
    return replace(section, **changes)


def load_settings(config_path: Path | None = None) -> Settings:
    """Builds the settings: code defaults → radar.toml → environment variables."""
    load_env()
    settings = Settings()

    path = config_path or Path(os.environ.get("RADAR_CONFIG", "radar.toml"))
    if path.exists():
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{path}: invalid TOML ({exc})") from exc
        settings = _apply(settings, data, str(path))
    elif config_path is not None:
        raise ConfigError(f"Configuration file not found: {path}")

    if data_dir := os.environ.get("RADAR_DATA_DIR"):
        settings = replace(settings, data_dir=Path(data_dir))
    lang = os.environ.get("RADAR_LANG") or settings.lang
    try:
        settings = replace(settings, lang=normalize_lang(lang))
    except ValueError as exc:
        where = "RADAR_LANG" if os.environ.get("RADAR_LANG") else f"{path}: lang"
        raise ConfigError(f"{where}: {exc}") from exc
    return settings


def sec_user_agent() -> str:
    """User-Agent required by the SEC, read from SEC_USER_AGENT. Fails with a clear message."""
    load_env()
    value = os.environ.get("SEC_USER_AGENT", "").strip()
    if not value:
        raise ConfigError(
            "SEC_USER_AGENT is not set. The SEC requires a User-Agent in the format "
            '"Name contact@domain". Copy .env.example to .env and fill it in, for example: '
            'SEC_USER_AGENT="MyProject my-email@domain.com"'
        )
    if "@" not in value or " " not in value:
        raise ConfigError(
            f'Invalid SEC_USER_AGENT ("{value}"). Use the format "Name contact@domain".'
        )
    return value
