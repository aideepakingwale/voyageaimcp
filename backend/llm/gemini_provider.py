"""
Gemini Provider — FREE tier
Uses google-genai (the new SDK replacing google-generativeai).
Models: gemini-1.5-flash, gemini-1.5-pro
Limits: 15 req/min, 1M tok/day (free via AI Studio)
Signup: aistudio.google.com (Google account, no credit card)
"""
from .base_provider import BaseProvider, LLMResponse

# Try new SDK first, fall back to legacy
try:
    from google import genai as _genai
    from google.genai import types as _types
    _SDK = "new"
except ImportError:
    try:
        import google.generativeai as _genai_legacy  # noqa: F401
        _SDK = "legacy"
    except ImportError:
        _SDK = None


class GeminiProvider(BaseProvider):

    name = "gemini"
    free = True

    def __init__(self, api_key: str, model: str, pro_model: str):
        super().__init__(api_key)
        self.model     = model
        self.pro_model = pro_model
        self._ready    = False

        if _SDK and api_key:
            try:
                if _SDK == "new":
                    self._client = _genai.Client(api_key=api_key)
                else:
                    import google.generativeai as lg
                    lg.configure(api_key=api_key)
                    self._client = lg
                self._ready = True
            except Exception as e:
                self.last_error = str(e)

    def is_available(self) -> bool:
        return bool(_SDK and self.api_key and self._ready)

    def complete(self, system: str, user: str,
                 max_tokens: int = 2048, temperature: float = 0.1) -> LLMResponse:

        if not self.is_available():
            return LLMResponse(
                success=False, provider=self.name,
                error="Gemini not available (no key or SDK not installed — pip install google-genai)"
            )

        full_prompt = f"{system}\n\n{user}"

        for model_name in [self.model, self.pro_model]:
            try:
                if _SDK == "new":
                    resp = self._client.models.generate_content(
                        model=model_name,
                        contents=full_prompt,
                        config=_types.GenerateContentConfig(
                            max_output_tokens=max_tokens,
                            temperature=temperature,
                        ),
                    )
                    text    = resp.text
                    in_tok  = getattr(resp.usage_metadata, "prompt_token_count", 0)
                    out_tok = getattr(resp.usage_metadata, "candidates_token_count", 0)
                else:
                    # Legacy SDK
                    m    = self._client.GenerativeModel(
                        model_name=model_name,
                        system_instruction=system,
                    )
                    resp = m.generate_content(user)
                    text    = resp.text
                    in_tok  = getattr(resp.usage_metadata, "prompt_token_count", 0)
                    out_tok = getattr(resp.usage_metadata, "candidates_token_count", 0)

                return LLMResponse(
                    success=True, provider=self.name, model=model_name,
                    text=text, input_tokens=in_tok, output_tokens=out_tok,
                    cost_usd=0.0,
                )

            except Exception as e:
                self.last_error = str(e)
                err_lower = str(e).lower()
                if any(x in err_lower for x in ["quota", "rate", "429", "resource", "exhausted"]):
                    continue   # try next model
                return LLMResponse(
                    success=False, provider=self.name,
                    model=model_name, error=str(e),
                )

        return LLMResponse(
            success=False, provider=self.name,
            error=f"All Gemini models exhausted: {self.last_error}",
        )
