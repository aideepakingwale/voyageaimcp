"""
Hotel MCP with provider-swappable live accommodation search.

Default PoC provider:
- LiteAPI hotel rates

Legacy provider retained:
- Amadeus hotel search
"""
import random
from datetime import datetime, timedelta

from config import Config

from .amadeus_client import amadeus
from .base_mcp import BaseMCP
from .liteapi_client import liteapi

CITY_COORDS = {
    "LIS": (38.7223, -9.1393), "BCN": (41.3851, 2.1734), "MAD": (40.4168, -3.7038),
    "FCO": (41.9028, 12.4964), "CDG": (48.8566, 2.3522), "AMS": (52.3676, 4.9041),
    "ATH": (37.9838, 23.7275), "DXB": (25.2048, 55.2708), "LHR": (51.5074, -0.1278),
    "NRT": (35.6762, 139.6503), "SIN": (1.3521, 103.8198), "JFK": (40.7128, -74.0060),
    "ZRH": (47.3769, 8.5417), "VIE": (48.2082, 16.3738), "MLE": (4.1755, 73.5093),
    "DPS": (-8.3405, 115.0920), "BKK": (13.7563, 100.5018), "MRU": (-20.1609, 57.4977),
    "OPO": (41.1496, -8.6109), "FAO": (37.0194, -7.9322), "TFS": (28.0469, -16.5726),
}

STAR_AMENITIES = {
    5: ["pool", "spa", "gym", "restaurant", "bar", "concierge", "room_service", "valet"],
    4: ["pool", "gym", "restaurant", "bar", "room_service"],
    3: ["restaurant", "bar", "wifi"],
}

AREA_NAMES = {
    "LIS": ["Chiado", "Alfama", "Belem", "Baixa", "Bairro Alto", "Parque das Nacoes"],
    "BCN": ["Gothic Quarter", "Eixample", "Gracia", "Barceloneta", "Sarria"],
    "MAD": ["Sol", "Salamanca", "Malasana", "Chueca", "Chamberi"],
    "FCO": ["Trastevere", "Campo de' Fiori", "Prati", "Termini", "Colosseo"],
    "CDG": ["Marais", "Saint-Germain", "Champs-Elysees", "Montmartre", "Opera"],
    "DXB": ["Dubai Marina", "Downtown", "JBR", "DIFC", "Palm Jumeirah"],
}


class HotelMCP(BaseMCP):
    def __init__(self):
        super().__init__(ttl=300)

    def _fetch(self, params: dict) -> dict:
        city = params.get("city", "LIS").upper()[:3]
        check_in = params.get("check_in", (datetime.now() + timedelta(days=45)).strftime("%Y-%m-%d"))
        check_out = params.get("check_out", (datetime.now() + timedelta(days=52)).strftime("%Y-%m-%d"))
        guests = int(params.get("guests", 2))
        rooms = int(params.get("rooms", 1))
        min_stars = int(params.get("min_stars", 3))
        needs_pool = params.get("pool", False)
        family = params.get("family_rooms", False)
        currency = params.get("currency", "GBP")
        nights = max(1, (datetime.strptime(check_out, "%Y-%m-%d") - datetime.strptime(check_in, "%Y-%m-%d")).days)
        provider = (Config.HOTEL_DATA_PROVIDER or "liteapi").lower()

        if provider == "liteapi":
            return self._fetch_liteapi(city, check_in, check_out, guests, rooms,
                                       nights, min_stars, needs_pool, family, currency)
        return self._fetch_amadeus(city, check_in, check_out, guests, rooms,
                                   nights, min_stars, needs_pool, family)

    def _fetch_liteapi(self, city: str, check_in: str, check_out: str,
                       guests: int, rooms: int, nights: int, min_stars: int,
                       needs_pool: bool, family: bool, currency: str) -> dict:
        if liteapi.configured:
            try:
                raw = liteapi.search_rates(city, check_in, check_out, guests, rooms, currency=currency, min_stars=min_stars)
                if raw:
                    hotels = [
                        h for h in (
                            _parse_liteapi_hotel(item, city, check_in, check_out, nights, rooms, min_stars, needs_pool, family, currency)
                            for item in raw[:20]
                        )
                        if h
                    ]
                    if hotels:
                        hotels.sort(key=lambda x: x["price_per_night"])
                        return {
                            "data": {
                                "hotels": hotels[:8],
                                "nights": nights,
                                "city": city,
                                "source": "liteapi_live",
                            },
                            "count": len(hotels[:8]),
                        }
                    self._log.warning("LiteAPI returned hotel rows but none were usable", extra={
                        "city": city,
                        "check_in": check_in,
                        "check_out": check_out,
                        "guests": guests,
                        "rooms": rooms,
                        "diagnostic": liteapi.last_diagnostic.get("hotel_rates", {}),
                        "first_result_keys": sorted(list(raw[0].keys())) if raw and isinstance(raw[0], dict) else [],
                        "first_result_preview": raw[0] if raw and isinstance(raw[0], dict) else {},
                    })
            except Exception as exc:
                liteapi._set_diag("hotel_rates", status="exception", error=str(exc), request={
                    "city": city,
                    "check_in": check_in,
                    "check_out": check_out,
                    "guests": guests,
                    "rooms": rooms,
                    "currency": currency,
                })
                self._log.warning("LiteAPI hotel fallback: %s", type(exc).__name__, extra={
                    "diagnostic": liteapi.last_diagnostic.get("hotel_rates", {}),
                })
        else:
            liteapi._set_diag("auth", status="not_configured", reason="LITEAPI_API_KEY is missing.")
            liteapi._set_diag("hotel_rates", status="auth_unavailable",
                              auth=liteapi.last_diagnostic.get("auth", {}))

        fallback = self._mock(city, check_in, check_out, guests, rooms, nights, min_stars, needs_pool, family)
        fallback["provider_diagnostics"] = {
            "provider": "liteapi",
            "configured": liteapi.configured,
            "operation": "hotel_rates",
            "detail": liteapi.last_diagnostic.get("hotel_rates", {}),
            "auth": liteapi.last_diagnostic.get("auth", {}),
        }
        return fallback

    def _fetch_amadeus(self, city: str, check_in: str, check_out: str,
                       guests: int, rooms: int, nights: int, min_stars: int,
                       needs_pool: bool, family: bool) -> dict:
        if amadeus.configured:
            try:
                hotels = self._live_amadeus(city, check_in, check_out, guests, rooms, nights, min_stars, needs_pool, family)
                if hotels:
                    return {
                        "data": {"hotels": hotels, "nights": nights, "city": city, "source": "amadeus_live"},
                        "count": len(hotels),
                    }
                self._log.warning("Amadeus hotel search returned no usable offers", extra={
                    "city": city,
                    "check_in": check_in,
                    "check_out": check_out,
                    "guests": guests,
                    "rooms": rooms,
                    "hotel_list_diagnostic": amadeus.last_diagnostic.get("hotel_list", {}),
                    "hotel_offers_diagnostic": amadeus.last_diagnostic.get("hotel_offers", {}),
                })
            except Exception as exc:
                amadeus._set_diag("hotel_offers", status="exception", error=str(exc), request={
                    "city": city,
                    "check_in": check_in,
                    "check_out": check_out,
                    "guests": guests,
                    "rooms": rooms,
                })
                self._log.warning("Amadeus hotel fallback: %s", type(exc).__name__, extra={
                    "hotel_list_diagnostic": amadeus.last_diagnostic.get("hotel_list", {}),
                    "hotel_offers_diagnostic": amadeus.last_diagnostic.get("hotel_offers", {}),
                })
        else:
            amadeus._set_diag("auth", status="not_configured",
                              reason="AMADEUS_CLIENT_ID or AMADEUS_CLIENT_SECRET is missing.")
            amadeus._set_diag("hotel_list", status="auth_unavailable",
                              auth=amadeus.last_diagnostic.get("auth", {}))
            amadeus._set_diag("hotel_offers", status="auth_or_ids_unavailable",
                              hotel_count=0, auth=amadeus.last_diagnostic.get("auth", {}))

        fallback = self._mock(city, check_in, check_out, guests, rooms, nights, min_stars, needs_pool, family)
        fallback["provider_diagnostics"] = {
            "provider": "amadeus",
            "configured": amadeus.configured,
            "operations": {
                "hotel_list": amadeus.last_diagnostic.get("hotel_list", {}),
                "hotel_list_by_geocode": amadeus.last_diagnostic.get("hotel_list_by_geocode", {}),
                "hotel_offers": amadeus.last_diagnostic.get("hotel_offers", {}),
                "auth": amadeus.last_diagnostic.get("auth", {}),
            },
        }
        return fallback

    def _live_amadeus(self, city, check_in, check_out, guests, rooms,
                      nights, min_stars, needs_pool, family):
        amenities = ["SWIMMING_POOL"] if needs_pool else None
        hotel_list = amadeus.hotel_list(city, radius=10, amenities=amenities)
        if not hotel_list:
            coords = CITY_COORDS.get(city)
            if coords:
                hotel_list = amadeus.hotel_list_by_geocode(coords[0], coords[1], radius=20, amenities=amenities)
        if not hotel_list and amenities:
            hotel_list = amadeus.hotel_list(city, radius=10, amenities=None)
            if not hotel_list:
                coords = CITY_COORDS.get(city)
                if coords:
                    hotel_list = amadeus.hotel_list_by_geocode(coords[0], coords[1], radius=20, amenities=None)
        if not hotel_list:
            return []
        ids = [hotel["hotelId"] for hotel in hotel_list[:30]]
        offers = []
        for max_ids, currency in ((20, "GBP"), (10, "GBP"), (5, "GBP"), (5, None), (3, "EUR")):
            offers = amadeus.hotel_offers(ids, check_in, check_out, guests, currency=currency, max_ids=max_ids)
            if offers:
                break
        results = []
        for item in offers[:12]:
            try:
                hotel = item["hotel"]
                offer = item["offers"][0]
                total = float(offer["price"]["total"])
                per_night = total / nights
                stars = int(hotel.get("rating", 3))
                if stars < min_stars:
                    continue
                results.append({
                    "name": hotel["name"].title(),
                    "stars": stars,
                    "area": hotel.get("cityCode", ""),
                    "check_in": check_in,
                    "check_out": check_out,
                    "nights": nights,
                    "price_per_night": round(per_night, 2),
                    "total_price_gbp": round(total, 2),
                    "amenities": STAR_AMENITIES.get(min(stars, 5), [])[:4],
                    "family_rooms": family,
                    "rooms_available": max(1, rooms),
                    "bookable": True,
                    "source": "amadeus_live",
                })
            except Exception:
                continue
        results.sort(key=lambda x: x["price_per_night"])
        return results[:8]

    def _mock(self, city, check_in, check_out, guests, rooms,
              nights, min_stars, needs_pool, family):
        base_prices = {5: 280, 4: 145, 3: 85, 2: 55}
        areas = AREA_NAMES.get(city, ["City Centre", "Old Town", "Waterfront"])
        hotels = []
        for stars in range(5, min_stars - 1, -1):
            if needs_pool and stars < 4:
                continue
            base = base_prices.get(stars, 100)
            for index in range(2 if stars >= 4 else 1):
                seed = abs(hash(f"{city}{stars}{index}{check_in}"))
                variance = 1 + (seed % 30 - 15) / 100
                per_night = round(base * variance * rooms, 2)
                total = round(per_night * nights, 2)
                area = areas[seed % len(areas)]
                hotels.append({
                    "name": _hotel_name(city, stars, seed),
                    "stars": stars,
                    "area": area,
                    "check_in": check_in,
                    "check_out": check_out,
                    "nights": nights,
                    "price_per_night": per_night,
                    "total_price_gbp": total,
                    "amenities": STAR_AMENITIES.get(stars, [])[:4],
                    "family_rooms": stars >= 3,
                    "rooms_available": random.randint(2, 8),
                    "bookable": True,
                    "source": "estimated",
                })
        hotels.sort(key=lambda x: x["price_per_night"])
        return {"data": {"hotels": hotels[:8], "nights": nights, "city": city, "source": "estimated"},
                "count": len(hotels[:8])}

    def _score_confidence(self, result):
        hotels = result.get("data", {}).get("hotels", [])
        source = result.get("data", {}).get("source", "estimated")
        if not hotels:
            return 0.0
        return min(0.99, 0.96 if source in {"amadeus_live", "liteapi_live"} else 0.80)


HOTEL_ADJECTIVES = ["Grand", "Royal", "Palace", "Boutique", "Azure", "Garden", "Heritage", "Prestige"]
HOTEL_NOUNS = ["Hotel", "Suites", "Resort", "Collection", "Residence", "Retreat"]


def _hotel_name(city: str, stars: int, seed: int) -> str:
    city_words = {"LIS": "Lisboa", "BCN": "Barcelona", "MAD": "Madrid", "FCO": "Roma",
                  "CDG": "Paris", "DXB": "Dubai", "ATH": "Athens", "SIN": "Singapore"}
    city_word = city_words.get(city, city)
    adjective = HOTEL_ADJECTIVES[seed % len(HOTEL_ADJECTIVES)]
    noun = HOTEL_NOUNS[(seed // 3) % len(HOTEL_NOUNS)]
    return f"{adjective} {city_word} {noun}" if stars >= 4 else f"{city_word} {noun}"


def _parse_liteapi_hotel(item: dict, city: str, check_in: str, check_out: str, nights: int,
                         rooms: int, min_stars: int, needs_pool: bool, family: bool, currency: str):
    try:
        hotel_data = item.get("hotel") if isinstance(item.get("hotel"), dict) else item
        name = _first_value(
            hotel_data,
            ("name",),
            ("hotelName",),
            ("hotel_name",),
            ("hotelDetails", "name"),
            ("hotel_data", "name"),
            ("hotelInfo", "name"),
        )
        if not name:
            name = _deep_find_string(item, {"name", "hotelName", "hotel_name"})
        if not name:
            return None
        stars = int(float(_first_value(
            hotel_data,
            ("starRating",),
            ("stars",),
            ("rating",),
            ("hotelDetails", "starRating"),
        ) or 0))
        if stars and stars < min_stars:
            return None
        amenity_names = _extract_amenities(hotel_data)
        if needs_pool and "pool" not in amenity_names:
            return None
        total_price = _extract_price_value(item)
        price_currency = (_extract_price_currency(item) or currency or "GBP").upper()
        if total_price is None:
            return None
        total_gbp = _convert_to_gbp(float(total_price), price_currency)
        per_night = total_gbp / max(1, nights)
        area = (
            _first_value(
                hotel_data,
                ("address", "area"),
                ("address", "city"),
                ("cityName",),
                ("city",),
                ("hotelDetails", "city"),
                ("location", "city"),
            )
            or city
        )
        return {
            "name": str(name),
            "stars": max(stars, min_stars) if stars else min_stars,
            "area": str(area),
            "check_in": check_in,
            "check_out": check_out,
            "nights": nights,
            "price_per_night": round(per_night, 2),
            "total_price_gbp": round(total_gbp, 2),
            "amenities": amenity_names[:4] or STAR_AMENITIES.get(max(stars, min_stars), [])[:4],
            "family_rooms": bool(_first_value(hotel_data, ("familyFriendly",), ("isFamilyFriendly",)) or family or stars >= 3),
            "rooms_available": int(_first_value(item, ("roomsAvailable",), ("availableRooms",), ("roomCount",)) or rooms),
            "bookable": True,
            "source": "liteapi_live",
        }
    except Exception:
        return None


def _first_value(item: dict, *paths):
    for path in paths:
        cur = item
        ok = True
        for part in path:
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                ok = False
                break
        if ok and cur not in (None, "", [], {}):
            return cur
    return None


def _extract_price_value(item: dict):
    candidates = [
        ("price", "total"),
        ("price", "amount"),
        ("price", "converted"),
        ("total",),
        ("totalPrice",),
        ("grossPrice",),
        ("retailRate", "total"),
        ("netRate", "total"),
        ("rate", "total"),
        ("lowestPrice",),
        ("bestRate", "total"),
        ("dailyRate",),
    ]
    for path in candidates:
        value = _first_value(item, path)
        if value is None:
            continue
        try:
            return float(value)
        except Exception:
            continue
    room_types = item.get("roomTypes") or item.get("rooms") or []
    if isinstance(room_types, list):
        for room in room_types:
            for path in (
                ("price", "total"),
                ("price", "amount"),
                ("retailRate", "total"),
                ("rate", "total"),
                ("totalPrice",),
                ("bestRate", "total"),
            ):
                value = _first_value(room, path)
                if value is None:
                    continue
                try:
                    return float(value)
                except Exception:
                    continue
            nested = _deep_find_number(room, {"total", "amount", "totalPrice", "grossPrice", "lowestPrice"})
            if nested is not None:
                return nested
    nested = _deep_find_number(item, {"total", "amount", "totalPrice", "grossPrice", "lowestPrice", "converted"})
    if nested is not None:
        return nested
    return None


def _extract_price_currency(item: dict):
    for path in (
        ("price", "currency"),
        ("currency",),
        ("convertedCurrency",),
        ("retailRate", "currency"),
        ("netRate", "currency"),
        ("rate", "currency"),
        ("bestRate", "currency"),
    ):
        value = _first_value(item, path)
        if value:
            return value
    room_types = item.get("roomTypes") or item.get("rooms") or []
    if isinstance(room_types, list):
        for room in room_types:
            for path in (("price", "currency"), ("retailRate", "currency"), ("rate", "currency")):
                value = _first_value(room, path)
                if value:
                    return value
    nested = _deep_find_string(item, {"currency", "convertedCurrency"})
    if nested:
        return nested
    return None


def _extract_amenities(item: dict):
    names = []
    for key in ("facilities", "facilityNames", "amenities"):
        value = item.get(key)
        if isinstance(value, list):
            for entry in value:
                if isinstance(entry, str):
                    names.append(entry.lower())
                elif isinstance(entry, dict):
                    text = entry.get("name") or entry.get("label") or entry.get("facilityName")
                    if text:
                        names.append(str(text).lower())
        elif isinstance(value, dict):
            for entry in value.values():
                if isinstance(entry, str):
                    names.append(entry.lower())
    normalized = []
    for name in names:
        if "pool" in name:
            normalized.append("pool")
        elif "spa" in name:
            normalized.append("spa")
        elif "gym" in name or "fitness" in name:
            normalized.append("gym")
        elif "restaurant" in name:
            normalized.append("restaurant")
        elif "bar" in name:
            normalized.append("bar")
        elif "wifi" in name or "wi-fi" in name:
            normalized.append("wifi")
    return list(dict.fromkeys(normalized))


def _deep_find_string(node, keys: set[str]):
    if isinstance(node, dict):
        for key, value in node.items():
            if key in keys and isinstance(value, str) and value.strip():
                return value
            found = _deep_find_string(value, keys)
            if found:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _deep_find_string(value, keys)
            if found:
                return found
    return None


def _deep_find_number(node, keys: set[str]):
    if isinstance(node, dict):
        for key, value in node.items():
            if key in keys:
                try:
                    return float(value)
                except Exception:
                    pass
            found = _deep_find_number(value, keys)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _deep_find_number(value, keys)
            if found is not None:
                return found
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
