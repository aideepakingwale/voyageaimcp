"""
VoyageAI Reasoning Engine
Orchestrates the full pipeline: MCP calls → LLM → guardrails → retry loop.

Flow:
  1. L1 input guardrail
  2. Score MCP server relevance
  3. Call relevant MCP servers in parallel
  4. Send context + MCP data to LLM waterfall (Groq → Gemini → Anthropic → Template)
  5. L2 output guardrails (schema → factual → business rules)
  6. Confidence scoring (4-signal weighted)
  7. If confidence < 85% → targeted fix → retry (max 3×)
  8. L3 action guardrail (PCI check → human confirm if >£1,000)
  9. Human handoff if all retries exhausted
"""
import json
from config        import Config

try:
    from core.logging_config  import get_logger
    from core.request_context import get_request_id, set_request_id
    _log = get_logger("app")
    _HAS_LOGGER = True
except ImportError:
    _HAS_LOGGER = False
from llm           import get_waterfall
from mcp_servers   import MCP_REGISTRY
from guardrails    import GuardrailOrchestrator
from rag.memory_store import memory_store

from .prompts            import SYSTEM_PROMPT, INTENT_PROMPT, build_fix_hint
from .mcp_scorer         import MCPRelevanceScorer
from .confidence_scorer  import ConfidenceScorer


class ReasoningEngine:
    """
    Single public method: reason(user_message, session_id) → dict
    Everything else is private implementation detail.
    """

    def __init__(self):
        self._waterfall  = get_waterfall()
        self._mcp_scorer = MCPRelevanceScorer()
        self._conf_sc    = ConfidenceScorer()
        self._guardrail  = GuardrailOrchestrator()
        from core.logging_config import get_logger
        self._log = get_logger("reasoning")

    # ── PUBLIC ────────────────────────────────────────────────

    def reason(self, user_message: str, session_id: str) -> dict:
        """
        Full reasoning pipeline with retry loop.
        Returns a structured result dict suitable for JSON serialisation.
        """
        # Ensure trace ID is set for this call chain
        try:
            from core.trace import get_trace_id, set_trace_id, new_trace_id
            if get_trace_id() == "NO-TRACE":
                set_trace_id(new_trace_id())
        except Exception:
            pass

        self._log.info("Reasoning started", extra={
            "session_id":  session_id,
            "message_len": len(user_message),
            "preview":     user_message,   # full message, no truncation
        })
        # Ensure session exists
        if not memory_store.get_session(session_id):
            session_id = memory_store.create_session()

        # Layer 1: Input guardrail
        input_check = self._guardrail.check_input(user_message)
        if not input_check.passed:
            return self._rejected(input_check, session_id)

        memory_store.add_turn(session_id, "user", user_message)

        # Retry loop
        last_result: dict | None = None
        fix_hint:    str         = ""

        for attempt in range(1, Config.MAX_RETRY_ITERATIONS + 1):
            if _HAS_LOGGER:
                _log.info("REASONING ATTEMPT",
                          extra={"request_id": get_request_id(),
                                 "session_id": session_id,
                                 "attempt": attempt,
                                 "fix_hint": fix_hint[:80] if fix_hint else ""})
            try:
                result = self._single_pass(user_message, session_id, attempt, fix_hint)
            except Exception as exc:
                last_result = {"error": str(exc), "attempt": attempt}
                fix_hint    = f"Previous attempt raised: {exc}. Fix and retry."
                continue

            last_result = result
            output_checks = self._guardrail.check_output(
                result["llm_output"], result["mcp_data"]
            )
            failed = [c for c in output_checks if not c.passed]

            if not failed:
                conf = result["confidence"]
                if conf["overall"] >= Config.CONFIDENCE_THRESHOLD:
                    return self._finalise(result, session_id)
                # Below threshold — targeted retry
                fix_hint = self._conf_sc.targeted_fix(conf)
            else:
                fix = failed[0]
                fix_hint = f"Layer {fix.layer} failed: {fix.reason}. {self._fix_for_layer(fix.layer)}"

        # All retries exhausted
        if _HAS_LOGGER:
            _log.warning("HUMAN HANDOFF",
                         extra={"request_id": get_request_id(),
                                "session_id": session_id,
                                "reason": "max retries exhausted"})
        return self._human_handoff(last_result, session_id)

    # ── PRIVATE: SINGLE PASS ──────────────────────────────────

    def _single_pass(self, user_message: str, session_id: str,
                     attempt: int, fix_hint: str) -> dict:
        """One full reasoning pass: MCP → LLM → confidence."""

        self._log.info("Reasoning attempt %d", attempt, extra={
            "session_id": session_id, "attempt": attempt,
            "fix_hint": fix_hint[:100] if fix_hint else None,
        })
        # Score which MCP servers are relevant
        relevance = self._mcp_scorer.score_all(user_message)

        # Get origin airport: from session (user-provided) → detected → LHR
        entities      = memory_store.retrieve_all_entities(session_id)
        origin_iata   = (entities.get("origin_iata")
                         or entities.get("detected_origin_iata")
                         or "LHR")

        mcp_params = self._mcp_scorer.build_params(user_message, session_id,
                                                    origin_iata=origin_iata)

        # Call relevant MCP servers
        mcp_data = {}
        for name, score in relevance.items():
            srv = MCP_REGISTRY.get(name)
            if srv:
                params = mcp_params.get(name, {})
                result = srv.call(params)
                mcp_data[name] = {**result, "relevance": score}

        # RAG context
        context    = memory_store.build_context_summary(session_id)
        rag_recall = self._estimate_rag_recall(session_id)

        # Build prompt
        user_prompt = INTENT_PROMPT.format(
            user_message=user_message,
            context=context,
            mcp_data=self._mcp_scorer.summarise_mcp(mcp_data),
            fix_hint=build_fix_hint(fix_hint),
        )

        # LLM call via waterfall
        llm_resp = self._waterfall.complete(SYSTEM_PROMPT, user_prompt)
        if not llm_resp.success:
            raise RuntimeError(f"LLM waterfall exhausted: {llm_resp.error}")

        llm_output = json.loads(llm_resp.text)
        self._store_entities(session_id, llm_output)

        # Confidence scoring
        llm_scores = llm_output.get("confidence_scores", {})
        confidence = self._conf_sc.compute(llm_scores, mcp_data, rag_recall)

        self._log.info("Reasoning pass complete", extra={
            "attempt":      attempt,
            "provider":     llm_resp.provider,
            "model":        llm_resp.model,
            "latency_ms":   llm_resp.latency_ms,
            "overall_conf": confidence.get("overall", 0),
            "passed":       confidence.get("passed", False),
            "dest":         llm_output.get("intent", {}).get("destination", ""),
            "total_cost_gbp": llm_output.get("total_cost_gbp", 0),
        })
        return {
            "session_id":     session_id,
            "attempt":        attempt,
            "llm_provider":   llm_resp.provider,
            "llm_model":      llm_resp.model,
            "llm_latency_ms": llm_resp.latency_ms,
            "llm_cost_usd":   llm_resp.cost_usd,
            "llm_output":     llm_output,
            "mcp_data":       mcp_data,
            "relevance":      relevance,
            "confidence":     confidence,
            "status":         "processing",
        }

    # ── PRIVATE: FINALISE ─────────────────────────────────────

    def _finalise(self, result: dict, session_id: str) -> dict:
        """Apply Layer 3 action guardrail and return final result."""
        session      = memory_store.get_session(session_id) or {}
        action_check = self._guardrail.check_action(
            result["llm_output"],
            result["confidence"]["overall"],
            session,
        )
        result["action_check"] = {
            "passed": action_check.passed,
            "action": action_check.action,
            "reason": action_check.reason,
            "data":   action_check.data,
        }
        result["status"] = (
            "awaiting_confirmation" if action_check.action == "human_confirm"
            else "ready"
        )
        if _HAS_LOGGER:
            _log.info("REASONING COMPLETE",
                      extra={"request_id": get_request_id(),
                             "session_id": session_id,
                             "status": result["status"],
                             "provider": result.get("llm_provider",""),
                             "confidence": result.get("confidence",{}).get("overall",0),
                             "attempt": result.get("attempt",1)})
        memory_store.add_turn(
            session_id, "assistant",
            result["llm_output"].get("summary", ""),
        )
        return result

    # ── PRIVATE: HELPERS ──────────────────────────────────────

    def _store_entities(self, sid: str, output: dict):
        """Persist extracted intent entities to RAG memory."""
        intent  = output.get("intent", {})
        overall = output.get("confidence_scores", {}).get("overall", 0.70)
        for key, val in intent.items():
            if val:
                memory_store.store_entity(sid, key, val, confidence=overall)

    def _estimate_rag_recall(self, sid: str) -> float:
        """Estimate RAG quality from entity count in session."""
        entities = memory_store.retrieve_all_entities(sid)
        return round(min(0.98, 0.65 + 0.05 * len(entities)), 3)

    def _fix_for_layer(self, layer: str) -> str:
        if "SCHEMA"  in layer: return "Return valid JSON exactly matching the schema."
        if "FACTUAL" in layer: return "Use only MCP-verified prices and IATA codes."
        if "BUSINESS"in layer: return "Respect budget cap and future date constraints."
        return "Review and correct the output carefully."

    def _rejected(self, check, session_id: str) -> dict:
        return {
            "session_id": session_id,
            "status":     "rejected",
            "guardrail":  check.layer,
            "reason":     check.reason,
            "message":    check.data or check.reason,
            "confidence": {"overall": 0.0, "passed": False},
        }

    def _human_handoff(self, last_result: dict | None, session_id: str) -> dict:
        self._log.warning("Human handoff triggered", extra={
            "session_id":  session_id,
            "max_attempts":Config.MAX_RETRY_ITERATIONS,
            "last_conf":   (last_result or {}).get("confidence",{}).get("overall",0),
        })
        return {
            "session_id":  session_id,
            "status":      "human_handoff",
            "reason":      f"Could not reach {Config.CONFIDENCE_THRESHOLD:.0%} "
                           f"after {Config.MAX_RETRY_ITERATIONS} attempts",
            "last_result": last_result,
            "message":     "AI couldn't complete this booking with sufficient confidence. Connecting you to a specialist.",
            "confidence":  (last_result or {}).get("confidence", {"overall": 0.0}),
        }
