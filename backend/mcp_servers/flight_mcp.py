"""
Flight MCP — Amadeus Flight Offers Search API
Docs: https://developers.amadeus.com/self-service/category/flights/api-doc/flight-offers-search
FREE sandbox: test.api.amadeus.com (real airline data, test fares)
"""
import os, re, random
from datetime        import datetime, timedelta
from .base_mcp       import BaseMCP
from .amadeus_client import amadeus

AIRLINE_NAMES = {
    "BA":"British Airways","TP":"TAP Air Portugal","EZY":"easyJet",
    "FR":"Ryanair","U2":"easyJet","VY":"Vueling","IB":"Iberia",
    "AF":"Air France","KL":"KLM","LH":"Lufthansa","AZ":"ITA Airways",
    "AY":"Finnair","SK":"SAS","OS":"Austrian Airlines","LX":"SWISS",
    "EK":"Emirates","QR":"Qatar Airways","TK":"Turkish Airlines",
    "AA":"American Airlines","UA":"United Airlines","DL":"Delta Air Lines",
    "VS":"Virgin Atlantic","W6":"Wizz Air","PC":"Pegasus Airlines",
    "SN":"Brussels Airlines","TOM":"TUI Airways","BY":"TUI Airways",
    "MT":"Thomas Cook","LS":"Jet2","EW":"Eurowings","HV":"Transavia",
    "TO":"Transavia France","BV":"Blue Air","RO":"TAROM",
    "JU":"Air Serbia","JP":"Adria Airways","4U":"Germanwings",
    "XQ":"SunExpress","XC":"Corendon Airlines","ZB":"Monarch",
    "BE":"Flybe","6H":"Israir","IW":"Wings Air",
    "CX":"Cathay Pacific","SQ":"Singapore Airlines","MH":"Malaysia Airlines",
    "TG":"Thai Airways","GA":"Garuda Indonesia","AI":"Air India",
    "6E":"IndiGo","G8":"Go First","IX":"Air India Express",
    "GF":"Gulf Air","FZ":"flydubai","G9":"Air Arabia",
    "WY":"Oman Air","ME":"Middle East Airlines","GS":"Tianjin Airlines",
    "MU":"China Eastern","CA":"Air China","CZ":"China Southern",
    "JL":"Japan Airlines","NH":"ANA","OZ":"Asiana Airlines",
    "KE":"Korean Air","CI":"China Airlines","BR":"EVA Air",
    "NZ":"Air New Zealand","QF":"Qantas","VA":"Virgin Australia",
}

ROUTE_BASE_PRICES = {
    # From LHR
    ("LHR","LIS"):145,("LHR","OPO"):155,("LHR","FAO"):170,
    ("LHR","BCN"):125,("LHR","MAD"):135,("LHR","AGP"):160,
    ("LHR","TFS"):185,("LHR","PMI"):175,("LHR","IBZ"):195,
    ("LHR","LPA"):190,("LHR","ACE"):200,("LHR","FUE"):205,
    ("LHR","FCO"):145,("LHR","MXP"):135,("LHR","VCE"):155,
    ("LHR","CDG"):95, ("LHR","NCE"):155,("LHR","MRS"):160,
    ("LHR","AMS"):105,("LHR","BRU"):110,("LHR","ZRH"):140,
    ("LHR","GVA"):145,("LHR","VIE"):155,("LHR","MUC"):145,
    ("LHR","FRA"):135,("LHR","BER"):130,("LHR","HAM"):145,
    ("LHR","ATH"):195,("LHR","JTR"):225,("LHR","HER"):215,
    ("LHR","CFU"):210,("LHR","RHO"):220,("LHR","JMK"):230,
    ("LHR","CPH"):140,("LHR","ARN"):150,("LHR","OSL"):145,
    ("LHR","HEL"):165,("LHR","KEF"):175,("LHR","PRG"):130,
    ("LHR","WAW"):140,("LHR","BUD"):145,("LHR","DUB"):90,
    ("LHR","DXB"):345,("LHR","AUH"):355,("LHR","DOH"):335,
    ("LHR","RUH"):365,("LHR","CAI"):280,("LHR","CMN"):225,
    ("LHR","RAK"):235,("LHR","NBO"):420,("LHR","JNB"):520,
    ("LHR","CPT"):545,("LHR","MRU"):610,("LHR","SEZ"):690,
    ("LHR","SIN"):580,("LHR","NRT"):680,("LHR","HKG"):620,
    ("LHR","BKK"):490,("LHR","DPS"):650,("LHR","KUL"):560,
    ("LHR","MNL"):620,("LHR","SGN"):580,("LHR","MLE"):680,
    ("LHR","CMB"):520,("LHR","DEL"):420,("LHR","BOM"):440,
    ("LHR","GOI"):460,("LHR","JFK"):430,("LHR","LAX"):530,
    ("LHR","MIA"):495,("LHR","ORD"):465,("LHR","YYZ"):480,
    ("LHR","YVR"):545,("LHR","SYD"):880,("LHR","MEL"):890,
    ("LHR","AKL"):980,("LHR","GIG"):620,("LHR","GRU"):640,
    ("LHR","BOB"):1150,("LHR","HNL"):780,
    # From LGW
    ("LGW","BCN"):115,("LGW","MAD"):125,("LGW","LIS"):135,
    ("LGW","TFS"):175,("LGW","PMI"):165,("LGW","CDG"):90,
    # From MAN
    ("MAN","LIS"):165,("MAN","BCN"):145,("MAN","MAD"):155,
    ("MAN","TFS"):195,("MAN","DXB"):365,("MAN","SEZ"):710,
    ("MAN","MLE"):700,("MAN","DPS"):670,("MAN","JFK"):450,
    # From EDI
    ("EDI","LIS"):185,("EDI","BCN"):165,("EDI","DXB"):385,
    ("EDI","AMS"):130,("EDI","CDG"):145,
    # From BHX
    ("BHX","BCN"):150,("BHX","MAD"):160,("BHX","LIS"):170,
    ("BHX","PMI"):175,("BHX","TFS"):195,("BHX","DXB"):375,
    # From DXB (return trips)
    ("DXB","LHR"):345,("DXB","MLE"):280,("DXB","CMB"):210,
    ("DXB","DEL"):200,("DXB","BOM"):210,("DXB","NBO"):380,
}

SCHEDULES = {
    "EU":  [("06:25","BA",2.3),("07:40","EZY",2.1),("09:15","FR",2.2),
            ("11:50","VY",2.3),("14:05","TP",2.2),("16:30","IB",2.4),
            ("19:45","KL",2.2),("21:15","FR",2.1)],
    "MED": [("06:30","BA",3.5),("08:15","EZY",3.3),("11:00","FR",3.4),
            ("14:30","TOM",3.5),("17:00","BY",3.3),("19:30","LS",3.4)],
    "LONG":[("09:00","BA",8.0),("11:30","EK",9.0),("14:00","QR",9.5),
            ("16:30","EK",10.0),("21:00","BA",8.5),("23:30","VS",8.0)],
    "US":  [("09:00","BA",7.5),("10:30","VS",7.5),("12:30","UA",8.0),
            ("14:00","AA",7.5),("16:00","BA",8.0),("17:30","DL",8.5)],
    "AUS": [("09:00","QF",21.0),("12:00","BA",21.5),("21:00","EK",23.0)],
}


def _route_type(dest: str) -> str:
    EU  = {"LIS","OPO","FAO","BCN","MAD","AGP","PMI","IBZ","TFS","LPA","ACE","FUE",
           "FCO","MXP","VCE","CDG","NCE","MRS","AMS","BRU","ZRH","GVA","VIE","MUC",
           "FRA","BER","HAM","ATH","JTR","HER","CFU","RHO","JMK","CPH","ARN","OSL",
           "HEL","KEF","PRG","WAW","BUD","DUB","LCA","MLA","DBV","SPU","SVQ","VLC"}
    US  = {"JFK","LAX","MIA","ORD","SFO","BOS","IAD","DFW","ATL","IAH","SEA","DEN",
           "LAS","MCO","PHX","MSP","YYZ","YVR","YUL","YYC","MEX","CUN"}
    AUS = {"SYD","MEL","BNE","PER","ADL","AKL","WLG","CHC","NAN","PPT","BOB"}
    if dest in EU:  return "EU"
    if dest in US:  return "US"
    if dest in AUS: return "AUS"
    if dest in {"DXB","AUH","DOH","RUH","JED","CMN","RAK","CAI","NBO","JNB","CPT",
                "MRU","SEZ","KGL","DAR","ADD","ACC","LOS"}:
        return "MED"
    return "LONG"


class FlightMCP(BaseMCP):
    def __init__(self): super().__init__(ttl=180)

    def _fetch(self, params: dict) -> dict:
        origin = params.get("origin","LHR").upper()
        dest   = params.get("destination","LIS").upper()
        date   = params.get("date") or (datetime.now()+timedelta(days=60)).strftime("%Y-%m-%d")
        adults = int(params.get("adults", 2))
        direct = params.get("direct_only", False)
        curr   = params.get("currency","GBP")

        # ── Real Amadeus call ─────────────────────────────────
        if amadeus.configured:
            try:
                raw = amadeus.flight_offers(origin, dest, date, adults, direct, curr)
                if raw:
                    flights = [f for f in (_parse(o, adults) for o in raw[:10]) if f]
                    if flights:
                        flights.sort(key=lambda x: x["price_gbp"])
                        return {"data":{"flights":flights,"origin":origin,
                                        "destination":dest,"date":date,"source":"amadeus_live"},
                                "count":len(flights)}
            except Exception as e:
                self._log.debug("Amadeus flight fallback: %s", type(e).__name__)

        # ── Realistic fallback ────────────────────────────────
        return _realistic_flights(origin, dest, date, adults, direct)

    def _score_confidence(self, r):
        src = r.get("data",{}).get("source","")
        n   = len(r.get("data",{}).get("flights",[]))
        return min(0.98, (0.97 if src=="amadeus_live" else 0.82) + 0.003*n)


def _parse(offer, adults):
    try:
        itin   = offer["itineraries"][0]
        segs   = itin["segments"]
        first, last = segs[0], segs[-1]
        carrier = first["carrierCode"]
        price   = float(offer["price"]["grandTotal"])
        dur     = _dur(itin.get("duration",""))
        seats   = offer.get("numberOfBookableSeats", adults + 4)
        # Skip offers that don't have enough seats — try next offer
        if int(seats) < adults:
            return None  # caller will try next offer
        cabin   = (offer["travelerPricings"][0]["fareDetailsBySegment"][0]
                   .get("cabin","ECONOMY"))
        return {
            "airline":         AIRLINE_NAMES.get(carrier, carrier),
            "flight_number":   carrier + first["number"],
            "origin":          first["departure"]["iataCode"],
            "destination":     last["arrival"]["iataCode"],
            "departure":       first["departure"]["at"],
            "arrival":         last["arrival"]["at"],
            "duration":        dur,
            "stops":           len(segs)-1,
            "cabin":           cabin,
            "price_gbp":       round(price,2),
            "price_per_adult": round(price/max(adults,1),2),
            "seats_available": int(seats),
            "bookable":        True,
            "source":          "amadeus_live",
        }
    except Exception:
        return None


def _realistic_flights(origin, dest, date, adults, direct):
    base = ROUTE_BASE_PRICES.get((origin,dest)) or ROUTE_BASE_PRICES.get((origin[:3],dest)) or 300
    rtype = _route_type(dest)
    schedules = SCHEDULES.get(rtype, SCHEDULES["LONG"])
    try:
        dep = datetime.strptime(date,"%Y-%m-%d")
        days_ahead = max(0,(dep-datetime.now()).days)
        wk = 1.18 if dep.weekday()>=4 else 1.0
        adv= 0.85 if days_ahead>90 else (0.92 if days_ahead>60 else
              1.0 if days_ahead>30 else 1.15 if days_ahead<14 else 1.05)
    except Exception:
        wk=adv=1.0
    flights=[]
    selected = schedules[:5] if direct else schedules
    for dep_t, code, hrs in selected:
        mult = {"BA":1.25,"VS":1.20,"EK":1.15,"QR":1.10,"SQ":1.12,
                "EZY":0.82,"FR":0.72,"W6":0.75,"LS":0.80}.get(code,1.0)
        seed = abs(hash(f"{origin}{dest}{dep_t}{code}"))
        vary = 1 + (seed%22-11)/100
        ppp  = round(base*mult*wk*adv*vary, 2)
        total= round(ppp*adults, 2)
        dh,dm= map(int,dep_t.split(":"))
        am   = dh*60+dm+int(hrs*60)
        fn   = f"{code}{100+seed%900}"
        flights.append({
            "airline":         AIRLINE_NAMES.get(code,code),
            "flight_number":   fn,
            "origin":          origin,
            "destination":     dest,
            "departure":       f"{date}T{dh:02d}:{dm:02d}:00",
            "arrival":         f"{date}T{am//60:02d}:{am%60:02d}:00",
            "duration":        f"{int(hrs)}h {int((hrs%1)*60):02d}m",
            "stops":           0,
            "cabin":           "ECONOMY",
            "price_gbp":       total,
            "price_per_adult": ppp,
            "seats_available": max(adults + 2, random.randint(4, 9)),
            "bookable":        True,
            "source":          "estimated",
        })
    flights.sort(key=lambda x:x["price_gbp"])
    return {"data":{"flights":flights,"origin":origin,"destination":dest,
                    "date":date,"source":"estimated"},"count":len(flights)}


def _dur(iso):
    h=re.search(r"(\d+)H",iso); m=re.search(r"(\d+)M",iso)
    return " ".join(filter(None,[f"{h.group(1)}h" if h else "",
                                  f"{m.group(1)}m" if m else ""])) or iso
