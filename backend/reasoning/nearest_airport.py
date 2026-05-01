"""
VoyageAI Nearest Airport Resolver — External API Edition
=========================================================
Resolves any destination text → nearest RELEVANT airport.

Zero hardcoded coordinates. All geocoding comes from external APIs:
  • Amadeus Location Search  (/v1/reference-data/locations)
  • OpenStreetMap Nominatim  (nominatim.openstreetmap.org/search)
  • Photon / Komoot          (photon.komoot.io/api)
  • LLM (Groq/Gemini)        (last resort — asks for lat/lon)

Airport lookup:
  • Amadeus Airport Nearest Relevant  (/v1/reference-data/locations/airports)
    Sorts by analytics.flights.score — returns the most USEFUL airport,
    not just geographically closest.
  • Haversine scan of local ref_airports DB  (offline fallback)

Flow:
  "Pushkar pilgrimage" or "Valley of the Kings" or "Angkor Wat"
    → geocoding_client.geocode(place)  → (lat, lon, provider)
    → amadeus.nearest_relevant_airports(lat, lon, radius=300)
      [or haversine_fallback if Amadeus unconfigured]
    → NearestAirportResult
    → "✈ Fly into Jaipur (JAI), then ~145km by car (2 hrs) to Pushkar"
"""
import math
import logging
import time
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("voyageai.reasoning")

# TTL cache — avoid redundant API calls for the same destination
_CACHE: dict[str, tuple[float, Optional["NearestAirportResult"]]] = {}
_CACHE_TTL = 3_600  # 1 hour


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class NearestAirportResult:
    query:              str
    iata:               str
    airport_name:       str
    airport_city:       str
    country_code:       str
    destination_name:   str
    distance_km:        float
    transfer_mode:      str   # car | train | boat | trek | tuk-tuk
    flight_score:       float # Amadeus analytics score (higher = busier airport)
    geo_source:         str   # amadeus | nominatim | photon | llm
    airport_source:     str   # amadeus | haversine
    requires_transfer:  bool

    @property
    def transfer_time(self) -> str:
        return _transfer_time(self.distance_km, self.transfer_mode)

    @property
    def transfer_advice(self) -> str:
        if not self.requires_transfer or self.distance_km < 5:
            return (f"✈ Direct flights available into {self.airport_city} "
                    f"Airport ({self.iata})")
        return _format_advice(
            self.transfer_mode, self.distance_km,
            self.destination_name, self.airport_city, self.iata
        )

    def to_dict(self) -> dict:
        return {
            "query":               self.query,
            "nearest_iata":        self.iata,
            "airport_name":        self.airport_name,
            "nearest_airport_city":self.airport_city,
            "country_code":        self.country_code,
            "destination":         self.destination_name,
            "distance_km":         round(self.distance_km),
            "transfer_mode":       self.transfer_mode,
            "transfer_time":       self.transfer_time,
            "transfer_advice":     self.transfer_advice,
            "flight_score":        self.flight_score,
            "geo_source":          self.geo_source,
            "airport_source":      self.airport_source,
            "requires_transfer":   self.requires_transfer,
        }


# ── Public API ────────────────────────────────────────────────────────────────

def find_nearest_airport(
    query: str,
    radius_km: int = 300,
    country_hint: str = "",
) -> Optional[NearestAirportResult]:
    """
    Find the nearest relevant airport for any place name.
    Caches results for 1 hour.
    """
    cache_key = f"{query.lower().strip()}|{country_hint}"
    if cache_key in _CACHE:
        ts, cached = _CACHE[cache_key]
        if time.time() - ts < _CACHE_TTL:
            return cached

    result = _resolve(query, radius_km, country_hint)
    _CACHE[cache_key] = (time.time(), result)
    return result


def find_nearest_by_coords(
    lat: float, lon: float,
    label: str = "destination",
    radius_km: int = 300,
    transfer_mode: str = "car",
) -> Optional[NearestAirportResult]:
    """Find nearest airport when coordinates are already known."""
    return _from_coords(label, lat, lon, radius_km, transfer_mode, "provided")


def geocoding_status() -> dict:
    """Expose geocoding provider availability for the health endpoint."""
    from mcp_servers.geocoding_client import geocoding_status as _gs
    return _gs()


# ── Core resolution ───────────────────────────────────────────────────────────

def _resolve(query: str, radius_km: int, country_hint: str) -> Optional[NearestAirportResult]:
    dest_name = query.strip().title()

    # Step 1 — Try direct IATA lookup (user may have typed a city WITH an airport)
    direct = _direct_airport_lookup(query)
    if direct:
        log.info("Direct airport for '%s': %s (%s)", query, direct.iata, direct.airport_city)
        return direct

    # Step 2 — Geocode: place name → (lat, lon)
    from mcp_servers.geocoding_client import geocode
    geo = geocode(query, country_hint)
    if not geo:
        log.warning("Could not geocode '%s' — all providers failed", query)
        return None
    lat, lon, geo_src = geo

    # Step 3 — Find nearest relevant airport from coordinates
    return _from_coords(dest_name, lat, lon, radius_km, "car", geo_src)


def _direct_airport_lookup(query: str) -> Optional[NearestAirportResult]:
    """
    If the place name maps directly to an airport city, return it immediately
    (no transfer required). Uses the reference cache city aliases.
    """
    try:
        from core.reference_cache import ref
        if not ref._built: ref.build()
        iata = ref.city_to_iata(query.lower().strip())
        if iata:
            ap = ref.airport(iata) or {}
            return NearestAirportResult(
                query             = query,
                iata              = iata,
                airport_name      = ap.get("name", iata),
                airport_city      = ap.get("city", iata),
                country_code      = ap.get("country_code", ""),
                destination_name  = query.title(),
                distance_km       = 0.0,
                transfer_mode     = "car",
                flight_score      = 100.0,  # direct airport
                geo_source        = "reference_cache",
                airport_source    = "reference_cache",
                requires_transfer = False,
            )
    except Exception as e:
        log.debug("Direct lookup error: %s", e)
    return None


def _from_coords(
    dest_name: str, lat: float, lon: float,
    radius_km: int, default_mode: str, geo_src: str,
) -> Optional[NearestAirportResult]:
    """Given coordinates, find the nearest relevant airport."""

    # Try Amadeus Airport Nearest Relevant API first
    result = _amadeus_nearest(dest_name, lat, lon, radius_km, default_mode, geo_src)
    if result:
        log.info(
            "Amadeus nearest airport: '%s' → %s (%s, %.0fkm, score=%.1f)",
            dest_name, result.iata, result.airport_city,
            result.distance_km, result.flight_score
        )
        return result

    # Fallback: Haversine scan of local DB
    result = _haversine_fallback(dest_name, lat, lon, radius_km, default_mode, geo_src)
    if result:
        log.info(
            "Haversine nearest airport: '%s' → %s (%.0fkm)",
            dest_name, result.iata, result.distance_km
        )
        return result

    log.warning("No airport found within %dkm of '%s' (%s, %s)", radius_km, dest_name, lat, lon)
    return None


# ── Airport resolution: Amadeus & Haversine ───────────────────────────────────

def _amadeus_nearest(
    dest_name: str, lat: float, lon: float,
    radius_km: int, default_mode: str, geo_src: str,
) -> Optional[NearestAirportResult]:
    """
    Amadeus Airport Nearest Relevant API.
    GET /v1/reference-data/locations/airports
    Sorts by analytics.flights.score — returns the busiest reachable airport.
    """
    try:
        from mcp_servers.amadeus_client import amadeus
        if not amadeus.configured:
            return None

        airports = amadeus.nearest_relevant_airports(
            lat=lat, lon=lon,
            radius=min(radius_km, 500),
            max_results=5,
            sort="analytics.flights.score",
        )
        if not airports:
            return None

        best      = airports[0]
        iata      = best.get("iataCode", "")
        name      = best.get("name", iata)
        city      = best.get("address", {}).get("cityName", iata)
        country   = best.get("address", {}).get("countryCode", "")
        dist_km   = float(best.get("distance", {}).get("value", 0))
        score     = float(best.get("analytics", {}).get("flights", {}).get("score", 0))
        mode      = _infer_mode(default_mode, dist_km, dest_name)

        return NearestAirportResult(
            query             = dest_name,
            iata              = iata,
            airport_name      = name,
            airport_city      = city,
            country_code      = country,
            destination_name  = dest_name,
            distance_km       = dist_km,
            transfer_mode     = mode,
            flight_score      = score,
            geo_source        = geo_src,
            airport_source    = "amadeus",
            requires_transfer = dist_km > 5,
        )
    except Exception as e:
        log.debug("Amadeus nearest airports error: %s", e)
    return None


def _haversine_fallback(
    dest_name: str, lat: float, lon: float,
    radius_km: int, default_mode: str, geo_src: str,
) -> Optional[NearestAirportResult]:
    """Offline fallback — haversine scan of ref_airports SQLite table."""
    try:
        import sqlite3
        from pathlib import Path
        db  = Path(__file__).parent.parent / "data" / "voyageai.db"
        con = sqlite3.connect(str(db))
        rows = con.execute(
            "SELECT iata, name, city, country_code, lat, lon "
            "FROM ref_airports WHERE lat IS NOT NULL AND lat != 0 AND lat != ''"
        ).fetchall()
        con.close()

        best_row, best_km = None, float("inf")
        for row in rows:
            try:
                km = _haversine_km(lat, lon, float(row[4]), float(row[5]))
                if km < best_km:
                    best_km, best_row = km, row
            except (TypeError, ValueError):
                pass

        if best_row is None or best_km > radius_km:
            return None

        mode = _infer_mode(default_mode, best_km, dest_name)
        return NearestAirportResult(
            query             = dest_name,
            iata              = best_row[0],
            airport_name      = best_row[1] or best_row[0],
            airport_city      = best_row[2] or best_row[0],
            country_code      = best_row[3] or "",
            destination_name  = dest_name,
            distance_km       = best_km,
            transfer_mode     = mode,
            flight_score      = 0.0,
            geo_source        = geo_src,
            airport_source    = "haversine",
            requires_transfer = best_km > 5,
        )
    except Exception as e:
        log.debug("Haversine fallback error: %s", e)
    return None


# ── Utilities ─────────────────────────────────────────────────────────────────

def _infer_mode(base: str, dist_km: float, dest: str) -> str:
    """Infer the best ground transfer mode from destination keywords + distance."""
    d = dest.lower()
    if any(k in d for k in ["trek", "hike", "peak", "summit", "base camp",
                             "kedarnath", "hemkund", "everest"]):
        return "trek"
    if any(k in d for k in ["island", "bay", "reef", "okavango", "halong",
                             "galapagos", "backwater"]):
        return "boat"
    if any(k in d for k in ["machu picchu", "cinque terre", "nikko",
                             "fuji", "darjeeling toy train"]):
        return "train"
    if any(k in d for k in ["angkor", "siem reap", "cambodia"]):
        return "tuk-tuk"
    if base and base not in ("car", ""):
        return base
    if dist_km > 300:
        return "car/train"
    return "car"


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def _transfer_time(km: float, mode: str) -> str:
    if km < 5:
        return "on-site"
    speeds = {"car": 70, "train": 110, "bus": 50, "boat": 25,
              "trek": 4, "tuk-tuk": 35, "car/boat": 55, "car/train": 80}
    speed = speeds.get(mode.split("/")[0].split("(")[0].strip(), 65)
    hrs   = km / speed
    if hrs < 1:       return f"{round(hrs * 60)} min"
    if hrs < 2:       return f"{hrs:.1f} hrs"
    return            f"{round(hrs)} hrs"


def _format_advice(mode: str, km: float, dest: str,
                   airport_city: str, iata: str) -> str:
    time = _transfer_time(km, mode)
    phrases = {
        "car":       f"~{round(km)}km by private taxi or hire car ({time})",
        "train":     f"~{round(km)}km by train ({time})",
        "bus":       f"~{round(km)}km by coach or local bus ({time})",
        "boat":      f"~{round(km)}km by boat transfer ({time})",
        "trek":      f"~{round(km)}km trek from the trailhead ({time}) — plan extra days",
        "tuk-tuk":   f"~{round(km)}km by tuk-tuk or remork ({time})",
        "car/boat":  f"~{round(km)}km by road then boat ({time})",
        "car/train": f"~{round(km)}km by car or regional train ({time})",
    }
    phrase = phrases.get(mode, f"~{round(km)}km by {mode} ({time})")
    return (
        f"✈ Fly into {airport_city} Airport ({iata}), "
        f"then {phrase} to {dest}. "
        f"We recommend pre-booking your ground transfer."
    )
