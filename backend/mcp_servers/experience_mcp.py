"""
Experience MCP Server
PRIMARY:  Amadeus Activities API (real tours and experiences)
FALLBACK: Curated realistic activity catalogue per city
"""
from .base_mcp       import BaseMCP
from .amadeus_client import amadeus

CITY_COORDS = {
    "LIS":(38.7223,-9.1393),"BCN":(41.3851,2.1734),"MAD":(40.4168,-3.7038),
    "FCO":(41.9028,12.4964),"CDG":(48.8566,2.3522),"ATH":(37.9838,23.7275),
    "DXB":(25.2048,55.2708),"NRT":(35.6762,139.6503),"SIN":(1.3521,103.8198),
    "ZRH":(47.3769,8.5417), "DPS":(-8.3405,115.0920),"BKK":(13.7563,100.5018),
    "VIE":(48.2082,16.3738),"AMS":(52.3676,4.9041),
}

CURATED = {
    "LIS":[
        {"name":"Sintra & Cascais Royal Palaces Day Trip","dur":8,"ppg":55,"tags":["culture","family","history"]},
        {"name":"Lisbon Food & Wine Walking Tour","dur":3.5,"ppg":65,"tags":["food","culture"]},
        {"name":"Fado Show with Portuguese Dinner","dur":3,"ppg":78,"tags":["culture","evening","romantic"]},
        {"name":"Belém & Pastéis de Nata Historical Tour","dur":2.5,"ppg":38,"tags":["food","history","family"]},
        {"name":"Tuk-Tuk Alfama Hills Tour","dur":1.5,"ppg":42,"tags":["city","family"]},
        {"name":"Arrábida Beach & Dolphin Watching","dur":8,"ppg":88,"tags":["beach","nature","adventure"]},
        {"name":"Surf Lesson – Cascais","dur":2,"ppg":55,"tags":["sport","adventure","summer"]},
        {"name":"Oceanarium & MAAT Museum Combo","dur":4,"ppg":28,"tags":["family","kids","culture"]},
    ],
    "BCN":[
        {"name":"Sagrada Família Skip-the-Line Guided Tour","dur":2,"ppg":45,"tags":["culture","history","architecture"]},
        {"name":"Gaudí Architecture & Tapas Walking Tour","dur":4,"ppg":72,"tags":["food","culture","architecture"]},
        {"name":"Flamenco Show with Dinner","dur":2.5,"ppg":85,"tags":["culture","evening","romantic"]},
        {"name":"Camp Nou Stadium Experience","dur":2,"ppg":38,"tags":["sport","family"]},
        {"name":"Gothic Quarter & Born Hidden Gems","dur":3,"ppg":48,"tags":["history","culture"]},
        {"name":"Montserrat Mountain & Monastery","dur":8,"ppg":65,"tags":["nature","culture","day_trip"]},
    ],
    "FCO":[
        {"name":"Vatican Museums & Sistine Chapel (Skip Line)","dur":3,"ppg":58,"tags":["culture","history","art"]},
        {"name":"Colosseum, Roman Forum & Palatine Hill","dur":3.5,"ppg":52,"tags":["history","culture"]},
        {"name":"Rome Food Tour: Trastevere at Night","dur":3,"ppg":79,"tags":["food","evening","culture"]},
        {"name":"Vatican & Castel Sant'Angelo Sunset","dur":4,"ppg":65,"tags":["romantic","culture"]},
        {"name":"Amalfi Coast Day Trip by Boat","dur":10,"ppg":125,"tags":["day_trip","nature","scenic"]},
    ],
    "DXB":[
        {"name":"Desert Safari with BBQ Dinner & Camel Ride","dur":6,"ppg":85,"tags":["adventure","culture","evening"]},
        {"name":"Dubai Frame & Old Dubai Creek Walk","dur":4,"ppg":48,"tags":["culture","history","family"]},
        {"name":"Burj Khalifa At the Top (124F)","dur":1.5,"ppg":42,"tags":["views","family"]},
        {"name":"Dubai Fountain & Souk Tour","dur":3,"ppg":35,"tags":["culture","shopping"]},
        {"name":"Skydive Dubai","dur":3,"ppg":480,"tags":["adventure","extreme"]},
    ],
    "ATH":[
        {"name":"Acropolis & Parthenon Guided Tour","dur":3,"ppg":45,"tags":["history","culture"]},
        {"name":"Athens Food Tasting & Street Art Walk","dur":3.5,"ppg":68,"tags":["food","culture"]},
        {"name":"Cape Sounion & Temple of Poseidon Sunset","dur":5,"ppg":55,"tags":["history","scenic"]},
        {"name":"Santorini Day Trip by Ferry","dur":14,"ppg":115,"tags":["day_trip","scenic","romantic"]},
    ],
}
DEFAULT_ACTIVITIES = [
    {"name":"City Walking Food & History Tour","dur":3,"ppg":55,"tags":["food","culture","history"]},
    {"name":"Half-Day City Highlights Tour","dur":4,"ppg":48,"tags":["culture","city","family"]},
    {"name":"Cooking Class – Local Cuisine","dur":3,"ppg":72,"tags":["food","culture"]},
    {"name":"Sunset Boat or River Cruise","dur":2,"ppg":58,"tags":["romantic","scenic","evening"]},
    {"name":"Street Art & Local Neighbourhoods Walk","dur":2.5,"ppg":38,"tags":["culture","art"]},
    {"name":"Day Trip to Nearby Natural Attraction","dur":8,"ppg":65,"tags":["nature","day_trip"]},
]


class ExperienceMCP(BaseMCP):
    def __init__(self): super().__init__(ttl=3600)

    def _fetch(self, params: dict) -> dict:
        city     = params.get("city","LIS").upper()[:3]
        guests   = int(params.get("guests",2))
        tags     = params.get("interests",[])
        budget_pp= float(params.get("budget_pp", 9999))

        coords = CITY_COORDS.get(city)
        source = "curated"

        if amadeus.configured and coords:
            live = self._live(coords[0], coords[1], guests, tags, budget_pp)
            if live:
                return {"data":{"experiences":live,"city":city,"source":"amadeus_live"},
                        "count":len(live)}

        # Use curated or default
        pool   = CURATED.get(city, DEFAULT_ACTIVITIES)
        source = "curated"
        results = []
        for a in pool:
            if tags and not any(t in a.get("tags",[]) for t in tags):
                continue
            ppg = a["ppg"]
            if ppg > budget_pp: continue
            results.append({
                "name":        a["name"],
                "duration_h":  a["dur"],
                "price_pp_gbp":ppg,
                "total_gbp":   round(ppg * guests, 2),
                "tags":        a.get("tags",[]),
                "availability":"Available – book 24h ahead",
                "bookable":    True,
                "source":      source,
            })
        return {"data":{"experiences":results,"city":city,"source":source},
                "count":len(results)}

    def _live(self, lat, lon, guests, tags, budget_pp):
        raw = amadeus.activities(lat, lon, radius=25)
        if not raw:
            return []
        results = []
        for a in raw[:15]:
            try:
                name  = a.get("name","")
                price = float(a.get("price",{}).get("amount",0))
                if price <= 0 or price > budget_pp: continue
                results.append({
                    "name":         name,
                    "duration_h":   2.5,
                    "price_pp_gbp": round(price, 2),
                    "total_gbp":    round(price * guests, 2),
                    "rating":       float(a.get("rating",4.0)),
                    "tags":         ["activity","tour"],
                    "bookable":     True,
                    "source":       "amadeus_live",
                })
            except Exception:
                continue
        results.sort(key=lambda x: x["price_pp_gbp"])
        return results[:8]

    def _score_confidence(self, r):
        src = r.get("data",{}).get("source","curated")
        if not r.get("data",{}).get("experiences"):
            return 0.0
        return 0.95 if "live" in src else 0.88
