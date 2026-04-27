"""Shared guardrail types."""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class GuardrailResult:
    passed:        bool
    layer:         str
    reason:        str  = ""
    action:        str  = "proceed"   # proceed|reject|retry|block|human_confirm
    failed_fields: list = field(default_factory=list)
    data:          Any  = None
