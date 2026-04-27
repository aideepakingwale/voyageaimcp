"""
VoyageAI Confidence Scorer
Four-signal weighted aggregation pipeline.

Signal weights:
  Intent      25%  — how well the LLM understood the request
  RAG         20%  — how reliably session memory was recalled
  GDS         35%  — how bookable/verified the itinerary is (highest weight)
  Hallucination 20%— how factually grounded the LLM output is

Threshold: 85% → PROCEED | <85% → RETRY (max 3×) → Human handoff
"""
from config import Config


class ConfidenceScorer:
    """
    Aggregates four independent signals into a single confidence score.
    Identifies the weakest signal to guide targeted retry fixes.
    """

    WEIGHTS = {
        "intent":        0.25,
        "rag":           0.20,
        "gds":           0.35,
        "hallucination": 0.20,
    }

    # Target fixes per failing signal
    FIXES = {
        "intent":        "Re-parse user intent carefully. Extract destination, dates, guests, budget explicitly.",
        "rag":           "Use session context to fill missing preferences. Don't guess — use provided data.",
        "gds":           "Use ONLY prices and availability from MCP data. Do not invent any values.",
        "hallucination": "Every fact must come from MCP responses. Verify all flight codes and prices.",
    }

    def compute(self, llm_scores: dict,
                mcp_results: dict,
                rag_recall: float) -> dict:
        """
        Returns full confidence report including per-signal scores,
        final weighted score, pass/fail, and targeted fix instruction.
        """
        # S1 — intent confidence from LLM self-report
        s1 = float(llm_scores.get("intent", 0.70))

        # S2 — RAG recall quality (estimated from session entity count)
        s2 = float(rag_recall)

        # S3 — GDS/MCP confidence (weighted avg of MCP server confidences)
        mcp_confs = [
            v.get("confidence", 0)
            for v in mcp_results.values()
            if isinstance(v, dict) and not v.get("error")
        ]
        s3 = round(sum(mcp_confs) / len(mcp_confs), 3) if mcp_confs else 0.5

        # S4 — hallucination guard from LLM self-report
        s4 = float(llm_scores.get("hallucination", 0.80))

        final = (
            s1 * self.WEIGHTS["intent"] +
            s2 * self.WEIGHTS["rag"] +
            s3 * self.WEIGHTS["gds"] +
            s4 * self.WEIGHTS["hallucination"]
        )
        final = round(final, 3)

        passed = final >= Config.CONFIDENCE_THRESHOLD

        return {
            "intent":        round(s1, 3),
            "rag":           round(s2, 3),
            "gds":           round(s3, 3),
            "hallucination": round(s4, 3),
            "overall":       final,
            "threshold":     Config.CONFIDENCE_THRESHOLD,
            "passed":        passed,
            "weakest":       self._weakest(s1, s2, s3, s4),
        }

    def targeted_fix(self, scores: dict) -> str:
        """Return a targeted fix instruction for the weakest signal."""
        w = scores.get("weakest", "gds")
        v = scores.get(w, 0)
        return (
            f"Weakest confidence signal: {w} ({v:.0%}). "
            f"Required action: {self.FIXES.get(w, 'Review and improve accuracy.')}"
        )

    def _weakest(self, s1: float, s2: float, s3: float, s4: float) -> str:
        vals = {"intent": s1, "rag": s2, "gds": s3, "hallucination": s4}
        return min(vals, key=vals.get)
