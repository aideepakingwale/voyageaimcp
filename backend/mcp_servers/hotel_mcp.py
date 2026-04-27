"""
Hotel MCP Server
PRIMARY:  Amadeus Hotel Search API (real hotels, real prices)
FALLBACK: Curated realistic mock
"""
import random
from datetime import datetime, timedelta
from .base_mcp       import BaseMCP
from .amadeus_client import amadeus

# City code → (lat, lon) for Amadeus activities fallback
CITY_COORDS = {
    "LIS":(38.7223,-9.1393),"BCN":(41.3851,2.1734),"MAD":(40.4168,-3.7038),
    "FCO":(41.9028,12.4964),"CDG":(48.8566,2.3522),"AMS":(52.3676,4.9041),
    "ATH":(37.9838,23.7275),"DXB":(25.2048,55.2708),"LHR":(51.5074,-0.1278),
    "NRT":(35.6762,139.6503),"SIN":(1.3521,103.8198),"JFK":(40.7128,-74.0060),
    "ZRH":(47.3769,8.5417),"VIE":(48.2082,16.3738),"MLE":(4.1755,73.5093),
    "DPS":(-8.3405,115.0920),"BKK":(13.7563,100.5018),"MRU":(-20.1609,57.4977),
    "OPO":(41.1496,-8.6109),"FAO":(37.0194,-7.9322),"TFS":(28.0469,-16.5726),
}

STAR_AMENITIES = {
    5: ["pool","spa","gym","restaurant","bar","concierge","room_service","valet"],
    4: ["pool","gym","restaurant","bar","room_service"],
    3: ["restaurant","bar","wifi"],
}

AREA_NAMES = {
    "LIS":["Chiado","Alfama","Belém","Baixa","Bairro Alto","Parque das Nações"],
    "BCN":["Gothic Quarter","Eixample","Gràcia","Barceloneta","Sarrià"],
    "MAD":["Sol","Salamanca","Malasaña","Chueca","Chamberí"],
    "FCO":["Trastevere","Campo de' Fiori","Prati","Termini","Colosseo"],
    "CDG":["Marais","Saint-Germain","Champs-Élysées","Montmartre","Opéra"],
    "DXB":["Dubai Marina","Downtown","JBR","DIFC","Palm Jumeirah"],
}


class HotelMCP(BaseMCP):
    def __init__(self): super().__init__(ttl=300)

    def _fetch(self, params: dict) -> dict:
        city      = params.get("city","LIS").upper()[:3]
        check_in  = params.get("check_in",  (datetime.now()+timedelta(days=45)).strftime("%Y-%m-%d"))
        check_out = params.get("check_out", (datetime.now()+timedelta(days=52)).strftime("%Y-%m-%d"))
        guests    = int(params.get("guests",2))
        rooms     = int(params.get("rooms",1))
        min_stars = int(params.get("min_stars",3))
        needs_pool= params.get("pool", False)
        family    = params.get("family_rooms", False)

        nights = max(1, (datetime.strptime(check_out,"%Y-%m-%d") -
                         datetime.strptime(check_in, "%Y-%m-%d")).days)

        if amadeus.configured:
            hotels = self._live(city, check_in, check_out, guests, rooms,
                                nights, min_stars, needs_pool, family)
            if hotels:
                return {"data":{"hotels":hotels,"nights":nights,
                                "city":city,"source":"live"},
                        "count":len(hotels)}

        return self._mock(city, check_in, check_out, guests, rooms,
                          nights, min_stars, needs_pool, family)

    def _live(self, city, check_in, check_out, guests, rooms,
              nights, min_stars, needs_pool, family):
        amenities = ["SWIMMING_POOL"] if needs_pool else None
        hotel_list = amadeus.hotel_list(city, radius=10, amenities=amenities)
        if not hotel_list:
            return []
        ids = [h["hotelId"] for h in hotel_list[:30]]
        offers = amadeus.hotel_offers(ids, check_in, check_out, guests)
        results = []
        for o in offers[:12]:
            try:
                h     = o["hotel"]
                offer = o["offers"][0]
                ppn   = float(offer["price"]["total"]) / nights
                total = float(offer["price"]["total"])
                stars = int(h.get("rating", 3))
                if stars < min_stars: continue
                results.append({
                    "name":            h["name"].title(),
                    "stars":           stars,
                    "area":            h.get("cityCode",""),
                    "check_in":        check_in,
                    "check_out":       check_out,
                    "nights":          nights,
                    "price_per_night": round(ppn, 2),
                    "total_price_gbp": round(total, 2),
                    "amenities":       STAR_AMENITIES.get(min(stars,5), [])[:4],
                    "family_rooms":    family,
                    "rooms_available": random.randint(2,8),
                    "bookable":        True,
                    "source":          "live",
                })
            except Exception:
                continue
        results.sort(key=lambda x: x["price_per_night"])
        return results[:8]

    def _mock(self, city, check_in, check_out, guests, rooms,
              nights, min_stars, needs_pool, family):
        base_prices = {5:280, 4:145, 3:85, 2:55}
        areas       = AREA_NAMES.get(city, ["City Centre","Old Town","Waterfront"])
        hotels = []
        for stars in range(5, min_stars-1, -1):
            if needs_pool and stars < 4: continue
            base = base_prices.get(stars, 100)
            for i in range(2 if stars >= 4 else 1):
                seed     = abs(hash(f"{city}{stars}{i}{check_in}"))
                variance = 1 + (seed % 30 - 15) / 100
                ppn      = round(base * variance * rooms, 2)
                total    = round(ppn * nights, 2)
                area     = areas[seed % len(areas)]
                hotels.append({
                    "name":            _hotel_name(city, stars, seed),
                    "stars":           stars,
                    "area":            area,
                    "check_in":        check_in,
                    "check_out":       check_out,
                    "nights":          nights,
                    "price_per_night": ppn,
                    "total_price_gbp": total,
                    "amenities":       STAR_AMENITIES.get(stars,[])[:4],
                    "family_rooms":    stars >= 3,
                    "rooms_available": random.randint(2,8),
                    "bookable":        True,
                    "source":          "estimated",
                })
        hotels.sort(key=lambda x: x["price_per_night"])
        return {"data":{"hotels":hotels[:8],"nights":nights,
                        "city":city,"source":"estimated"},
                "count":len(hotels[:8])}

    def _score_confidence(self, r):
        h = r.get("data",{}).get("hotels",[])
        src = r.get("data",{}).get("source","estimated")
        if not h: return 0.0
        return min(0.99, (0.96 if src=="live" else 0.80))


HOTEL_ADJECTIVES = ["Grand","Royal","Palace","Boutique","Azure","Garden","Heritage","Prestige"]
HOTEL_NOUNS      = ["Hotel","Suites","Resort","Collection","Residence","Retreat"]

def _hotel_name(city: str, stars: int, seed: int) -> str:
    city_words = {"LIS":"Lisboa","BCN":"Barcelona","MAD":"Madrid","FCO":"Roma",
                  "CDG":"Paris","DXB":"Dubai","ATH":"Athens","SIN":"Singapore"}
    city_word  = city_words.get(city, city)
    adj        = HOTEL_ADJECTIVES[seed % len(HOTEL_ADJECTIVES)]
    noun       = HOTEL_NOUNS[(seed // 3) % len(HOTEL_NOUNS)]
    return f"{adj} {city_word} {noun}" if stars >= 4 else f"{city_word} {noun}"
