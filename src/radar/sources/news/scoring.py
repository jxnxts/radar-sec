"""Hook for scoring news items later (an LLM or any other model). Nothing scores today.

A scorer receives the stored item (with its matches and tags) and returns a small
JSON-able dict (e.g. {"model": "...", "sentiment": 0.4, "relevance": 0.9}) or None.
The poller stores the result in `news_items.score` and in the forward log, next to
the item's `seen_at`, so a score never leaks information the item did not have.
"""

from __future__ import annotations

from typing import Any, Protocol


class NewsScorer(Protocol):
    name: str

    def score(self, item: dict[str, Any]) -> dict[str, Any] | None: ...
