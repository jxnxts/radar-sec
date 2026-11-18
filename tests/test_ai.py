"""The AI is always simulated: no test calls the real SDK or uses a login or token."""

import asyncio
import os
import sys
import types
from dataclasses import dataclass, field
from datetime import date

import pytest

from radar import ai
from radar.config import AIConfig
from radar.db import Database
from radar.models import Signal
from radar.summary import Summarizer, build_prompt, localized_summaries, template_summary


@dataclass
class FakeResult:
    result: str | None = "Generated summary."
    subtype: str = "success"
    is_error: bool = False
    errors: list[str] = field(default_factory=list)


@pytest.fixture
def fake_sdk(monkeypatch):
    """Puts a fake claude_agent_sdk in place of the real one and records its use."""
    state = types.SimpleNamespace(
        calls=[], env_seen=[], messages=[FakeResult()], raises=None, delay=0.0
    )

    class Options:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    async def query(*, prompt, options=None):
        state.calls.append((prompt, options.kwargs))
        state.env_seen.append({k: os.environ.get(k) for k in ai.BLOCKED_ENV})
        if state.delay:
            await asyncio.sleep(state.delay)
        if state.raises:
            raise state.raises
        yield "intermediate message that must be ignored"
        for message in state.messages:
            yield message

    module = types.ModuleType("claude_agent_sdk")
    module.ClaudeAgentOptions = Options
    module.ResultMessage = FakeResult
    module.query = query
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", module)
    return state


def test_generate_returns_the_result_text(fake_sdk):
    assert ai.generate("summarize this") == "Generated summary."
    prompt, options = fake_sdk.calls[0]
    assert prompt == "summarize this"
    assert options["model"] == "haiku"
    assert options["max_turns"] == 1
    assert options["tools"] == [] and options["allowed_tools"] == []  # no tools
    assert options["setting_sources"] == []  # no user CLAUDE.md or skills
    assert "in English" in options["system_prompt"]


def test_system_prompt_follows_the_language(fake_sdk):
    ai.generate("x", system_prompt=ai.system_prompt("pt-BR"))
    assert "português do Brasil" in fake_sdk.calls[0][1]["system_prompt"]
    assert "in English" in ai.system_prompt("en")


def test_model_is_configurable(fake_sdk):
    ai.generate("x", model="sonnet")
    assert fake_sdk.calls[0][1]["model"] == "sonnet"


def test_api_credentials_never_reach_the_sdk(fake_sdk, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key-that-would-bill-the-api")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "another-token")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "subscription-token")

    ai.generate("x")

    assert fake_sdk.env_seen == [{"ANTHROPIC_API_KEY": None, "ANTHROPIC_AUTH_TOKEN": None}]
    # After the call the process environment is back to what it was.
    assert os.environ["ANTHROPIC_API_KEY"] == "key-that-would-bill-the-api"
    assert os.environ["ANTHROPIC_AUTH_TOKEN"] == "another-token"
    assert os.environ["CLAUDE_CODE_OAUTH_TOKEN"] == "subscription-token"


def test_environment_is_restored_even_when_the_sdk_fails(fake_sdk, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
    fake_sdk.raises = RuntimeError("CLI crashed")
    with pytest.raises(ai.AIError):
        ai.generate("x")
    assert os.environ["ANTHROPIC_API_KEY"] == "key"


def test_works_without_any_token(fake_sdk):
    # The default is the logged-in Claude Code session: no variable is required.
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in os.environ
    assert ai.generate("x") == "Generated summary."


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (
            FakeResult(is_error=True, subtype="error_during_execution", errors=["not logged in"]),
            "not logged in",
        ),
        (FakeResult(subtype="error_max_turns"), "error_max_turns"),
        (FakeResult(result="   "), "empty"),
    ],
)
def test_unusable_results_become_ai_errors(fake_sdk, result, expected):
    fake_sdk.messages = [result]
    with pytest.raises(ai.AIError, match=expected):
        ai.generate("x")


def test_no_result_message_is_an_error(fake_sdk):
    fake_sdk.messages = []
    with pytest.raises(ai.AIError, match="without returning a result"):
        ai.generate("x")


def test_sdk_exceptions_become_ai_errors(fake_sdk):
    fake_sdk.raises = RuntimeError("usage limit reached")
    with pytest.raises(ai.AIError, match="usage limit reached"):
        ai.generate("x")


def test_timeout_becomes_ai_error(fake_sdk):
    fake_sdk.delay = 5
    with pytest.raises(ai.AIError, match="timed out"):
        ai.generate("x", timeout=0.05)


def test_missing_sdk_becomes_ai_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", None)
    with pytest.raises(ai.AIError, match="not installed"):
        ai.generate("x")


# ------------------------------------------------------------------- summary


def cluster_signal() -> Signal:
    return Signal(
        type="cluster_buy",
        dedupe_key="cluster_buy:1:2026-11-17",
        issuer_cik="1",
        issuer_name="Example Corp",
        ticker="EXM",
        signal_date=date(2026, 11, 17),
        score=74.0,
        explanation="2 distinct insiders bought $300K.",
        trigger_accession="0000000001-26-000001",
        details={
            "insiders": [
                {"name": "Ana Souza", "role": "CEO", "value": 200_000},
                {"name": "Rui Lima", "role": "Director/Officer", "value": 100_000},
            ],
            "n_insiders": 2,
            "total_value": 300_000,
            "avg_price": 12.5,
            "first_buy": "2026-11-12",
            "last_buy": "2026-11-16",
        },
    )


def officer_signal() -> Signal:
    return Signal(
        type="big_officer_buy",
        dedupe_key="big_officer_buy:1:2026-11-17",
        issuer_cik="1",
        issuer_name="Example Corp",
        ticker="EXM",
        signal_date=date(2026, 11, 17),
        score=70.0,
        explanation="CEO bought $400K.",
        trigger_accession="0000000001-26-000002",
        details={
            "insider": "Ana Souza",
            "role": "CEO",
            "total_value": 400_000,
            "shares": 32_000,
            "avg_price": 12.5,
            "last_buy": "2026-11-16",
            "stake_increase": 0.2,
        },
    )


def activist_signal() -> Signal:
    return Signal(
        type="activist_13d",
        dedupe_key="activist_13d:1:2026-11-17",
        issuer_cik="1",
        issuer_name="Example Corp",
        ticker="EXM",
        signal_date=date(2026, 11, 17),
        score=65.0,
        explanation="Fund filed a 13D with 8.20%.",
        trigger_accession="0000000001-26-000003",
        details={
            "filer": "Activist Fund LP",
            "percent": 8.2,
            "shares": 1_000_000,
            "event_date": "2026-11-10",
            "activist_tone": True,
            "purpose": "We intend to nominate directors.",
        },
    )


@pytest.mark.parametrize("factory", [cluster_signal, officer_signal, activist_signal])
def test_template_summary_is_three_to_five_lines_in_both_languages(factory):
    lines = template_summary(factory()).splitlines()
    assert 3 <= len(lines) <= 5
    assert lines[0].startswith("Who:") and lines[1].startswith("How much:")
    assert lines[2].startswith("Context:")
    lines = template_summary(factory(), "pt-BR").splitlines()
    assert 3 <= len(lines) <= 5
    assert lines[0].startswith("Quem:") and lines[1].startswith("Quanto:")
    assert lines[2].startswith("Contexto:")


def test_template_summary_texts():
    assert template_summary(cluster_signal()) == (
        "Who: 2 insiders at Example Corp (EXM) — Ana Souza (CEO), Rui Lima (Director/Officer).\n"
        "How much: $300K in open-market buys, average price $12.50.\n"
        "Context: buys between Nov 12, 2026 and Nov 16, 2026; signal public on Nov 17, 2026.\n"
        "Several insiders buying together with their own money is the pattern this rule looks for."
    )
    assert template_summary(cluster_signal(), "pt-BR") == (
        "Quem: 2 insiders de Example Corp (EXM) — Ana Souza (CEO), Rui Lima (diretor/executivo).\n"
        "Quanto: US$ 300 mil em compras a mercado, preço médio US$ 12,50.\n"
        "Contexto: compras entre 12/11/2026 e 16/11/2026; sinal público em 17/11/2026.\n"
        "Vários insiders comprando juntos com dinheiro próprio é o padrão que a regra procura."
    )
    assert template_summary(officer_signal()).splitlines()[-1] == "The officer's stake grew 20.0%."
    assert template_summary(activist_signal(), "pt-BR").splitlines()[1] == (
        "Quanto: 8,20% da empresa (1.000.000 ações)."
    )


def test_localized_summaries_prefer_cached_ai_text_per_language():
    texts, sources = localized_summaries(cluster_signal(), {"pt-BR": "Resumo da IA."})
    assert texts["pt-BR"] == "Resumo da IA." and sources["pt-BR"] == "ai"
    assert texts["en"] == template_summary(cluster_signal()) and sources["en"] == "template"


def test_prompt_carries_the_filing_text_as_data():
    prompt = build_prompt(activist_signal(), {"issuer": "Example Corp"})
    assert "3 to 5 short lines" in prompt
    assert "<filing>" in prompt and "</filing>" in prompt
    assert "We intend to nominate directors." in prompt
    assert "Example Corp" in prompt
    assert '"purpose"' not in prompt.split("<filing>")[0]  # the purpose goes as filing text


def test_prompt_follows_the_language():
    prompt = build_prompt(activist_signal(), None, "pt-BR")
    assert "3 a 5 linhas" in prompt and "(sem texto adicional)" not in prompt
    assert "Item 4 (propósito da transação):" in prompt


@pytest.fixture
def db():
    with Database(":memory:") as database:
        yield database


def test_summarizer_uses_ai_and_caches_by_accession(db):
    calls = []

    def generate(prompt, *, model, timeout, system_prompt):
        calls.append((model, timeout, "in English" in system_prompt))
        return "AI summary."

    summarizer = Summarizer(db, AIConfig(model="haiku", timeout_seconds=42), generate=generate)
    first = summarizer.summarize(cluster_signal())
    again = summarizer.summarize(cluster_signal())

    assert (first.summary, first.summary_source) == ("AI summary.", "ai")
    assert again.summary == "AI summary."
    assert calls == [("haiku", 42, True)]  # the second time came from the cache, no quota spent
    assert db.ai_calls_last_hour() == 1
    assert summarizer.stored(first) == ("AI summary.", "ai")


def test_summarizer_caches_per_language(db):
    prompts = []

    def generate(prompt, *, model, timeout, system_prompt):
        prompts.append((prompt, system_prompt))
        return "Resumo da IA."

    summarizer = Summarizer(db, AIConfig(), lang="pt-BR", generate=generate)
    signal = summarizer.summarize(cluster_signal())
    assert (signal.summary, signal.summary_source) == ("Resumo da IA.", "ai")
    assert "português do Brasil" in prompts[0][1] and "Resuma o sinal" in prompts[0][0]
    accession, kind = signal.trigger_accession, signal.type
    assert db.cached_ai_summary(accession, kind, "pt-BR") == "Resumo da IA."
    assert db.cached_ai_summary(accession, kind, "en") is None
    assert db.cached_ai_summaries(accession, kind) == {"pt-BR": "Resumo da IA."}
    # The English column falls back to the template: no extra AI call.
    assert summarizer.stored(signal) == (template_summary(signal, "en"), "template")
    assert len(prompts) == 1


def test_summarizer_falls_back_to_template_when_ai_fails(db, caplog):
    def generate(prompt, **kwargs):
        raise ai.AIError("not logged in to Claude Code")

    signal = Summarizer(db, AIConfig(), generate=generate).summarize(cluster_signal())
    assert signal.summary_source == "template"
    assert signal.summary == template_summary(cluster_signal())
    assert "not logged in to Claude Code" in caplog.text  # the reason is logged
    assert db.cached_ai_summary(signal.trigger_accession, signal.type) is None


def test_summarizer_survives_unexpected_exceptions(db):
    def generate(prompt, **kwargs):
        raise ValueError("something nobody foresaw")

    signal = Summarizer(db, AIConfig(), generate=generate).summarize(officer_signal())
    assert signal.summary_source == "template" and signal.summary


def test_summarizer_respects_the_hourly_cap(db, caplog):
    calls = []

    def generate(prompt, **kwargs):
        calls.append(prompt)
        return "AI"

    summarizer = Summarizer(db, AIConfig(max_calls_per_hour=2), generate=generate)
    sources = []
    for i in range(4):
        signal = cluster_signal()
        signal.trigger_accession = f"acc-{i}"
        sources.append(summarizer.summarize(signal).summary_source)

    assert sources == ["ai", "ai", "template", "template"]
    assert len(calls) == 2
    assert caplog.text.count("hourly cap of 2 calls") == 1  # warns only once


def test_failed_calls_also_count_towards_the_cap(db):
    def generate(prompt, **kwargs):
        raise ai.AIError("quota exhausted")

    summarizer = Summarizer(db, AIConfig(max_calls_per_hour=3), generate=generate)
    for i in range(5):
        signal = cluster_signal()
        signal.trigger_accession = f"acc-{i}"
        summarizer.summarize(signal)
    assert db.ai_calls_last_hour() == 3  # stopped insisting once the cap was hit


def test_summarizer_disabled_never_calls_ai(db):
    def generate(prompt, **kwargs):
        raise AssertionError("should not call the AI")

    signal = Summarizer(db, AIConfig(enabled=False), generate=generate).summarize(cluster_signal())
    assert signal.summary_source == "template"
    assert db.ai_calls_last_hour() == 0


def test_options_are_valid_for_the_installed_sdk(monkeypatch):
    """Uses the real SDK classes (only the call is simulated) to catch API changes."""
    import claude_agent_sdk

    seen = {}

    async def fake_query(*, prompt, options=None):
        seen["options"] = options
        yield claude_agent_sdk.ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="s",
            result="Real summary.",
        )

    monkeypatch.setattr(claude_agent_sdk, "query", fake_query)

    assert ai.generate("summarize", model="haiku") == "Real summary."
    options = seen["options"]
    assert isinstance(options, claude_agent_sdk.ClaudeAgentOptions)
    assert options.model == "haiku" and options.max_turns == 1
    assert options.tools == [] and options.allowed_tools == []
    assert options.setting_sources == []
    assert options.extra_args == {"no-session-persistence": None}
