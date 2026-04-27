"""
Guardrail Orchestrator — runs all three layers in sequence.
Import this; do not import individual guards directly from routes.
"""
from .types          import GuardrailResult
from .input_guard    import InputGuardrail
from .schema_guard   import SchemaGuardrail
from .factual_guard  import FactualGuardrail
from .business_guard import BusinessRulesGuardrail
from .action_guard   import ActionGuardrail


class GuardrailOrchestrator:
    """
    Layer 1  — Input:    sanitise before LLM sees it
    Layer 2a — Schema:   validate JSON structure
    Layer 2b — Factual:  cross-check claims vs MCP data
    Layer 2c — Business: enforce travel domain rules
    Layer 3  — Action:   final gate before GDS transaction
    """

    def __init__(self):
        self._input    = InputGuardrail()
        self._schema   = SchemaGuardrail()
        self._factual  = FactualGuardrail()
        self._business = BusinessRulesGuardrail()
        self._action   = ActionGuardrail()

    def check_input(self, text: str) -> GuardrailResult:
        return self._input.validate(text)

    def check_output(self, llm_output: dict, mcp_data: dict = None) -> list:
        """Run L2a → L2b → L2c. Stops on first failure."""
        results = []

        r = self._schema.validate(llm_output)
        results.append(r)
        if not r.passed:
            return results

        r2 = self._factual.verify(llm_output, mcp_data or {})
        results.append(r2)
        if not r2.passed:
            return results

        r3 = self._business.validate(llm_output)
        results.append(r3)
        return results

    def check_action(self, llm_output: dict,
                     confidence: float, session: dict) -> GuardrailResult:
        return self._action.gate(llm_output, confidence, session)


__all__ = ["GuardrailOrchestrator", "GuardrailResult"]
