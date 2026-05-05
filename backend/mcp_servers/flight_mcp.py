"""
Flight MCP with provider-swappable live flight search.

Default PoC provider:
- Duffel test/live API for offer requests

Legacy provider retained:
- Amadeus flight offers
"""
import random
import re
from datetime import datetime, timedelta

from config import Config

from .amadeus_client import amadeus
from .base_mcp import BaseMCP
from .duffel_client import duffel

AIRLINE_NAMES = {
    "BA": "British Airways", "TP": "TAP Air Portugal", "EZY": "easyJet",
    "FR": "Ryanair", "U2": "easyJet", "VY": "Vueling", "IB": "Iberia",
    "AF": "Air France", "KL": "KLM", "LH": "Lufthansa", "AZ": "ITA Airways",
    "AY": "Finnair", "SK": "SAS", "OS": "Austrian Airlines", "LX": "SWISS",
    "EK": "Emirates", "QR": "Qatar Airways", "TK": "Turkish Airlines",
    "AA": "American Airlines", "UA": "United Airlines", "DL": "Delta Air Lines",
    "VS": "Virgin Atlantic", "W6": "Wizz Air", "PC": "Pegasus Airlines",
    "SN": "Brussels Airlines", "TOM": "TUI Airways", "BY": "TUI Airways",
    "MT": "Thomas Cook", "LS": "Jet2", "EW": "Eurowings", "HV": "Transavia",
    "TO": "Transavia France", "BV": "Blue Air", "RO": "TAROM",
    "JU": "Air Serbia", "JP": "Adria Airways", "4U": "Germanwings",
    "XQ": "SunExpress", "XC": "Corendon Airlines", "ZB": "Monarch",
    "BE": "Flybe", "6H": "Israir", "IW": "Wings Air",
    "CX": "Cathay Pacific", "SQ": "Singapore Airlines", "MH": "Malaysia Airlines",
    "TG": "Thai Airways", "GA": "Garuda Indonesia", "AI": "Air India",
    "6E": "IndiGo", "G8": "Go First", "IX": "Air India Express",
    "GF": "Gulf Air", "FZ": "flydubai", "G9": "Air Arabia",
    "WY": "Oman Air", "ME": "Middle East Airlines", "GS": "Tianjin Airlines",
    "MU": "China Eastern", "CA": "Air China", "CZ": "China Southern",
    "JL": "Japan Airlines", "NH": "ANA", "OZ": "Asiana Airlines",
    "KE": "Korean Air", "CI": "China Airlines", "BR": "EVA Air",
    "NZ": "Air New Zealand", "QF": "Qantas", "VA": "Virgin Australia",
}

ROUTE_BASE_PRICES = {
    ("LHR", "LIS"): 145, ("LHR", "OPO"): 155, ("LHR", "FAO"): 170,
    ("LHR", "BCN"): 125, ("LHR", "MAD"): 135, ("LHR", "AGP"): 160,
    ("LHR", "TFS"): 185, ("LHR", "PMI"): 175, ("LHR", "IBZ"): 195,
    ("LHR", "LPA"): 190, ("LHR", "ACE"): 200, ("LHR", "FUE"): 205,
    ("LHR", "FCO"): 145, ("LHR", "MXP"): 135, ("LHR", "VCE"): 155,
    ("LHR", "CDG"): 95, ("LHR", "NCE"): 155, ("LHR", "MRS"): 160,
    ("LHR", "AMS"): 105, ("LHR", "BRU"): 110, ("LHR", "ZRH"): 140,
    ("LHR", "GVA"): 145, ("LHR", "VIE"): 155, ("LHR", "MUC"): 145,
    ("LHR", "FRA"): 135, ("LHR", "BER"): 130, ("LHR", "HAM"): 145,
    ("LHR", "ATH"): 195, ("LHR", "JTR"): 225, ("LHR", "HER"): 215,
    ("LHR", "CFU"): 210, ("LHR", "RHO"): 220, ("LHR", "JMK"): 230,
    ("LHR", "CPH"): 140, ("LHR", "ARN"): 150, ("LHR", "OSL"): 145,
    ("LHR", "HEL"): 165, ("LHR", "KEF"): 175, ("LHR", "PRG"): 130,
    ("LHR", "WAW"): 140, ("LHR", "BUD"): 145, ("LHR", "DUB"): 90,
    ("LHR", "DXB"): 345, ("LHR", "AUH"): 355, ("LHR", "DOH"): 335,
    ("LHR", "RUH"): 365, ("LHR", "CAI"): 280, ("LHR", "CMN"): 225,
    ("LHR", "RAK"): 235, ("LHR", "NBO"): 420, ("LHR", "JNB"): 520,
    ("LHR", "CPT"): 545, ("LHR", "MRU"): 610, ("LHR", "SEZ"): 690,
    ("LHR", "SIN"): 580, ("LHR", "NRT"): 680, ("LHR", "HKG"): 620,
    ("LHR", "BKK"): 490, ("LHR", "DPS"): 650, ("LHR", "KUL"): 560,
    ("LHR", "MNL"): 620, ("LHR", "SGN"): 580, ("LHR", "MLE"): 680,
    ("LHR", "CMB"): 520, ("LHR", "DEL"): 420, ("LHR", "BOM"): 440,
    ("LHR", "GOI"): 460, ("LHR", "JFK"): 430, ("LHR", "LAX"): 530,
    ("LHR", "MIA"): 495, ("LHR", "ORD"): 465, ("LHR", "YYZ"): 480,
    ("LHR", "YVR"): 545, ("LHR", "SYD"): 880, ("LHR", "MEL"): 890,
    ("LHR", "AKL"): 980, ("LHR", "GIG"): 620, ("LHR", "GRU"): 640,
    ("LHR", "BOB"): 1150, ("LHR", "HNL"): 780,
    ("LGW", "BCN"): 115, ("LGW", "MAD"): 125, ("LGW", "LIS"): 135,
    ("LGW", "TFS"): 175, ("LGW", "PMI"): 165, ("LGW", "CDG"): 90,
    ("MAN", "LIS"): 165, ("MAN", "BCN"): 145, ("MAN", "MAD"): 155,
    ("MAN", "TFS"): 195, ("MAN", "DXB"): 365, ("MAN", "SEZ"): 710,
    ("MAN", "MLE"): 700, ("MAN", "DPS"): 670, ("MAN", "JFK"): 450,
    ("EDI", "LIS"): 185, ("EDI", "BCN"): 165, ("EDI", "DXB"): 385,
    ("EDI", "AMS"): 130, ("EDI", "CDG"): 145,
    ("BHX", "BCN"): 150, ("BHX", "MAD"): 160, ("BHX", "LIS"): 170,
    ("BHX", "PMI"): 175, ("BHX", "TFS"): 195, ("BHX", "DXB"): 375,
    ("DXB", "LHR"): 345, ("DXB", "MLE"): 280, ("DXB", "CMB"): 210,
    ("DXB", "DEL"): 200, ("DXB", "BOM"): 210, ("DXB", "NBO"): 380,
}

SCHEDULES = {
    "EU": [("06:25", "BA", 2.3), ("07:40", "EZY", 2.1), ("09:15", "FR", 2.2),
            ("11:50", "VY", 2.3), ("14:05", "TP", 2.2), ("16:30", "IB", 2.4),
            ("19:45", "KL", 2.2), ("21:15", "FR", 2.1)],
    "MED": [("06:30", "BA", 3.5), ("08:15", "EZY", 3.3), ("11:00", "FR", 3.4),
            ("14:30", "TOM", 3.5), ("17:00", "BY", 3.3), ("19:30", "LS", 3.4)],
    "LONG": [("09:00", "BA", 8.0), ("11:30", "EK", 9.0), ("14:00", "QR", 9.5),
             ("16:30", "EK", 10.0), ("21:00", "BA", 8.5), ("23:30", "VS", 8.0)],
    "US": [("09:00", "BA", 7.5), ("10:30", "VS", 7.5), ("12:30", "UA", 8.0),
           ("14:00", "AA", 7.5), ("16:00", "BA", 8.0), ("17:30", "DL", 8.5)],
    "AUS": [("09:00", "QF", 21.0), ("12:00", "BA", 21.5), ("21:00", "EK", 23.0)],
}


def _route_type(dest: str) -> str:
    eu = {"LIS", "OPO", "FAO", "BCN", "MAD", "AGP", "PMI", "IBZ", "TFS", "LPA", "ACE", "FUE",
          "FCO", "MXP", "VCE", "CDG", "NCE", "MRS", "AMS", "BRU", "ZRH", "GVA", "VIE", "MUC",
          "FRA", "BER", "HAM", "ATH", "JTR", "HER", "CFU", "RHO", "JMK", "CPH", "ARN", "OSL",
          "HEL", "KEF", "PRG", "WAW", "BUD", "DUB", "LCA", "MLA", "DBV", "SPU", "SVQ", "VLC"}
    us = {"JFK", "LAX", "MIA", "ORD", "SFO", "BOS", "IAD", "DFW", "ATL", "IAH", "SEA", "DEN",
          "LAS", "MCO", "PHX", "MSP", "YYZ", "YVR", "YUL", "YYC", "MEX", "CUN"}
    aus = {"SYD", "MEL", "BNE", "PER", "ADL", "AKL", "WLG", "CHC", "NAN", "PPT", "BOB"}
    if dest in eu:
        return "EU"
    if dest in us:
        return "US"
    if dest in aus:
        return "AUS"
    if dest in {"DXB", "AUH", "DOH", "RUH", "JED", "CMN", "RAK", "CAI", "NBO", "JNB", "CPT",
                "MRU", "SEZ", "KGL", "DAR", "ADD", "ACC", "LOS"}:
        return "MED"
    return "LONG"


class FlightMCP(BaseMCP):
    def __init__(self):
        super().__init__(ttl=180)

    def _fetch(self, params: dict) -> dict:
        origin = params.get("origin", "LHR").upper()
        dest = params.get("destination", "LIS").upper()
        date = params.get("date") or (datetime.now() + timedelta(days=60)).strftime("%Y-%m-%d")
        adults = int(params.get("adults", 2))
        direct = params.get("direct_only", False)
        curr = params.get("currency", "GBP")
        provider = (Config.FLIGHT_DATA_PROVIDER or "duffel").lower()

        if provider == "duffel":
            return self._fetch_duffel(origin, dest, date, adults, direct, curr)
        return self._fetch_amadeus(origin, dest, date, adults, direct, curr)

    def _fetch_duffel(self, origin: str, dest: str, date: str,
                      adults: int, direct: bool, currency: str) -> dict:
        if duffel.configured:
            try:
                raw = duffel.offer_request(origin, dest, date, adults, direct_only=direct)
                if raw:
                    flights = [f for f in (_parse_duffel_offer(o, adults, currency) for o in raw[:12]) if f]
                    if flights:
                        flights.sort(key=lambda x: x["price_gbp"])
                        return {
                            "data": {
                                "flights": flights,
                                "origin": origin,
                                "destination": dest,
                                "date": date,
                                "source": "duffel_api_live",
                            },
                            "count": len(flights),
                        }
                    self._log.warning("Duffel returned offers but none were usable", extra={
                        "origin": origin,
                        "destination": dest,
                        "date": date,
                        "adults": adults,
                        "raw_offer_count": len(raw),
                        "diagnostic": duffel.last_diagnostic.get("offer_request", {}),
                    })
            except Exception as exc:
                duffel._set_diag("offer_request", status="exception", error=str(exc), request={
                    "origin": origin,
                    "destination": dest,
                    "date": date,
                    "adults": adults,
                    "direct_only": direct,
                })
                self._log.warning("Duffel flight fallback: %s", type(exc).__name__, extra={
                    "diagnostic": duffel.last_diagnostic.get("offer_request", {}),
                })
        else:
            duffel._set_diag("auth", status="not_configured", reason="DUFFEL_API_TOKEN is missing.")
            duffel._set_diag("offer_request", status="auth_unavailable",
                             auth=duffel.last_diagnostic.get("auth", {}))

        fallback = _realistic_flights(origin, dest, date, adults, direct)
        fallback["provider_diagnostics"] = {
            "provider": "duffel",
            "configured": duffel.configured,
            "operation": "offer_request",
            "detail": duffel.last_diagnostic.get("offer_request", {}),
            "auth": duffel.last_diagnostic.get("auth", {}),
        }
        return fallback

    def _fetch_amadeus(self, origin: str, dest: str, date: str,
                       adults: int, direct: bool, currency: str) -> dict:
        if amadeus.configured:
            attempts = [
                {"currency": currency, "direct_only": direct, "max_results": 8, "label": "primary"},
                {"currency": None, "direct_only": direct, "max_results": 8, "label": "no_currency"},
                {"currency": "EUR", "direct_only": direct, "max_results": 8, "label": "eur_currency"},
                {"currency": None, "direct_only": False, "max_results": 20, "label": "broad_search"},
            ]
            seen = set()
            for attempt in attempts:
                key = (attempt["currency"], attempt["direct_only"], attempt["max_results"])
                if key in seen:
                    continue
                seen.add(key)
                try:
                    raw = amadeus.flight_offers(
                        origin, dest, date, adults,
                        direct_only=attempt["direct_only"],
                        currency=attempt["currency"],
                        max_results=attempt["max_results"],
                    )
                    if raw:
                        flights = [f for f in (_parse_amadeus_offer(o, adults) for o in raw[:10]) if f]
                        if flights:
                            flights.sort(key=lambda x: x["price_gbp"])
                            return {
                                "data": {
                                    "flights": flights,
                                    "origin": origin,
                                    "destination": dest,
                                    "date": date,
                                    "source": "amadeus_live",
                                    "amadeus_attempt": attempt["label"],
                                },
                                "count": len(flights),
                            }
                        self._log.warning("Amadeus returned flight offers but none were usable", extra={
                            "origin": origin,
                            "destination": dest,
                            "date": date,
                            "adults": adults,
                            "raw_offer_count": len(raw),
                            "attempt": attempt,
                            "diagnostic": amadeus.last_diagnostic.get("flight_offers", {}),
                        })
                except Exception as exc:
                    amadeus._set_diag("flight_offers", status="exception",
                                      error=str(exc),
                                      request={"origin": origin, "destination": dest,
                                               "date": date, "adults": adults,
                                               "direct_only": attempt["direct_only"],
                                               "currency": attempt["currency"]})
                    self._log.warning("Amadeus flight fallback: %s", type(exc).__name__, extra={
                        "attempt": attempt,
                        "diagnostic": amadeus.last_diagnostic.get("flight_offers", {}),
                    })
        else:
            amadeus._set_diag("auth", status="not_configured",
                              reason="AMADEUS_CLIENT_ID or AMADEUS_CLIENT_SECRET is missing.")
            amadeus._set_diag("flight_offers", status="auth_unavailable",
                              auth=amadeus.last_diagnostic.get("auth", {}))

        fallback = _realistic_flights(origin, dest, date, adults, direct)
        fallback["provider_diagnostics"] = {
            "provider": "amadeus",
            "configured": amadeus.configured,
            "operation": "flight_offers",
            "detail": amadeus.last_diagnostic.get("flight_offers", {}),
            "auth": amadeus.last_diagnostic.get("auth", {}),
        }
        return fallback

    def _score_confidence(self, result):
        source = result.get("data", {}).get("source", "")
        count = len(result.get("data", {}).get("flights", []))
        live_sources = {"amadeus_live", "duffel_api_live"}
        return min(0.98, (0.97 if source in live_sources else 0.82) + 0.003 * count)


def _parse_amadeus_offer(offer, adults):
    try:
        itinerary = offer["itineraries"][0]
        segments = itinerary["segments"]
        first, last = segments[0], segments[-1]
        carrier = first["carrierCode"]
        price = float(offer["price"]["grandTotal"])
        duration = _dur(itinerary.get("duration", ""))
        seats = offer.get("numberOfBookableSeats", adults + 4)
        if int(seats) < adults:
            return None
        cabin = offer["travelerPricings"][0]["fareDetailsBySegment"][0].get("cabin", "ECONOMY")
        return {
            "airline": AIRLINE_NAMES.get(carrier, carrier),
            "flight_number": carrier + first["number"],
            "origin": first["departure"]["iataCode"],
            "destination": last["arrival"]["iataCode"],
            "departure": first["departure"]["at"],
            "arrival": last["arrival"]["at"],
            "duration": duration,
            "stops": len(segments) - 1,
            "cabin": cabin,
            "price_gbp": round(price, 2),
            "price_per_adult": round(price / max(adults, 1), 2),
            "seats_available": int(seats),
            "bookable": True,
            "source": "amadeus_live",
        }
    except Exception:
        return None


def _parse_duffel_offer(offer, adults, currency):
    try:
        slices = offer.get("slices", []) or []
        if not slices:
            return None
        first_slice = slices[0]
        segments = first_slice.get("segments", []) or []
        if not segments:
            return None
        first, last = segments[0], segments[-1]
        owner = offer.get("owner", {}) or {}
        marketing_code = (
            ((first.get("marketing_carrier") or {}).get("iata_code"))
            or ((first.get("operating_carrier") or {}).get("iata_code"))
            or ""
        )
        marketing_name = ((first.get("marketing_carrier") or {}).get("name")) or ""
        operating_name = ((first.get("operating_carrier") or {}).get("name")) or ""
        owner_name = owner.get("name") or ""
        sandbox_owner_names = {"Duffel Airways", "Duffel Air", "Duffel"}
        airline_name = operating_name or marketing_name
        if not airline_name or airline_name in sandbox_owner_names:
            airline_name = AIRLINE_NAMES.get(marketing_code, "")
        if (not airline_name or airline_name in sandbox_owner_names) and owner_name not in sandbox_owner_names:
            airline_name = owner_name
        if not airline_name:
            airline_name = marketing_code or "Unknown Airline"
        marketing_number = (
            first.get("marketing_carrier_flight_number")
            or first.get("operating_carrier_flight_number")
            or ""
        )
        total_amount = float(offer.get("total_amount") or 0)
        total_currency = (offer.get("total_currency") or currency or "GBP").upper()
        total_gbp = _convert_to_gbp(total_amount, total_currency)
        return {
            "airline": airline_name,
            "flight_number": f"{marketing_code}{marketing_number}".strip() or marketing_code or "DUFFEL",
            "origin": _segment_iata(first, "origin"),
            "destination": _segment_iata(last, "destination"),
            "departure": first.get("departing_at"),
            "arrival": last.get("arriving_at"),
            "duration": _dur(first_slice.get("duration", "")),
            "stops": max(0, len(segments) - 1),
            "cabin": str(offer.get("cabin_class") or "economy").upper(),
            "price_gbp": round(total_gbp, 2),
            "price_per_adult": round(total_gbp / max(adults, 1), 2),
            "seats_available": adults,
            "bookable": True,
            "source": "duffel_api_live",
        }
    except Exception:
        return None


def _convert_to_gbp(amount: float, currency: str) -> float:
    rates = {
        "GBP": 1.0,
        "EUR": 0.86,
        "USD": 0.79,
        "AED": 0.21,
        "IDR": 0.000049,
        "SGD": 0.59,
    }
    return amount * rates.get((currency or "GBP").upper(), 1.0)


def _segment_iata(segment: dict, key: str) -> str:
    node = segment.get(key) or {}
    return node.get("iata_code") or ((node.get("city") or {}).get("iata_code")) or ""


def _realistic_flights(origin, dest, date, adults, direct):
    base = ROUTE_BASE_PRICES.get((origin, dest)) or ROUTE_BASE_PRICES.get((origin[:3], dest)) or 300
    route_type = _route_type(dest)
    schedules = SCHEDULES.get(route_type, SCHEDULES["LONG"])
    try:
        departure = datetime.strptime(date, "%Y-%m-%d")
        days_ahead = max(0, (departure - datetime.now()).days)
        weekend_multiplier = 1.18 if departure.weekday() >= 4 else 1.0
        advance_multiplier = (
            0.85 if days_ahead > 90 else
            0.92 if days_ahead > 60 else
            1.0 if days_ahead > 30 else
            1.15 if days_ahead < 14 else
            1.05
        )
    except Exception:
        weekend_multiplier = advance_multiplier = 1.0
    flights = []
    selected = schedules[:5] if direct else schedules
    for dep_time, code, hours in selected:
        multiplier = {"BA": 1.25, "VS": 1.20, "EK": 1.15, "QR": 1.10, "SQ": 1.12,
                      "EZY": 0.82, "FR": 0.72, "W6": 0.75, "LS": 0.80}.get(code, 1.0)
        seed = abs(hash(f"{origin}{dest}{dep_time}{code}"))
        variation = 1 + (seed % 22 - 11) / 100
        per_person = round(base * multiplier * weekend_multiplier * advance_multiplier * variation, 2)
        total = round(per_person * adults, 2)
        dep_hour, dep_min = map(int, dep_time.split(":"))
        arrival_minutes = dep_hour * 60 + dep_min + int(hours * 60)
        flight_number = f"{code}{100 + seed % 900}"
        flights.append({
            "airline": AIRLINE_NAMES.get(code, code),
            "flight_number": flight_number,
            "origin": origin,
            "destination": dest,
            "departure": f"{date}T{dep_hour:02d}:{dep_min:02d}:00",
            "arrival": f"{date}T{arrival_minutes // 60:02d}:{arrival_minutes % 60:02d}:00",
            "duration": f"{int(hours)}h {int((hours % 1) * 60):02d}m",
            "stops": 0,
            "cabin": "ECONOMY",
            "price_gbp": total,
            "price_per_adult": per_person,
            "seats_available": max(adults + 2, random.randint(4, 9)),
            "bookable": True,
            "source": "estimated",
        })
    flights.sort(key=lambda x: x["price_gbp"])
    return {
        "data": {
            "flights": flights,
            "origin": origin,
            "destination": dest,
            "date": date,
            "source": "estimated",
        },
        "count": len(flights),
    }


def _dur(iso_value):
    hours = re.search(r"(\d+)H", iso_value or "")
    minutes = re.search(r"(\d+)M", iso_value or "")
    return " ".join(filter(None, [
        f"{hours.group(1)}h" if hours else "",
        f"{minutes.group(1)}m" if minutes else "",
    ])) or (iso_value or "")
