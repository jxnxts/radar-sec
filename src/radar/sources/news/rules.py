"""News signal rules. Phase 1 only collects: no news item fires a signal yet.

When a rule is added (from tags, a score or both), it goes here as a pure function
with its `SignalSpec`, like the other sources, so the backtest can replay it from the
forward log with each item's `seen_at`.
"""

from __future__ import annotations

from ..base import SignalSpec

SPECS: dict[str, SignalSpec] = {}
