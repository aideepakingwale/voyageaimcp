"""
Loyalty MCP Server
- Current tier, points, benefits
- Cliff-edge analysis (how close to next tier)
- Points earning estimate for current trip
- Redeemable benefits for this booking
"""
import json, os, sqlite3
from .base_mcp import BaseMCP

DB_PATH = os.path.join(os.path.dirname(__file__), "../data/voyageai.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


class LoyaltyMCP(BaseMCP):

    def __init__(self):
        super().__init__(ttl=60)   # loyalty data changes frequently

    def _fetch(self, params: dict) -> dict:
        customer_id  = params.get("customer_id", "")
        trip_cost    = float(params.get("trip_cost_gbp", 0))
        nights       = int(params.get("nights", 0))
        flights      = int(params.get("flights", 1))

        conn = get_db()
        try:
            # Get loyalty account
            acct = conn.execute("""
                SELECT la.*, c.name
                FROM loyalty_accounts la
                JOIN customers c ON c.id = la.customer_id
                WHERE la.customer_id=?
            """, (customer_id,)).fetchone()

            if not acct:
                return {"data": None, "error": "No loyalty account found"}

            acct = dict(acct)

            # Get current tier details
            tier_info = conn.execute(
                "SELECT * FROM loyalty_tiers WHERE tier=?", (acct["tier"],)
            ).fetchone()
            tier_info = dict(tier_info) if tier_info else {}
            tier_info["benefits"] = json.loads(tier_info.get("benefits") or "{}")

            # Get next tier details
            next_tier_name = tier_info.get("next_tier")
            next_tier = None
            if next_tier_name:
                nt = conn.execute(
                    "SELECT * FROM loyalty_tiers WHERE tier=?", (next_tier_name,)
                ).fetchone()
                if nt:
                    next_tier = dict(nt)
                    next_tier["benefits"] = json.loads(next_tier.get("benefits") or "{}")

            # Cliff-edge analysis
            cliff_edge = self._cliff_edge_analysis(acct, tier_info, next_tier)

            # Points earned on this trip
            multiplier    = tier_info.get("points_multiplier", 1.0)
            points_earned = int(trip_cost * multiplier)
            new_balance   = acct["points_balance"] + points_earned
            nights_after  = acct["total_nights_ytd"] + nights
            flights_after = acct["total_flights_ytd"] + flights

            # Benefits applicable to this booking
            applicable_benefits = self._applicable_benefits(tier_info, next_tier, cliff_edge)

            # Redemption options (what can they use points for)
            redemptions = self._redemption_options(acct["points_balance"], tier_info)

            return {"data": {
                "member":          acct["name"],
                "member_id":       acct["member_id"],
                "current_tier":    acct["tier"],
                "points_balance":  acct["points_balance"],
                "points_ytd":      acct["points_ytd"],
                "nights_ytd":      acct["total_nights_ytd"],
                "flights_ytd":     acct["total_flights_ytd"],
                "tier_expiry":     acct["tier_expiry"],
                "member_since":    acct["member_since"],
                "tier_benefits":   tier_info.get("benefits", {}),
                "tier_perks":      tier_info.get("benefits", {}).get("perks", []),
                "next_tier":       next_tier_name,
                "next_tier_benefits": next_tier.get("benefits", {}) if next_tier else None,
                "cliff_edge":      cliff_edge,
                "trip_earnings": {
                    "points_to_earn":   points_earned,
                    "multiplier":       multiplier,
                    "new_balance":      new_balance,
                    "nights_after":     nights_after,
                    "flights_after":    flights_after,
                    "will_tier_up":     self._will_tier_up(next_tier, new_balance, nights_after, flights_after),
                },
                "applicable_benefits": applicable_benefits,
                "redemption_options":  redemptions,
                "discount_pct":        tier_info.get("benefits", {}).get("discount_pct", 0),
                "lounge_access":       bool(tier_info.get("lounge_access")),
                "priority_boarding":   bool(tier_info.get("priority_boarding")),
            }}
        finally:
            conn.close()

    def _cliff_edge_analysis(self, acct, tier_info, next_tier) -> dict:
        if not next_tier:
            return {"at_max_tier": True, "message": "You are at our highest tier — Platinum!"}

        points_needed  = next_tier["min_points"]    - acct["points_balance"]
        nights_needed  = next_tier["min_nights_ytd"] - acct["total_nights_ytd"]
        flights_needed = next_tier["min_flights_ytd"]- acct["total_flights_ytd"]

        # Cliff edge = within 20% of threshold
        points_pct  = acct["points_balance"] / max(next_tier["min_points"], 1)
        nights_pct  = acct["total_nights_ytd"] / max(next_tier["min_nights_ytd"], 1)
        flights_pct = acct["total_flights_ytd"] / max(next_tier["min_flights_ytd"], 1)

        is_cliff = max(points_pct, nights_pct, flights_pct) >= 0.80

        return {
            "is_cliff_edge":   is_cliff,
            "next_tier":       next_tier["tier"],
            "points_needed":   max(0, points_needed),
            "nights_needed":   max(0, nights_needed),
            "flights_needed":  max(0, flights_needed),
            "points_pct":      round(points_pct * 100, 1),
            "nights_pct":      round(nights_pct * 100, 1),
            "flights_pct":     round(flights_pct * 100, 1),
            "message":         self._cliff_message(is_cliff, next_tier["tier"],
                                   max(0,points_needed), max(0,nights_needed), max(0,flights_needed)),
        }

    def _cliff_message(self, is_cliff, next_tier, points, nights, flights) -> str:
        if is_cliff:
            parts = []
            if points > 0:  parts.append(f"{points:,} more points")
            if nights > 0:  parts.append(f"{nights} more nights")
            if flights > 0: parts.append(f"{flights} more flights")
            if parts:
                return f"🎯 SO CLOSE to {next_tier}! You need just {' and '.join(parts)} — this trip could get you there!"
            return f"🎉 This trip will qualify you for {next_tier} tier!"
        elif points > 0:
            return f"Keep travelling! You need {points:,} more points for {next_tier} tier."
        return f"On track for {next_tier}!"

    def _will_tier_up(self, next_tier, new_balance, nights, flights) -> bool:
        if not next_tier:
            return False
        return (new_balance >= next_tier["min_points"] and
                nights  >= next_tier["min_nights_ytd"] and
                flights >= next_tier["min_flights_ytd"])

    def _applicable_benefits(self, tier_info, next_tier, cliff_edge) -> list:
        perks = []
        benefits = tier_info.get("benefits", {})

        if benefits.get("discount_pct", 0) > 0:
            perks.append({
                "icon": "💰",
                "title": f"{benefits['discount_pct']}% Member Discount",
                "desc":  f"Applied to hotel rate as {tier_info.get('tier','')} member",
                "value": "AUTO-APPLIED"
            })
        if benefits.get("lounge_access"):
            perks.append({
                "icon": "🛋️",
                "title": "Airport Lounge Access",
                "desc":  "Complimentary access at departure airport",
                "value": "INCLUDED"
            })
        if benefits.get("priority_boarding"):
            perks.append({
                "icon": "✈️",
                "title": "Priority Boarding",
                "desc":  "Board before general passengers",
                "value": "INCLUDED"
            })
        upgrade = benefits.get("room_upgrade_chance", "")
        if upgrade and upgrade != "10%":
            perks.append({
                "icon": "🏨",
                "title": f"Room Upgrade ({upgrade} chance)",
                "desc":  "Complimentary upgrade subject to availability",
                "value": "REQUEST AT CHECKIN"
            })
        baggage = benefits.get("extra_baggage", "0kg")
        if baggage != "0kg":
            perks.append({
                "icon": "🧳",
                "title": f"Extra Baggage Allowance +{baggage}",
                "desc":  "Additional baggage included in your fare",
                "value": "INCLUDED"
            })

        # If cliff-edge, show what they'd get at next tier
        if cliff_edge.get("is_cliff_edge") and next_tier:
            nt_benefits = next_tier.get("benefits", {})
            if nt_benefits.get("discount_pct",0) > benefits.get("discount_pct",0):
                perks.append({
                    "icon": "⭐",
                    "title": f"Achieve {next_tier['tier']}: Get {nt_benefits['discount_pct']}% discount!",
                    "desc":  f"Up from current {benefits.get('discount_pct',0)}% — add eligible flights to qualify",
                    "value": "ACHIEVABLE THIS TRIP"
                })

        return perks

    def _redemption_options(self, points: int, tier_info: dict) -> list:
        options = []
        if points >= 5000:
            options.append({"points": 5000, "reward": "£50 hotel credit", "icon": "🏨"})
        if points >= 10000:
            options.append({"points": 10000, "reward": "Free room upgrade", "icon": "⬆️"})
        if points >= 15000:
            options.append({"points": 15000, "reward": "One-way flight reward (short-haul)", "icon": "✈️"})
        if points >= 25000:
            options.append({"points": 25000, "reward": "Return flight reward (short-haul)", "icon": "✈️"})
        if points >= 40000:
            options.append({"points": 40000, "reward": "Long-haul return flight", "icon": "🌍"})
        return options

    def _score_confidence(self, result: dict) -> float:
        return 0.99 if result.get("data") else 0.0
