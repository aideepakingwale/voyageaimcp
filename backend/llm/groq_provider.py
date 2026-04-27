"""
Groq Provider — FREE tier
Models: llama-3.1-70b-versatile, mixtral-8x7b-32768
Limits: 14,400 req/day, 500,000 tok/day (free)
Speed:  ~500 tokens/second (fastest available)
Signup: console.groq.com
"""
import json
from .base_provider import BaseProvider, LLMResponse

try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False


class GroqProvider(BaseProvider):

    name = "groq"
    free = True

    MODELS = [
        "llama-3.1-70b-versatile",
        "mixtral-8x7b-32768",
        "llama-3.1-8b-instant",
        "gemma2-9b-it",
    ]

    def __init__(self, api_key: str, model: str, fallback_model: str):
        super().__init__(api_key)
        self.model         = model
        self.fallback_model = fallback_model
        self.client        = None
        if GROQ_AVAILABLE and api_key:
            try:
                self.client = Groq(api_key=api_key)
            except Exception as e:
                self.last_error = str(e)

    def is_available(self) -> bool:
        return GROQ_AVAILABLE and bool(self.api_key) and self.client is not None

    def complete(self, system: str, user: str,
                 max_tokens: int = 2048, temperature: float = 0.1) -> LLMResponse:

        if not self.is_available():
            return LLMResponse(
                success=False, provider=self.name,
                error="Groq not available (no key or SDK not installed)"
            )

        # Try primary model, then fallback
        for model in [self.model, self.fallback_model]:
            try:
                resp = self.client.chat.completions.create(
                    model       = model,
                    messages    = [
                        {"role": "system",  "content": system},
                        {"role": "user",    "content": user},
                    ],
                    max_tokens  = max_tokens,
                    temperature = temperature,
                    timeout     = 20,
                )
                text = resp.choices[0].message.content
                return LLMResponse(
                    success        = True,
                    provider       = self.name,
                    model          = model,
                    text           = text,
                    input_tokens   = resp.usage.prompt_tokens,
                    output_tokens  = resp.usage.completion_tokens,
                    cost_usd       = 0.0,   # FREE
                )
            except Exception as e:
                self.last_error = str(e)
                # Rate limit or context error — try fallback model
                if "rate_limit" in str(e).lower() or "context" in str(e).lower():
                    continue
                # Other errors — fail immediately
                return LLMResponse(
                    success=False, provider=self.name,
                    model=model, error=str(e)
                )

        return LLMResponse(
            success=False, provider=self.name,
            error=f"All Groq models failed: {self.last_error}"
        )
