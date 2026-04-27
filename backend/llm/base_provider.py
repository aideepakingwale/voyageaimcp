"""Base LLM provider interface."""
from dataclasses import dataclass, field
from abc import ABC, abstractmethod


@dataclass
class LLMResponse:
    success:       bool
    provider:      str
    model:         str   = ""
    text:          str   = ""
    error:         str   = ""
    input_tokens:  int   = 0
    output_tokens: int   = 0
    cost_usd:      float = 0.0
    latency_ms:    float = 0.0


class BaseProvider(ABC):
    name = "base"
    free = False

    def __init__(self, api_key: str = ""):
        self.api_key    = api_key
        self.last_error = ""
        self.call_count = 0
        self.total_cost = 0.0

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def complete(self, system: str, user: str,
                 max_tokens: int, temperature: float) -> LLMResponse: ...
