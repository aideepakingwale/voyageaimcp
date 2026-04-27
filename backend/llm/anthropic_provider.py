"""
Anthropic Provider — Paid fallback
Using claude-haiku (cheapest: ~$0.0025/1K tokens)
Only fires if Groq and Gemini both fail.
"""
from .base_provider import BaseProvider, LLMResponse

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False


class AnthropicProvider(BaseProvider):

    name = "anthropic"
    free = False

    def __init__(self, api_key: str, model: str):
        super().__init__(api_key)
        self.model  = model
        self.client = None
        if ANTHROPIC_AVAILABLE and api_key:
            try:
                self.client = anthropic.Anthropic(api_key=api_key)
            except Exception as e:
                self.last_error = str(e)

    def is_available(self) -> bool:
        return ANTHROPIC_AVAILABLE and bool(self.api_key) and self.client is not None

    def complete(self, system: str, user: str,
                 max_tokens: int = 2048, temperature: float = 0.1) -> LLMResponse:

        if not self.is_available():
            return LLMResponse(
                success=False, provider=self.name,
                error="Anthropic not available (no key or SDK missing)"
            )
        try:
            resp = self.client.messages.create(
                model      = self.model,
                max_tokens = max_tokens,
                system     = system,
                messages   = [{"role": "user", "content": user}],
            )
            text   = resp.content[0].text
            in_tok = resp.usage.input_tokens
            out_tok= resp.usage.output_tokens
            # Haiku pricing: $0.00025/1K input, $0.00125/1K output
            cost   = (in_tok / 1000 * 0.00025) + (out_tok / 1000 * 0.00125)

            return LLMResponse(
                success       = True,
                provider      = self.name,
                model         = self.model,
                text          = text,
                input_tokens  = in_tok,
                output_tokens = out_tok,
                cost_usd      = round(cost, 6),
            )
        except Exception as e:
            self.last_error = str(e)
            return LLMResponse(
                success=False, provider=self.name,
                model=self.model, error=str(e)
            )
