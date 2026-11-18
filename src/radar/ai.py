"""AI access through the Claude Agent SDK, with a synchronous, failure-proof interface.

The SDK runs Claude Code under the hood and uses the machine's logged-in session
(the user's subscription). No environment variable is needed; whoever runs on a
server without a login can set `CLAUDE_CODE_OAUTH_TOKEN`.

`ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` never reach the subprocess: if they
did, they would take precedence over the subscription and the call would be
billed through the API.

Any problem (SDK missing, not logged in, quota exhausted, timeout) becomes an
`AIError`, and the caller decides what to do. This module never brings the
program down.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager

from radar.i18n import DEFAULT_LANG, t

log = logging.getLogger(__name__)

# API credentials that would divert billing from the subscription to the paid API.
BLOCKED_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


def system_prompt(lang: str = DEFAULT_LANG) -> str:
    """System prompt asking for a summary in `lang`."""
    return t("ai.system_prompt", lang)


SYSTEM_PROMPT = system_prompt()


class AIError(RuntimeError):
    """The AI did not answer in a usable way; the message says why."""


@contextmanager
def _without_api_credentials() -> Iterator[None]:
    """Removes the API credentials from the environment while the SDK spawns the subprocess.

    The SDK builds Claude Code's environment from `os.environ`, and its `env`
    option only adds variables, never removes them. So the removal happens here,
    and is undone right after.
    """
    saved = {name: os.environ.pop(name) for name in BLOCKED_ENV if name in os.environ}
    try:
        yield
    finally:
        os.environ.update(saved)


async def _ask(prompt: str, *, model: str, system_prompt: str) -> str:
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        model=model,
        max_turns=1,
        tools=[],  # no built-in tools: the filing text already goes in the prompt
        allowed_tools=[],
        setting_sources=[],  # do not load the user's CLAUDE.md, skills or hooks
        extra_args={"no-session-persistence": None},  # keeps the session history clean
    )

    result: ResultMessage | None = None
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, ResultMessage):
            result = message

    if result is None:
        raise AIError("the SDK finished without returning a result")
    if result.is_error or result.subtype != "success":
        detail = "; ".join(result.errors or []) or (result.result or "").strip()[:200]
        raise AIError(f"result with error ({result.subtype})" + (f": {detail}" if detail else ""))
    text = (result.result or "").strip()
    if not text:
        raise AIError("empty answer")
    return text


def generate(
    prompt: str,
    *,
    model: str = "haiku",
    timeout: float = 90.0,
    system_prompt: str = SYSTEM_PROMPT,
) -> str:
    """Sends `prompt` to the model and returns the text. Raises `AIError` on any failure."""
    try:
        import claude_agent_sdk  # noqa: F401
    except ImportError as exc:
        raise AIError("package claude-agent-sdk is not installed") from exc

    async def run() -> str:
        return await asyncio.wait_for(
            _ask(prompt, model=model, system_prompt=system_prompt), timeout=timeout
        )

    try:
        with _without_api_credentials():
            return asyncio.run(run())
    except AIError:
        raise
    except TimeoutError as exc:
        raise AIError(f"timed out after {timeout:.0f}s") from exc
    except Exception as exc:  # the SDK can fail in many ways; none may leak
        raise AIError(f"{exc.__class__.__name__}: {str(exc)[:300]}") from exc
