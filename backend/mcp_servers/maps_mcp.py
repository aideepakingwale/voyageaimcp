"""
Maps / Distance MCP Server
PRIMARY:  OpenRouteService Matrix API (free, no credit card)
          https://openrouteservice.org — 2000 req/day free
FALLBACK: Haversine distance calculation + empirical city data
"""
import os, math
from .base_mcp    import BaseMCP
from .http_client import post, get

ORS_BASE = "https://api.openrouteservice.org"

# Airport coordinates
AIRPORT_COORDS = {
    "LIS":(38.7756,-9.1354),"BCN":(41.2971,2.0785),"MAD":(40.4983,-3.5676),
    "FCO":(41.8003,12.2389),"CDG":(49.0097,2.5479),"AMS":(52.3086,4.7639),
    "ATH":(37.9364,23.9445),"DXB":(25.2532,55.3657),"LHR":(51.4775,-0.4614),
    "LGW":(51.1481,-0.1903),"STN":(51.8850,0.2350), "MAN":(53.3537,-2.2750),
    "NRT":(35.7720,140.3929),"SIN":(1.3644,103.9915),"JFK":(40.6413,-73.7781),
    "ZRH":(47.4647,8.5492), "VIE":(48.1103,16.5697),"MLE":(4.1917,73.5290),
    "DPS":(-8.7482,115.1671),"BKK":(13.6900,100.7501),"MRU":(-20.4302,57.6836),
    "OPO":(41.2481,-8.6814),"TFS":(28.0445,-16.5724),"SEZ":(-4.6742,55.5219),
}

# City centre coordinates
CITY_COORDS = {
    "LIS":(38.7223,-9.1393),"BCN":(41.3851,2.1734),"MAD":(40.4168,-3.7038),
    "FCO":(41.9028,12.4964),"CDG":(48.8566,2.3522),"AMS":(52.3676,4.9041),
    "ATH":(37.9838,23.7275),"DXB":(25.2048,55.2708),"LHR":(51.5074,-0.1278),
    "NRT":(35.6762,139.6503),"SIN":(1.3521,103.8198),"JFK":(40.7128,-74.0060),
    "ZRH":(47.3769,8.5417), "VIE":(48.2082,16.3738),"MLE":(4.1755,73.5093),
    "DPS":(-8.3405,115.0920),"BKK":(13.7563,100.5018),"MRU":(-20.1609,57.4977),
}


class MapsMCP(BaseMCP):
    def __init__(self): super().__init__(ttl=86400)

    def _fetch(self, params: dict) -> dict:
        # Resolve origin and destination codes
        origin_code = params.get("origin","LIS_AIRPORT").upper().replace(" ","_")
        dest_code   = params.get("destination","CITY_CENTRE").upper().replace(" ","_")

        # Extract city code
        city = origin_code.split("_")[0] if "_" in origin_code else origin_code[:3]
        city = dest_code.split("_")[0] if "AIRPORT" not in origin_code else city

        # Determine coordinates
        if "AIRPORT" in origin_code:
            o_lat, o_lon = AIRPORT_COORDS.get(city, (0,0))
        else:
            o_lat, o_lon = CITY_COORDS.get(city[:3], (0,0))

        if "CENTRE" in dest_code or "CENTER" in dest_code or "CITY" in dest_code:
            d_lat, d_lon = CITY_COORDS.get(city, (0,0))
        elif "AIRPORT" in dest_code:
            d_lat, d_lon = AIRPORT_COORDS.get(city, (0,0))
        else:
            d_lat, d_lon = CITY_COORDS.get(dest_code[:3], CITY_COORDS.get(city,(0,0)))

        api_key = os.getenv("OPENROUTESERVICE_API_KEY","").strip()

        if api_key and api_key not in ("","demo","your_ors_key_here"):
            live = self._live_ors(api_key, o_lat, o_lon, d_lat, d_lon, city)
            if live:
                return live

        return self._haversine(o_lat, o_lon, d_lat, d_lon, city, origin_code, dest_code)

    def _live_ors(self, api_key, olat, olon, dlat, dlon, city):
        try:
            r = post(
                f"{ORS_BASE}/v2/directions/driving-car/geojson",
                json={"coordinates":[[olon,olat],[dlon,dlat]]},
                headers={"Authorization": api_key,
                         "Content-Type":  "application/json"},
                timeout=8,
            )
            if r.ok:
                feat = r.json()["features"][0]["properties"]["summary"]
                dist_km  = round(feat["distance"] / 1000, 1)
                dur_min  = round(feat["duration"] / 60)
                taxi_est = _taxi_estimate(dist_km, city)
                return {"data":{
                    "distance_km":    dist_km,
                    "drive_min":      dur_min,
                    "taxi_gbp_est":   taxi_est,
                    "public_option":  _public_transport(city, dur_min),
                    "advice":         f"Allow {dur_min + 15} min including traffic buffer.",
                    "source":         "openrouteservice_live",
                }}
        except Exception:
            pass
        return None

    def _haversine(self, olat, olon, dlat, dlon, city, orig, dest):
        if olat == 0 and olon == 0:
            return {"data":{"distance_km":15,"drive_min":30,"taxi_gbp_est":18,
                            "advice":"Transfer details not available for this route.",
                            "source":"estimated"}}

        R = 6371
        dlat_ = math.radians(dlat - olat)
        dlon_ = math.radians(dlon - olon)
        a = (math.sin(dlat_/2)**2 +
             math.cos(math.radians(olat)) * math.cos(math.radians(dlat)) *
             math.sin(dlon_/2)**2)
        dist_km  = round(R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a)), 1)
        speed_kph= 35   # average urban speed
        dur_min  = round(dist_km / speed_kph * 60)
        taxi_est = _taxi_estimate(dist_km, city)

        return {"data":{
            "distance_km":   dist_km,
            "drive_min":     dur_min,
            "taxi_gbp_est":  taxi_est,
            "public_option": _public_transport(city, dur_min),
            "advice":        f"Airport is {dist_km}km from city centre. Allow {dur_min + 10} min including traffic.",
            "source":        "calculated",
        }}

    def _score_confidence(self, r):
        src = r.get("data",{}).get("source","")
        return 0.97 if "live" in src else 0.85


def _taxi_estimate(dist_km: float, city: str) -> float:
    rates = {"DXB":2.5,"SIN":2.2,"LHR":2.8,"NRT":4.5,"JFK":3.0}
    rate  = rates.get(city, 1.8)
    return round(5 + dist_km * rate, 0)


def _public_transport(city: str, drive_min: int) -> str:
    metro_cities = {"LIS":"Metro (Linha Vermelha)","BCN":"L9 Sud Metro",
                    "MAD":"Metro Línea 8","ATH":"Metro Line 3",
                    "CDG":"RER B","AMS":"Sprinter train","ZRH":"ZVV train"}
    if city in metro_cities:
        return f"{metro_cities[city]} — approx {drive_min - 5}–{drive_min + 5} min"
    return f"Taxi or ride-share recommended — approx {drive_min} min"
