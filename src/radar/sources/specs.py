"""Every signal type of the extra sources, with the pre-registered test periods."""

from __future__ import annotations

from datetime import date

from .base import AVOID, LONG, SignalSpec
from .eightk import rules as eightk_rules
from .form144 import rules as form144_rules
from .short import rules as short_rules
from .thirteenf import rules as thirteenf_rules

SPECS: dict[str, SignalSpec] = {
    **eightk_rules.SPECS,
    **form144_rules.SPECS,
    **thirteenf_rules.SPECS,
    **short_rules.SPECS,
}
TESTED = [k for k, s in SPECS.items() if s.direction in (LONG, AVOID)]
# Form 144 is electronic only since 2023-04-13: no train period (see the plan).
FORM144_PERIOD = (date(2023, 5, 1), date(2025, 12, 31))
FORM144_HALVES = ((date(2023, 5, 1), date(2024, 6, 30)), (date(2024, 7, 1), date(2025, 12, 31)))
