"""
Flight MCP Server
PRIMARY:  Amadeus Flight Offers API (real-time fares, real flight numbers)
FALLBACK: Intelligent mock with date-aware pricing
"""
import re, random
from datetime import datetime, timedelta
from .base_mcp       import BaseMCP
from .amadeus_client import amadeus

AIRLINE_NAMES = {
    "BA":"British Airways","TP":"TAP Air Portugal","EZY":"easyJet",
    "FR":"Ryanair","U2":"easyJet","VY":"Vueling","IB":"Iberia",
    "AF":"Air France","KL":"KLM","LH":"Lufthansa","AZ":"ITA Airways",
    "AY":"Finnair","SK":"SAS","OS":"Austrian","LX":"Swiss",
    "EK":"Emirates","QR":"Qatar Airways","TK":"Turkish Airlines",
    "AA":"American Airlines","UA":"United Airlines","DL":"Delta",
    "VS":"Virgin Atlantic","W6":"Wizz Air","PC":"Pegasus Airlines",
}

ROUTE_PRICES = {
    ("LHR","LIS"):130,("LHR","BCN"):110,("LHR","MAD"):115,
    ("LHR","FCO"):140,("LHR","CDG"):80, ("LHR","AMS"):90,
    ("LHR","DXB"):320,("LHR","JFK"):420,("LHR","LAX"):520,
    ("LHR","SIN"):560,("LHR","NRT"):680,("LHR","BKK"):480,
    ("LHR","DPS"):620,("LGW","LIS"):115,("LGW","BCN"):95,
    ("LGW","CDG"):70, ("MAN","LIS"):145,("MAN","BCN"):125,
    ("LHR","ATH"):195,("LHR","ZRH"):130,("LHR","VIE"):145,
    ("LHR","MLE"):680,("LHR","SEZ"):720,("LHR","MRU"):650,
}


class FlightMCP(BaseMCP):
    def __init__(self): super().__init__(ttl=120)

    def _fetch(self, params: dict) -> dict:
        origin      = params.get("origin","LHR").upper()
        destination = params.get("destination","LIS").upper()
        date        = params.get("date") or (datetime.now()+timedelta(days=45)).strftime("%Y-%m-%d")
        adults      = int(params.get("adults", 2))
        direct      = params.get("direct_only", True)
        currency    = params.get("currency","GBP")

        if amadeus.configured:
            raw = amadeus.flight_offers(origin, destination, date, adults, direct, currency)
            if raw:
                flights = [f for f in (_parse_offer(o, adults) for o in raw[:8]) if f]
                if flights:
                    flights.sort(key=lambda x: x["price_gbp"])
                    return {"data":{"flights":flights,"route":f"{origin}→{destination}",
                                    "date":date,"source":"live"},
                            "count":len(flights)}

        return _mock_flights(origin, destination, date, adults, direct)

    def _score_confidence(self, result: dict) -> float:
        flights = result.get("data",{}).get("flights",[])
        src     = result.get("data",{}).get("source","mock")
        if not flights: return 0.0
        return min(0.99, (0.97 if src=="live" else 0.78) + 0.005*len(flights))


def _parse_offer(offer: dict, adults: int) -> dict | None:
    try:
        itin  = offer["itineraries"][0]
        segs  = itin["segments"]
        first, last = segs[0], segs[-1]
        carrier = first["carrierCode"]
        price   = float(offer["price"]["grandTotal"])
        dur_str = _parse_dur(itin.get("duration",""))
        seats   = offer.get("numberOfBookableSeats",9)
        cabin   = offer["travelerPricings"][0]["fareDetailsBySegment"][0].get("cabin","ECONOMY")
        return {
            "airline":         AIRLINE_NAMES.get(carrier, carrier),
            "flight_number":   carrier + first["number"],
            "origin":          first["departure"]["iataCode"],
            "destination":     last["arrival"]["iataCode"],
            "departure":       first["departure"]["at"],
            "arrival":         last["arrival"]["at"],
            "duration":        dur_str,
            "stops":           len(segs) - 1,
            "cabin":           cabin,
            "price_gbp":       round(price, 2),
            "price_per_adult": round(price / max(adults,1), 2),
            "seats_available": int(seats),
            "bookable":        True,
            "source":          "live",
        }
    except Exception:
        return None


def _mock_flights(origin, destination, date, adults, direct_only):
    base = ROUTE_PRICES.get((origin,destination),
           ROUTE_PRICES.get((origin[:3],destination),180))
    try:
        dep = datetime.strptime(date, "%Y-%m-%d")
        days_ahead = (dep - datetime.now()).days
        wk   = 1.15 if dep.weekday() >= 4 else 1.0
        adv  = 0.88 if days_ahead > 60 else (1.12 if days_ahead < 14 else 1.0)
    except Exception:
        wk = adv = 1.0

    schedules = [
        {"dep":"06:30","hrs":2.5,"airline":"Ryanair",        "pfx":"FR","m":0.68},
        {"dep":"07:45","hrs":2.3,"airline":"TAP Air Portugal","pfx":"TP","m":0.95},
        {"dep":"09:20","hrs":2.3,"airline":"British Airways", "pfx":"BA","m":1.22},
        {"dep":"11:55","hrs":2.4,"airline":"easyJet",         "pfx":"EZY","m":0.80},
        {"dep":"14:10","hrs":2.4,"airline":"Vueling",         "pfx":"VY","m":0.84},
        {"dep":"17:30","hrs":2.5,"airline":"Iberia",          "pfx":"IB","m":1.05},
        {"dep":"20:15","hrs":2.3,"airline":"Ryanair",         "pfx":"FR","m":0.63},
    ]

    flights = []
    for s in schedules[:5] if direct_only else schedules:
        ppp   = round(base * s["m"] * wk * adv * (1 + (hash(date+s["pfx"]) % 20 - 10)/100), 2)
        total = round(ppp * adults, 2)
        dh, dm = map(int, s["dep"].split(":"))
        am    = dh*60 + dm + int(s["hrs"]*60)
        code  = f"{s['pfx']}{100 + abs(hash(origin+destination+s['dep'])) % 900}"
        flights.append({
            "airline":         s["airline"],
            "flight_number":   code,
            "origin":          origin,
            "destination":     destination,
            "departure":       f"{date}T{dh:02d}:{dm:02d}:00",
            "arrival":         f"{date}T{am//60:02d}:{am%60:02d}:00",
            "duration":        f"{int(s['hrs'])}h {int((s['hrs']%1)*60):02d}m",
            "stops":           0,
            "cabin":           "ECONOMY",
            "price_gbp":       total,
            "price_per_adult": ppp,
            "seats_available": random.randint(3, 9),
            "bookable":        True,
            "source":          "estimated",
        })

    flights.sort(key=lambda x: x["price_gbp"])
    return {"data":{"flights":flights,"route":f"{origin}→{destination}",
                    "date":date,"source":"estimated"},
            "count":len(flights)}


def _parse_dur(iso: str) -> str:
    h = re.search(r"(\d+)H", iso); m = re.search(r"(\d+)M", iso)
    return " ".join(filter(None, [f"{h.group(1)}h" if h else "", f"{m.group(1)}m" if m else ""])) or iso
