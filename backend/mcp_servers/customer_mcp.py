"""
Customer MCP Server
Looks up customer profile, travel history, and derives:
- Interest profile from past trips
- Travel pattern analysis
- Personalised destination recommendations
"""
import json, os, sqlite3
from .base_mcp import BaseMCP

DB_PATH = os.path.join(os.path.dirname(__file__), "../data/voyageai.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


DESTINATION_INTERESTS = {
    "Maldives":    ["beach","luxury","snorkelling","diving","romance"],
    "Lisbon":      ["culture","food","city","history","wine"],
    "Tenerife":    ["beach","resort","pool","family","sun"],
    "Barcelona":   ["culture","food","art","city","beach"],
    "Dubai":       ["luxury","shopping","family","modern","water_park"],
    "New York":    ["business","city","culture","food","shopping"],
    "Singapore":   ["business","food","modern","city","culture"],
    "Tokyo":       ["culture","food","technology","history","business"],
    "Paris":       ["culture","art","romance","food","city"],
    "Rome":        ["culture","history","food","art","architecture"],
    "Santorini":   ["romance","view","wine","cruise","photography"],
    "Porto":       ["wine","culture","food","city","history"],
    "Florence":    ["art","culture","food","history","romance"],
    "Bali":        ["adventure","surf","culture","spiritual","nature"],
    "Thailand":    ["adventure","culture","food","beach","budget"],
    "Morocco":     ["culture","adventure","food","history","photography"],
    "Seychelles":  ["beach","luxury","romance","nature","diving"],
    "Amalfi":      ["romance","food","culture","views","boat"],
    "Mauritius":   ["beach","luxury","romance","water_sports","resort"],
    "Cyprus":      ["beach","family","resort","history","food"],
    "Zurich":      ["business","luxury","nature","city","fine_dining"],
}

NEXT_DESTINATIONS = {
    "beach":       ["Maldives","Seychelles","Mauritius","Bali","Santorini","Cyprus","Tenerife"],
    "culture":     ["Florence","Athens","Kyoto","Istanbul","Prague","Lisbon","Porto"],
    "food":        ["San Sebastián","Naples","Lyon","Tokyo","Bangkok","Mumbai","Lisbon"],
    "adventure":   ["Costa Rica","New Zealand","Iceland","Nepal","Patagonia","Bali"],
    "luxury":      ["Maldives","Seychelles","Monaco","Amalfi Coast","St Barts","Dubai"],
    "family":      ["Orlando","Dubai","Lanzarote","Cyprus","Mallorca","Costa Brava"],
    "romance":     ["Venice","Paris","Santorini","Maldives","Amalfi Coast","Tuscany"],
    "business":    ["New York","Singapore","Dubai","Frankfurt","Hong Kong","Zurich"],
    "wine":        ["Tuscany","Bordeaux","Porto","Rioja","Mendoza","Napa Valley"],
    "skiing":      ["Val d'Isère","Verbier","Kitzbühel","Courchevel","Aspen"],
}


class CustomerMCP(BaseMCP):

    def __init__(self):
        super().__init__(ttl=300)

    def _fetch(self, params: dict) -> dict:
        lookup  = params.get("customer_id") or params.get("email") or params.get("name","")
        if not lookup:
            return {"data": None, "error": "No customer identifier provided"}

        conn = get_db()
        try:
            # Find customer
            cust = conn.execute("""
                SELECT * FROM customers
                WHERE id=? OR email=? OR name LIKE ?
            """, (lookup, lookup, f"%{lookup}%")).fetchone()

            if not cust:
                return {"data": None, "error": f"Customer not found: {lookup}",
                        "suggestion": "Ask customer for their loyalty member ID or email"}

            cust = dict(cust)
            cust["preferences"] = json.loads(cust.get("preferences") or "{}")

            # Travel history
            history = conn.execute("""
                SELECT * FROM travel_history WHERE customer_id=?
                ORDER BY departure_date DESC
            """, (cust["id"],)).fetchall()
            history = [dict(h) for h in history]
            for h in history:
                h["ancillaries"] = json.loads(h.get("ancillaries") or "[]")

            # Derive interests from history
            interests = self._derive_interests(history)
            patterns  = self._analyse_patterns(history)
            recs      = self._recommend_destinations(interests, history)

            return {"data": {
                "profile":      cust,
                "history":      history,
                "interests":    interests,
                "patterns":     patterns,
                "recommended_destinations": recs,
                "total_trips":  len(history),
                "total_spent":  sum(h["total_spent_gbp"] for h in history),
                "avg_rating":   round(sum(h["rating"] for h in history) / max(len(history),1), 1),
                "top_airline":  self._most_common([h["airline"] for h in history]),
                "top_hotel_stars": self._most_common([str(h["hotel_stars"]) for h in history]),
            }}
        finally:
            conn.close()

    def _derive_interests(self, history: list) -> dict:
        interest_scores = {}
        for trip in history:
            dest_interests = DESTINATION_INTERESTS.get(trip["destination"], [])
            for interest in dest_interests:
                interest_scores[interest] = interest_scores.get(interest, 0) + trip.get("rating",3)
            for ancillary in trip.get("ancillaries", []):
                interest_scores[ancillary.replace("_"," ")] = interest_scores.get(ancillary.replace("_"," "), 0) + 1

        # Sort by score
        sorted_interests = sorted(interest_scores.items(), key=lambda x: x[1], reverse=True)
        top_interests    = [i[0] for i in sorted_interests[:8]]
        all_scores       = {k: round(v / max(max(interest_scores.values(), default=1), 1), 2)
                           for k, v in interest_scores.items()}

        return {"top": top_interests, "scores": all_scores}

    def _analyse_patterns(self, history: list) -> dict:
        if not history:
            return {}

        months = [int(h["departure_date"].split("-")[1]) for h in history if h.get("departure_date")]
        avg_nights = sum(h["nights"] for h in history) / max(len(history), 1)
        avg_spend  = sum(h["total_spent_gbp"] for h in history) / max(len(history), 1)
        trip_types = {}
        for h in history:
            tt = h.get("trip_type", "leisure")
            trip_types[tt] = trip_types.get(tt, 0) + 1

        preferred_month = max(set(months), key=months.count) if months else 8
        month_names = {1:"January",2:"February",3:"March",4:"April",5:"May",6:"June",
                       7:"July",8:"August",9:"September",10:"October",11:"November",12:"December"}

        return {
            "preferred_travel_month": month_names.get(preferred_month, "Summer"),
            "avg_trip_length_nights": round(avg_nights, 1),
            "avg_spend_per_trip_gbp": round(avg_spend, 0),
            "primary_trip_type":     max(trip_types, key=trip_types.get) if trip_types else "leisure",
            "books_in_advance_days": 75,
            "total_countries_visited": len(set(h.get("country_code","") for h in history)),
            "repeat_destinations":   self._find_repeats([h["destination"] for h in history]),
        }

    def _recommend_destinations(self, interests: dict, history: list) -> list:
        visited = {h["destination"] for h in history}
        top     = interests.get("top", [])
        recs    = []
        seen    = set()

        for interest in top[:5]:
            for dest in NEXT_DESTINATIONS.get(interest, []):
                if dest not in visited and dest not in seen:
                    recs.append({
                        "destination": dest,
                        "reason":      _build_reason(dest, interest, history, interests),
                        "match_score": round(interests["scores"].get(interest, 0.5), 2),
                        "based_on_interest": interest,
                    })
                    seen.add(dest)
                if len(recs) >= 6:
                    break
            if len(recs) >= 6:
                break

        return recs[:6]

    def _most_common(self, lst: list) -> str:
        return max(set(lst), key=lst.count) if lst else ""

    def _find_repeats(self, destinations: list) -> list:
        counts = {}
        for d in destinations:
            counts[d] = counts.get(d, 0) + 1
        return [d for d, c in counts.items() if c > 1]

    def _score_confidence(self, result: dict) -> float:
        return 0.98 if result.get("data") else 0.0

def _build_reason(dest: str, interest: str, history: list, interests: dict) -> str:
    """Build a specific, human-readable reason for each recommendation."""
    top = interests.get("top", [])[:3]
    visited = [h["destination"] for h in history]
    similar = [h["destination"] for h in history
               if set(DESTINATION_INTERESTS.get(h["destination"], [])) &
                  set(DESTINATION_INTERESTS.get(dest, []))]

    DEST_PROFILES = {
        "Athens":        "rich ancient history, world-class food scene, and stunning architecture",
        "Kyoto":         "serene temples, traditional culture, and exceptional cuisine",
        "Istanbul":      "unique East-meets-West culture, incredible food, and historic landmarks",
        "Prague":        "fairy-tale architecture, vibrant arts scene, and European charm",
        "San Sebastián": "renowned as Europe's food capital with Michelin-starred pintxos bars",
        "Naples":        "authentic Italian culture, world-famous pizza, and proximity to Pompeii",
        "Florence":      "Renaissance art, stunning architecture, and Tuscan food and wine",
        "Tuscany":       "rolling vineyards, world-class wine, and quintessential Italian countryside",
        "Val d'Isère":   "world-class skiing with excellent off-piste terrain and alpine charm",
        "Verbier":       "legendary ski resort with vibrant après-ski and stunning Swiss Alps scenery",
        "Costa Rica":    "unmatched biodiversity, zip-lining, surfing, and eco-adventure",
        "Iceland":       "Northern Lights, glacier hikes, hot springs, and dramatic landscapes",
        "Maldives":      "overwater villas, crystal-clear lagoons, and world-class snorkelling",
        "Seychelles":    "pristine beaches, unique granite boulders, and excellent diving",
        "Venice":        "unparalleled romance, historic canals, and exceptional art",
        "Amalfi Coast":  "dramatic coastal scenery, fresh seafood, and La Dolce Vita",
        "Bordeaux":      "world-famous wine estates, elegant architecture, and superb gastronomy",
    }

    desc = DEST_PROFILES.get(dest, f"perfect match for {interest} lovers")

    if similar:
        similar_name = similar[-1]
        return f"You loved {similar_name} — {dest} offers similar {interest} appeal: {desc}."
    elif interest in top[:2]:
        return f"Your top interest is {interest}, and {dest} is one of the best destinations for it: {desc}."
    else:
        return f"Based on your {interest} travel history, {dest} is a natural next step — {desc}."
