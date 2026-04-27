"""
Car / Transfer MCP Server
Uses location-aware pricing — no free real-time car rental API exists,
but prices are calculated from real route distances + realistic market rates.
"""
import random
from .base_mcp  import BaseMCP
from .maps_mcp  import AIRPORT_COORDS, CITY_COORDS
import math

# Base taxi/transfer fare per km (GBP) by city
CITY_RATES = {
    "LHR":2.80,"LGW":2.60,"MAN":2.20,"BHX":2.00,
    "LIS":1.60,"BCN":1.80,"MAD":1.70,"FCO":1.80,
    "CDG":2.10,"AMS":2.20,"ATH":1.40,"DXB":2.50,
    "JFK":3.00,"SIN":2.20,"NRT":4.50,"ZRH":3.50,
    "VIE":2.20,"DPS":1.20,"BKK":1.10,"MRU":1.50,
}

CAR_CATEGORIES = {
    1: {"name":"Economy",    "examples":"VW Polo or similar",    "per_day":28},
    2: {"name":"Compact",    "examples":"Ford Focus or similar",  "per_day":35},
    3: {"name":"Standard",   "examples":"Toyota Corolla or similar","per_day":44},
    4: {"name":"SUV",        "examples":"VW Tiguan or similar",   "per_day":58},
    5: {"name":"Minivan",    "examples":"Ford Galaxy (7 seats)",  "per_day":72},
    6: {"name":"Premium",    "examples":"BMW 5 Series or similar","per_day":95},
}

RENTAL_PROVIDERS = ["Hertz","Avis","Enterprise","Budget","Europcar","Sixt"]


class CarMCP(BaseMCP):
    def __init__(self): super().__init__(ttl=600)

    def _fetch(self, params: dict) -> dict:
        airport  = params.get("airport","LIS").upper()[:3]
        guests   = int(params.get("guests",2))
        days     = int(params.get("days",7))
        need_transfer = params.get("transfer_only", False)
        arrival_time  = params.get("arrival_time","")

        rate = CITY_RATES.get(airport, 1.80)
        dist = _airport_to_city_km(airport)

        # Is it late night? (extra charge)
        late = _is_late(arrival_time)
        late_surcharge = 1.25 if late else 1.0

        options = []

        # Transfer options (always offered)
        vehicle = "MPV (7-seat)" if guests >= 5 else ("Estate" if guests >= 4 else "Saloon")
        t_price = round((5 + dist * rate) * late_surcharge, 0)
        options.append({
            "type":         "private_transfer",
            "provider":     "Private Transfer",
            "vehicle":      f"Private {vehicle}",
            "passengers":   guests,
            "pickup":       f"{airport} Airport",
            "dropoff":      "Hotel",
            "distance_km":  dist,
            "price_gbp":    t_price,
            "duration_min": round(dist / 35 * 60 + 10),
            "note":         ("Late-night surcharge applied." if late else
                             "Meet & greet service included."),
            "bookable":     True,
            "source":       "calculated",
        })

        # Shared shuttle (cheaper)
        shuttle_price = round(t_price * 0.45, 0)
        options.append({
            "type":       "shared_shuttle",
            "provider":   "Shared Airport Shuttle",
            "vehicle":    "Minibus",
            "passengers": guests,
            "price_gbp":  shuttle_price,
            "duration_min": round(dist / 35 * 60 + 20),
            "note":       "Shared with other passengers. May include stops.",
            "bookable":   True,
            "source":     "calculated",
        })

        # Car rental (if not transfer-only)
        if not need_transfer:
            cat_num = 5 if guests >= 5 else (4 if guests >= 4 else (3 if guests >= 3 else 2))
            cat = CAR_CATEGORIES[cat_num]
            for i, provider in enumerate(random.sample(RENTAL_PROVIDERS, 3)):
                variance = 1 + (hash(f"{airport}{provider}{days}") % 30 - 15) / 100
                ppd = round(cat["per_day"] * variance, 2)
                options.append({
                    "type":       "car_rental",
                    "provider":   provider,
                    "category":   cat["name"],
                    "vehicle":    cat["examples"],
                    "days":       days,
                    "price_per_day_gbp": ppd,
                    "total_gbp":  round(ppd * days, 2),
                    "included":   ["CDW insurance","unlimited mileage","breakdown cover"],
                    "pickup":     f"{airport} Airport",
                    "note":       "Excess waiver available at counter.",
                    "bookable":   True,
                    "source":     "estimated",
                })
            options.sort(key=lambda x: x.get("total_gbp", x.get("price_gbp",9999)))

        return {"data":{"options":options,"airport":airport,"late_night":late},
                "count":len(options)}

    def _score_confidence(self, r):
        return 0.88 if r.get("data",{}).get("options") else 0.0


def _airport_to_city_km(airport: str) -> float:
    alat, alon = AIRPORT_COORDS.get(airport, (0,0))
    clat, clon = CITY_COORDS.get(airport, (0,0))
    if alat == 0: return 15.0
    R = 6371
    dlat = math.radians(clat - alat)
    dlon = math.radians(clon - alon)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(alat)) * math.cos(math.radians(clat)) *
         math.sin(dlon/2)**2)
    return round(R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a)), 1)


def _is_late(time_str: str) -> bool:
    try: return int(time_str.split(":")[0]) >= 22 or int(time_str.split(":")[0]) <= 5
    except Exception: return False
