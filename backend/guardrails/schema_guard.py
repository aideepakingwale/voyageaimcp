"""Layer 2a — JSON Schema Enforcement."""
import json
import jsonschema
from .types import GuardrailResult

ITINERARY_SCHEMA = {
    "type": "object",
    "required": ["intent", "destinations", "confidence_scores", "summary"],
    "properties": {
        "intent": {
            "type": "object",
            "required": ["destination", "dates", "guests", "budget_gbp"],
            "properties": {
                "destination":  {"type": "string", "minLength": 2},
                "city_code":    {"type": "string"},
                "dates":        {"type": "object"},
                "guests":       {"type": "integer", "minimum": 1, "maximum": 20},
                "budget_gbp":   {"type": "number", "minimum": 0},
                "adults":       {"type": "integer", "minimum": 0},
                "children":     {"type": "integer", "minimum": 0},
                "preferences":  {"type": "object"},
            },
        },
        "destinations":       {"type": "array", "minItems": 1},
        "confidence_scores":  {
            "type": "object",
            "required": ["overall"],
            "properties": {
                "intent":        {"type": "number", "minimum": 0, "maximum": 1},
                "rag":           {"type": "number", "minimum": 0, "maximum": 1},
                "overall":       {"type": "number", "minimum": 0, "maximum": 1},
                "hallucination": {"type": "number", "minimum": 0, "maximum": 1},
            },
        },
        "summary":            {"type": "string", "minLength": 10},
        "recommendations":    {"type": "object"},
        "total_cost_gbp":     {"type": "number", "minimum": 0},
    },
}


class SchemaGuardrail:
    """Validates LLM output against typed JSON schema."""

    def validate(self, llm_output) -> GuardrailResult:
        # Parse if string
        if isinstance(llm_output, str):
            try:
                llm_output = json.loads(llm_output)
            except json.JSONDecodeError as e:
                return GuardrailResult(
                    passed=False, layer="L2a_SCHEMA",
                    reason=f"Invalid JSON: {e}", action="retry",
                )

        # Schema validation
        validator = jsonschema.Draft7Validator(ITINERARY_SCHEMA)
        errors    = list(validator.iter_errors(llm_output))
        if errors:
            fields = [str(e.json_path) for e in errors[:5]]
            return GuardrailResult(
                passed=False, layer="L2a_SCHEMA",
                reason=f"Schema violations in: {fields}",
                action="retry", failed_fields=fields,
            )

        return GuardrailResult(passed=True, layer="L2a_SCHEMA", action="proceed", data=llm_output)
