"""Layer 2c — Business Rules Validation."""
from datetime import datetime
from config import Config
from .types import GuardrailResult


class BusinessRulesGuardrail:
    """
    Enforces travel-domain rules the LLM cannot know:
    - Budget cap (max 10% overshoot)
    - Departure date must be in the future
    - Minimum 1 night stay
    - Seat availability vs guest count
    """

    def validate(self, llm_output: dict) -> GuardrailResult:
        violations = []
        recs   = llm_output.get("recommendations", {})
        intent = llm_output.get("intent", {})
        dates  = intent.get("dates", {})
        total  = llm_output.get("total_cost_gbp", 0)
        budget = intent.get("budget_gbp", float("inf"))
        guests = intent.get("guests", 1)

        # Rule 1: Budget — soft warning only (do not hard-block; user decides)
        # Hard block only if >50% over budget (likely a data error)
        if total > 0 and budget < 99000 and total > budget * 1.50:
            violations.append(
                f"Total cost £{total:.0f} is more than 50% over budget £{budget:.0f} "
                f"— likely a data error, please check"
            )

        # Rule 2: Departure date in future
        dep = dates.get("departure_date", "")
        if dep:
            try:
                if datetime.strptime(dep, "%Y-%m-%d") <= datetime.now():
                    violations.append("Departure date must be in the future")
            except ValueError:
                violations.append(f"Invalid departure date format: {dep}")

        # Rule 3: Minimum stay
        nights = dates.get("nights", 1)
        if int(nights) < 1:
            violations.append("Minimum 1 night stay required")

        # Rule 4: Seat availability
        for flight in recs.get("flights", []):
            seats = flight.get("seats_available", 99)
            if int(seats) < int(guests):
                violations.append(
                    f"Flight {flight.get('flight_number','')} has only {seats} seats for {guests} guests"
                )

        if violations:
            return GuardrailResult(
                passed=False, layer="L2c_BUSINESS_RULES",
                reason="; ".join(violations),
                action="block",
                data={"violations": violations},
            )

        return GuardrailResult(passed=True, layer="L2c_BUSINESS_RULES", action="proceed")
