"""
Template Provider — ZERO COST, always works
Fires when ALL API providers fail or have no keys.
Returns structured mock itinerary using MCP data embedded in the prompt.
"""
import json, re
from datetime import datetime, timedelta
from .base_provider import BaseProvider, LLMResponse


class TemplateProvider(BaseProvider):
    """
    Deterministic rule-based itinerary builder.
    Parses MCP data from the prompt and builds a valid JSON response.
    No LLM required — pure Python logic.
    """
    name = "template"
    free = True

    def is_available(self) -> bool:
        return True   # always available

    def complete(self, system: str, user: str,
                 max_tokens: int = 2048, temperature: float = 0.1) -> LLMResponse:
        try:
            result = self._build_itinerary(user)
            return LLMResponse(
                success       = True,
                provider      = self.name,
                model         = "template-v1",
                text          = json.dumps(result),
                input_tokens  = 0,
                output_tokens = 0,
                cost_usd      = 0.0,
            )
        except Exception as e:
            return LLMResponse(
                success=False, provider=self.name,
                error=f"Template generation failed: {e}"
            )

    def _build_itinerary(self, prompt: str) -> dict:
        """Parse prompt for MCP data blocks and build structured itinerary."""

        # Extract destination
        dest_match = re.search(r"destination.*?[:\"]([A-Z]{2,20})", prompt, re.I)
        dest_city  = dest_match.group(1).title() if dest_match else "Lisbon"
        dest_code  = {"Lisbon":"LIS","Barcelona":"BCN","Paris":"CDG",
                      "Rome":"FCO","Madrid":"MAD"}.get(dest_city, "LIS")

        # Extract guests
        guests_m = re.search(r'"guests"\s*:\s*(\d+)', prompt)
        guests   = int(guests_m.group(1)) if guests_m else 2

        # Extract budget
        budget_m = re.search(r'"budget_gbp"\s*:\s*([\d.]+)', prompt)
        budget   = float(budget_m.group(1)) if budget_m else 3000

        # Extract nights
        nights_m = re.search(r'"nights"\s*:\s*(\d+)', prompt)
        nights   = int(nights_m.group(1)) if nights_m else 7

        # Extract departure date
        dep_m    = re.search(r'"departure_date"\s*:\s*"([\d-]+)"', prompt)
        dep_date = dep_m.group(1) if dep_m else (
            datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        ret_date = (datetime.strptime(dep_date, "%Y-%m-%d") +
                    timedelta(days=nights)).strftime("%Y-%m-%d")

        # Extract first flight from MCP data
        flight_m = re.search(r'"airline"\s*:\s*"([^"]+)".*?"flight_number"\s*:\s*"([^"]+)".*?"price_gbp"\s*:\s*([\d.]+)', prompt, re.S)
        if flight_m:
            airline, fnum, fprice = flight_m.group(1), flight_m.group(2), float(flight_m.group(3))
        else:
            airline, fnum, fprice = "TAP Air Portugal", "TP1363", 189 * guests

        # Extract first hotel from MCP data
        hotel_m = re.search(r'"name"\s*:\s*"([^"]+)".*?"stars"\s*:\s*(\d).*?"price_per_night"\s*:\s*([\d.]+)', prompt, re.S)
        if hotel_m:
            hname, hstars, hppn = hotel_m.group(1), int(hotel_m.group(2)), float(hotel_m.group(3))
        else:
            hname, hstars, hppn = "Memmo Alfama", 4, 195

        hotel_total = round(hppn * nights, 2)
        transfer    = 65
        exp_cost    = 120
        total       = round(fprice + hotel_total + transfer + exp_cost, 2)

        conf = {
            "intent":        0.82,
            "rag":           0.75,
            "gds":           0.80,
            "hallucination": 0.85,
            "overall":       0.80,
        }

        return {
            "intent": {
                "destination":  dest_city,
                "city_code":    dest_code,
                "country_code": dest_code[:2] if len(dest_code) >= 2 else "PT",
                "dates": {
                    "departure_date": dep_date,
                    "return_date":    ret_date,
                    "nights":         nights,
                    "flexible":       False,
                },
                "guests":   guests,
                "adults":   max(1, guests - 2),
                "children": min(2, guests),
                "budget_gbp": budget,
                "preferences": {
                    "direct_flight":  True,
                    "pool":           True,
                    "family_rooms":   guests > 2,
                    "min_hotel_stars": hstars,
                },
            },
            "destinations": [dest_city],
            "summary": (
                f"{nights}-night trip to {dest_city} for {guests} guests. "
                f"{airline} direct flight, {hstars}★ {hname}. "
                f"Total: £{total:.0f} (template fallback — verify with live booking)."
            ),
            "recommendations": {
                "flights": [{
                    "airline":         airline,
                    "flight_number":   fnum,
                    "origin":          "LHR",
                    "destination":     dest_code,
                    "departure":       f"{dep_date}T07:35:00",
                    "arrival":         f"{dep_date}T10:45:00",
                    "duration":        "2h10m",
                    "stops":           0,
                    "price_gbp":       round(fprice, 2),
                    "price_per_adult": round(fprice / max(1, guests), 2),
                    "seats_available": 6,
                    "bookable":        True,
                }],
                "hotels": [{
                    "name":            hname,
                    "stars":           hstars,
                    "area":            "City Centre",
                    "check_in":        dep_date,
                    "check_out":       ret_date,
                    "nights":          nights,
                    "price_per_night": hppn,
                    "total_price_gbp": hotel_total,
                    "amenities":       ["pool", "restaurant", "wifi"],
                    "family_rooms":    True,
                    "bookable":        True,
                }],
                "transfers": [{
                    "type":       "airport_transfer",
                    "provider":   "Transfers.com",
                    "price_gbp":  transfer,
                    "duration_min": 30,
                }],
                "experiences": [
                    {"name": f"{dest_city} City Walking Tour", "price_pp_gbp": 35,
                     "total_gbp": 35 * guests, "duration_h": 2.5},
                    {"name": f"Local Food & Wine Experience", "price_pp_gbp": 55,
                     "total_gbp": 55 * guests, "duration_h": 3.0},
                ],
                "weather_advisory": f"Typically pleasant in {dest_city}. Pack layers for evenings.",
                "visa_advisory":    "No visa required for UK passport holders (Schengen area).",
                "currency_tip":     "£1 ≈ €1.17. Carry some cash for local markets.",
            },
            "total_cost_gbp":   total,
            "confidence_scores": conf,
            "reasoning": (
                f"Template fallback used — all LLM providers unavailable. "
                f"Itinerary built from MCP data. "
                f"Confidence capped at {conf['overall']:.0%}. "
                f"Recommend retrying with a live LLM provider for optimal results."
            ),
        }
