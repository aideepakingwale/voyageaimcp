"""
Guardrail Orchestrator — runs all three layers in sequence.
Import this; do not import individual guards directly from routes.
"""
from .types          import GuardrailResult

try:
    from core.logging_config  import get_logger
    from core.request_context import get_request_id
    _log = get_logger("guardrails")
    _HAS_LOGGER = True
except ImportError:
    _HAS_LOGGER = False
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
        from core.logging_config import get_logger
        self._log = get_logger("guardrails")

    def check_input(self, text: str) -> GuardrailResult:
        result = self._input.validate(text)
        if _HAS_LOGGER:
            level = _log.warning if not result.passed else _log.debug
            level("L1 INPUT CHECK",
                  extra={"request_id": get_request_id(),
                         "passed": result.passed,
                         "action": result.action,
                         "reason": result.reason or "ok",
                         "input_preview": text[:80]})
        return result

    def check_output(self, llm_output: dict, mcp_data: dict = None) -> list:
        """Run L2a → L2b → L2c. Stops on first failure."""
        results = []

        r = self._schema.validate(llm_output)
        results.append(r)
        if _HAS_LOGGER:
            (_log.warning if not r.passed else _log.debug)("L2a SCHEMA",
                extra={"request_id": get_request_id(),
                       "passed": r.passed, "reason": r.reason or "ok",
                       "failed_fields": r.failed_fields})
        if not r.passed:
            return results

        r2 = self._factual.verify(llm_output, mcp_data or {})
        results.append(r2)
        if _HAS_LOGGER:
            (_log.warning if not r2.passed else _log.debug)("L2b FACTUAL",
                extra={"request_id": get_request_id(),
                       "passed": r2.passed, "reason": r2.reason or "ok"})
        if not r2.passed:
            return results

        r3 = self._business.validate(llm_output)
        results.append(r3)
        if _HAS_LOGGER:
            (_log.warning if not r3.passed else _log.debug)("L2c BUSINESS",
                extra={"request_id": get_request_id(),
                       "passed": r3.passed, "reason": r3.reason or "ok"})
        return results

    def check_action(self, llm_output: dict,
                     confidence: float, session: dict) -> GuardrailResult:
        result = self._action.gate(llm_output, confidence, session)
        if _HAS_LOGGER:
            level = _log.warning if not result.passed else _log.info
            level("L3 ACTION",
                  extra={"request_id": get_request_id(),
                         "passed": result.passed,
                         "action": result.action,
                         "confidence": confidence,
                         "reason": result.reason or "ok"})
        return result


__all__ = ["GuardrailOrchestrator", "GuardrailResult"]
