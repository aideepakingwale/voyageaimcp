"""
Ancillary Intelligence MCP Server
Analyses trip context and intelligently recommends relevant extras:
- Airport distance → private transfer
- Late night arrival → guaranteed transfer
- Summer + beach → pool view room
- Family with kids → kids club, family suite, theme park
- Honeymoon/couple → romantic dinner, spa
- Adventure → sports insurance, equipment
- Loyalty tier → upgrades and perks
"""
import json, os, sqlite3
from datetime import datetime
from .base_mcp import BaseMCP

DB_PATH = os.path.join(os.path.dirname(__file__), "../data/voyageai.db")

# Airport to city centre distances (km) — drives ancillary suggestions
AIRPORT_DISTANCES = {
    "LIS": {"distance_km": 8,  "drive_min": 25, "late_options": True},
    "BCN": {"distance_km": 17, "drive_min": 35, "late_options": True},
    "MAD": {"distance_km": 25, "drive_min": 40, "late_options": True},
    "FCO": {"distance_km": 32, "drive_min": 55, "late_options": True},  # far!
    "CDG": {"distance_km": 30, "drive_min": 50, "late_options": True},  # far!
    "LHR": {"distance_km": 25, "drive_min": 45, "late_options": True},
    "DXB": {"distance_km": 15, "drive_min": 30, "late_options": True},
    "MLE": {"distance_km": 2,  "drive_min": 40, "late_options": True, "boat_transfer": True},
    "DPS": {"distance_km": 12, "drive_min": 30, "late_options": True},
    "JFK": {"distance_km": 25, "drive_min": 50, "late_options": True},
    "NRT": {"distance_km": 70, "drive_min": 90, "late_options": True},  # very far!
    "SIN": {"distance_km": 20, "drive_min": 35, "late_options": True},
    "GVA": {"distance_km": 5,  "drive_min": 15, "late_options": False},
}

# Summer months by hemisphere
SUMMER_MONTHS_NORTH = {6, 7, 8}  # June-August
BEACH_DESTINATIONS  = {"LIS","BCN","FCO","DPS","MLE","SEZ","MRU","TFS","JTR","LCA","DXB"}
CITY_DESTINATIONS   = {"LHR","CDG","JFK","SIN","NRT","FCO","BCN","MAD"}
SKI_DESTINATIONS    = {"GVA","ZRH","INN","BRN"}


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


class AncillaryMCP(BaseMCP):

    def __init__(self):
        super().__init__(ttl=120)

    def _fetch(self, params: dict) -> dict:
        city_code     = params.get("city_code", "LIS").upper()
        departure_date= params.get("departure_date", "2025-08-01")
        arrival_time  = params.get("arrival_time", "14:00")  # HH:MM
        guests        = int(params.get("guests", 2))
        adults        = int(params.get("adults", 2))
        children      = int(params.get("children", 0))
        trip_type     = params.get("trip_type", "leisure")
        customer_interests = params.get("interests", [])
        loyalty_tier  = params.get("loyalty_tier", "Blue")
        nights        = int(params.get("nights", 7))
        hotel_stars   = int(params.get("hotel_stars", 4))
        budget_gbp    = float(params.get("budget_gbp", 3000))
        trip_cost_so_far = float(params.get("trip_cost_so_far", 0))

        context = {
            "is_family":      children > 0,
            "children":       children,
            "guests":         guests,
            "is_couple":      adults == 2 and children == 0,
            "is_solo":        guests == 1,
            "is_large_group": guests >= 5,
            "is_beach":       city_code in BEACH_DESTINATIONS,
            "is_city":        city_code in CITY_DESTINATIONS,
            "is_ski":         city_code in SKI_DESTINATIONS,
            "month":          int(departure_date.split("-")[1]) if departure_date else 8,
            "is_summer":      int(departure_date.split("-")[1]) in SUMMER_MONTHS_NORTH if departure_date else False,
            "is_late_arrival": self._is_late_night(arrival_time),
            "airport_info":   AIRPORT_DISTANCES.get(city_code, {"distance_km": 15, "drive_min": 30}),
            "is_far_airport": AIRPORT_DISTANCES.get(city_code, {}).get("distance_km", 15) > 20,
            "trip_type":      trip_type,
            "is_honeymoon":   trip_type == "honeymoon",
            "is_adventure":   trip_type == "adventure" or "adventure" in customer_interests,
            "is_business":    trip_type == "business",
            "loyalty_tier":   loyalty_tier,
            "is_gold_plus":   loyalty_tier in ("Gold", "Platinum"),
            "is_platinum":    loyalty_tier == "Platinum",
            "budget_remaining": budget_gbp - trip_cost_so_far,
            "nights":         nights,
            "hotel_stars":    hotel_stars,
            "interests":      customer_interests,
        }

        # Fetch all ancillaries from DB
        conn = get_db()
        try:
            all_ancillaries = conn.execute("SELECT * FROM ancillaries").fetchall()
            all_ancillaries = [dict(a) for a in all_ancillaries]
        finally:
            conn.close()

        # Score each ancillary against context
        scored = []
        for anc in all_ancillaries:
            score, reasons = self._score_ancillary(anc, context)
            if score > 0:
                price = anc["price_gbp"]
                # Apply loyalty discount
                if context["is_gold_plus"] and anc.get("loyalty_discount",0) > 0:
                    discount = anc["loyalty_discount"]
                    price    = round(price * (1 - discount/100), 2)
                scored.append({
                    **anc,
                    "relevance_score": score,
                    "reasons": reasons,
                    "price_gbp": price,
                    "loyalty_discounted": anc.get("loyalty_discount", 0) > 0 and context["is_gold_plus"],
                    "must_have": score >= 0.85,
                })

        scored.sort(key=lambda x: x["relevance_score"], reverse=True)

        # Group by category
        grouped = {}
        for a in scored[:12]:  # top 12
            cat = a["category"]
            grouped.setdefault(cat, []).append(a)

        # Smart narrative
        narratives = self._build_narratives(context, scored[:6])

        return {"data": {
            "ancillaries":   scored[:10],
            "by_category":   grouped,
            "must_haves":    [a for a in scored if a["must_have"]][:4],
            "narratives":    narratives,
            "context":       context,
            "total_ancillary_value": round(sum(a["price_gbp"] for a in scored[:5]), 2),
        }}

    def _score_ancillary(self, anc: dict, ctx: dict) -> tuple:
        score   = 0.0
        reasons = []

        cat  = anc["category"]
        aid  = anc["id"]
        conds= json.loads(anc.get("conditions") or "{}")
        triggers = conds.get("suggest_when", [])

        # --- TRANSFERS ---
        if cat == "transfer":
            if ctx["is_late_arrival"] and aid == "TR004":
                score  = 0.95; reasons.append("Late night arrival — guaranteed transfer recommended")
            elif ctx["is_far_airport"] and aid == "TR001":
                score  = 0.90; reasons.append(f"Airport is {ctx['airport_info'].get('distance_km','?')}km from city — private transfer advised")
            elif ctx["is_family"] and ctx["guests"] >= 4 and aid == "TR002":
                score  = 0.88; reasons.append("Large family group — MPV transfer fits everyone comfortably")
            elif ctx["is_city"] and aid == "TR001" and not ctx["is_far_airport"]:
                score  = 0.60; reasons.append("Convenient airport transfer available")
            elif ctx["is_solo"] and aid == "TR003":
                score  = 0.65; reasons.append("Economy shared shuttle — budget-friendly option")

        # --- ROOM UPGRADES ---
        elif cat == "room_upgrade":
            if ctx["is_platinum"] and aid in ("RU001","RU003"):
                score  = 0.92; reasons.append("Platinum member — complimentary upgrade likely, confirm at check-in")
            elif ctx["is_family"] and ctx["children"] >= 2 and aid == "RU004":
                score  = 0.90; reasons.append("Family of 4+ — family suite or connecting rooms strongly recommended")
            elif ctx["is_honeymoon"] and aid == "RU001":
                score  = 0.92; reasons.append("Honeymoon trip — junior suite sets a special tone")
            elif ctx["is_summer"] and ctx["is_beach"] and aid == "RU002":
                score  = 0.85; reasons.append("Summer beach trip — pool/ocean view room worth every penny")
            elif ctx["is_gold_plus"] and aid == "RU001":
                score  = 0.75; reasons.append("Gold member — discounted room upgrade available")
            elif ctx["is_business"] and aid == "RU003":
                score  = 0.80; reasons.append("Business travel — executive floor includes lounge and express checkout")

        # --- INSURANCE ---
        elif cat == "insurance":
            if ctx["is_family"] and aid == "IN002":
                score  = 0.95; reasons.append("Family travel — comprehensive family insurance is essential")
            elif ctx["is_adventure"] and aid == "IN003":
                score  = 0.90; reasons.append("Adventure activities planned — specialist sports cover required")
            elif aid == "IN001" and not ctx["is_solo"]:
                score  = 0.80; reasons.append("Comprehensive travel insurance recommended for groups")
            elif aid == "IN001":
                score  = 0.70; reasons.append("Travel insurance protects your investment")

        # --- EXPERIENCES ---
        elif cat == "experience":
            if ctx["is_family"] and ctx["children"] >= 1 and aid in ("EX002","EX005"):
                score  = 0.90; reasons.append("Kids-friendly — supervised activities give parents a break too")
            elif ctx["is_honeymoon"] and aid in ("EX003","EX006"):
                score  = 0.92; reasons.append("Perfect for a honeymoon — intimate and memorable")
            elif ctx["is_couple"] and aid == "EX003":
                score  = 0.82; reasons.append("Romantic dinner experience — ideal for couples")
            elif ctx["is_summer"] and ctx["is_beach"] and aid == "EX004":
                score  = 0.85; reasons.append("Summer at the beach — surf lesson is a must-try")
            elif ctx["is_gold_plus"] and aid == "EX001":
                score  = 0.75; reasons.append("Private city tour — exclusive experience for Gold+ members")
            elif ctx["is_city"] and aid == "EX001":
                score  = 0.70; reasons.append("Make the most of a city destination with a local expert")

        # --- EQUIPMENT ---
        elif cat == "equipment":
            if ctx["children"] > 0 and ctx.get("children") and ctx["children"] < 3 and aid == "EQ001":
                score  = 0.88; reasons.append("Young children detected — baby equipment pack saves packing")
            elif ctx["is_platinum"] and ctx["is_city"] and aid == "EQ002":
                score  = 0.65; reasons.append("Golf equipment available at resort")

        return round(score, 2), reasons

    def _is_late_night(self, time_str: str) -> bool:
        try:
            h = int(time_str.split(":")[0])
            return h >= 22 or h <= 5
        except Exception:
            return False

    def _build_narratives(self, ctx: dict, top_ancillaries: list) -> list:
        n = []
        if ctx["is_family"]:
            n.append({"icon":"👨‍👩‍👧‍👦","title":"Family Travel Tip",
                "text":f"With {ctx['children']} child(ren), we've prioritised kids-friendly experiences, a family room, and comprehensive insurance."})
        if ctx["is_late_arrival"]:
            n.append({"icon":"🌙","title":"Late Night Arrival Detected",
                "text":"Your flight arrives late — a pre-booked private transfer means no taxi queues after a long journey."})
        if ctx["is_far_airport"]:
            n.append({"icon":"🗺️","title":"Airport Is Far From City",
                "text":f"The airport is {ctx['airport_info'].get('distance_km','?')}km from your hotel — a private transfer avoids confusing public transport on arrival."})
        if ctx["is_summer"] and ctx["is_beach"]:
            n.append({"icon":"☀️","title":"Summer Beach Holiday",
                "text":"Pool or ocean view rooms are worth the upgrade in summer — you'll spend most of the day outside and want that view to come back to."})
        if ctx["is_honeymoon"]:
            n.append({"icon":"💍","title":"Congratulations!",
                "text":"We've added romantic extras to make your honeymoon unforgettable — private dining, spa access, and a suite upgrade."})
        if ctx["is_gold_plus"]:
            n.append({"icon":"⭐","title":"Your Loyalty Benefits",
                "text":f"As a {ctx['loyalty_tier']} member, you receive discounts on selected ancillaries and complimentary priority boarding."})
        return n

    def _score_confidence(self, result: dict) -> float:
        return 0.92 if result.get("data", {}).get("ancillaries") else 0.5
