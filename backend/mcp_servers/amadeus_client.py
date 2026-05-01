"""
Amadeus API Client — shared token management.
All Amadeus-based MCP servers share this single client to avoid
redundant token fetches (tokens are valid for 29 min).

Free sandbox: developers.amadeus.com (no credit card required)
Sandbox returns real airline/hotel data with test fares.
"""
import os
import time
import logging
from .http_client import post, get
import logging
log = logging.getLogger(__name__)

log = logging.getLogger(__name__)

AMADEUS_AUTH_URL    = "https://test.api.amadeus.com/v1/security/oauth2/token"
AMADEUS_BASE        = "https://test.api.amadeus.com"


class AmadeusClient:
    """Thread-safe Amadeus client with automatic token refresh."""

    def __init__(self):
        self._client_id  = os.getenv("AMADEUS_CLIENT_ID",  "").strip()
        self._client_sec = os.getenv("AMADEUS_CLIENT_SECRET", "").strip()
        self._token      = None
        self._expires_at = 0.0

    @property
    def configured(self) -> bool:
        return bool(self._client_id and self._client_sec)

    def _refresh_token(self) -> bool:
        """Fetch a new OAuth token. Returns True on success."""
        try:
            r = post(
                AMADEUS_AUTH_URL,
                data={
                    "grant_type":    "client_credentials",
                    "client_id":     self._client_id,
                    "client_secret": self._client_sec,
                },
                timeout=6,
            )
            if r.ok:
                d = r.json()
                self._token      = d["access_token"]
                self._expires_at = time.time() + d.get("expires_in", 1740) - 60
                return True
            log.warning("Amadeus token refresh failed: %s %s", r.status_code, r.text[:200])
        except Exception as e:
            log.warning("Amadeus token refresh error: %s", e)
        return False

    def _auth_header(self) -> dict | None:
        if not self.configured:
            return None
        if time.time() >= self._expires_at:
            if not self._refresh_token():
                return None
        return {"Authorization": f"Bearer {self._token}"}

    def flight_offers(self, origin: str, destination: str, date: str,
                      adults: int = 1, direct_only: bool = False,
                      currency: str = "GBP", max_results: int = 8) -> list[dict]:
        """Search flight offers. Returns list of parsed offer dicts."""
        headers = self._auth_header()
        if not headers:
            return []
        try:
            r = get(
                f"{AMADEUS_BASE}/v2/shopping/flight-offers",
                params={
                    "originLocationCode":      origin,
                    "destinationLocationCode": destination,
                    "departureDate":           date,
                    "adults":                  adults,
                    "nonStop":                 str(direct_only).lower(),
                    "currencyCode":            currency,
                    "max":                     max_results,
                },
                headers=headers,
                timeout=10,
            )
            if r.ok:
                return r.json().get("data", [])
            if r.status_code == 500:
                log.debug("Amadeus sandbox 500 on flights — using fallback")
            else:
                log.warning("Amadeus flight search %s: %s", r.status_code, r.text[:200])
        except Exception as e:
            log.debug("Amadeus flight error (fallback will be used): %s", type(e).__name__)
        return []

    def hotel_list(self, city_code: str, radius: int = 5,
                   amenities: list = None) -> list[dict]:
        """Get hotels in a city."""
        headers = self._auth_header()
        if not headers:
            return []
        params = {
            "cityCode": city_code,
            "radius":   radius,
            "radiusUnit": "KM",
        }
        if amenities:
            params["amenities"] = ",".join(amenities)
        try:
            r = get(f"{AMADEUS_BASE}/v1/reference-data/locations/hotels/by-city",
                    params=params, headers=headers, timeout=10)
            if r.ok:
                return r.json().get("data", [])
            if r.status_code == 500:
                log.debug("Amadeus sandbox 500 on hotels — using fallback")
            else:
                log.warning("Amadeus hotel list %s: %s", r.status_code, r.text[:200])
        except Exception as e:
            log.warning("Amadeus hotel list error: %s", e)
        return []

    def hotel_offers(self, hotel_ids: list[str], check_in: str,
                     check_out: str, adults: int = 2,
                     currency: str = "GBP") -> list[dict]:
        """Get offers for specific hotel IDs."""
        headers = self._auth_header()
        if not headers or not hotel_ids:
            return []
        try:
            r = get(
                f"{AMADEUS_BASE}/v3/shopping/hotel-offers",
                params={
                    "hotelIds":  ",".join(hotel_ids[:20]),
                    "checkInDate":  check_in,
                    "checkOutDate": check_out,
                    "adults":       adults,
                    "currency":     currency,
                    "bestRateOnly": "true",
                },
                headers=headers,
                timeout=12,
            )
            if r.ok:
                return r.json().get("data", [])
            if r.status_code == 500:
                log.debug("Amadeus sandbox 500 on hotel offers — using fallback")
            else:
                log.warning("Amadeus hotel offers %s: %s", r.status_code, r.text[:200])
        except Exception as e:
            log.warning("Amadeus hotel offers error: %s", e)
        return []

    def activities(self, lat: float, lon: float,
                   radius: int = 20) -> list[dict]:
        """Get activities/experiences near a location."""
        headers = self._auth_header()
        if not headers:
            return []
        try:
            r = get(
                f"{AMADEUS_BASE}/v1/shopping/activities",
                params={"latitude": lat, "longitude": lon, "radius": radius},
                headers=headers,
                timeout=10,
            )
            if r.ok:
                return r.json().get("data", [])
            if r.status_code == 500:
                log.debug("Amadeus sandbox 500 on activities — using fallback")
            else:
                log.warning("Amadeus activities %s: %s", r.status_code, r.text[:200])
        except Exception as e:
            log.warning("Amadeus activities error: %s", e)
        return []

    def nearest_relevant_airports(
        self,
        lat: float,
        lon: float,
        radius: int = 500,
        max_results: int = 5,
        sort: str = "analytics.flights.score",
    ) -> list[dict]:
        """
        Airport Nearest Relevant API.
        Docs: https://developers.amadeus.com/self-service/category/flights/
              api-doc/airport-nearest-relevant/api-reference
        Endpoint: GET /v1/reference-data/locations/airports
        Returns airports sorted by analytics (flight traffic score) —
        the most *useful* airport near a location, not just the geographically closest.

        Each result dict:
          iataCode, name, address.cityName, address.countryCode,
          geoCode.latitude, geoCode.longitude,
          distance.value (km), distance.unit,
          analytics.flights.score, analytics.travelers.score
        """
        headers = self._auth_header()
        if not headers:
            return []
        try:
            r = get(
                f"{AMADEUS_BASE}/v1/reference-data/locations/airports",
                params={
                    "latitude":   round(lat, 6),
                    "longitude":  round(lon, 6),
                    "radius":     radius,
                    "page[limit]":max_results,
                    "sort":       sort,
                },
                headers=headers,
                timeout=10,
            )
            if r.ok:
                data = r.json().get("data", [])
                log.info("Amadeus nearest airports: found %d results for (%s,%s)",
                         len(data), lat, lon)
                return data
            log.warning("Amadeus nearest airports %s: %s", r.status_code, r.text[:200])
        except Exception as e:
            log.warning("Amadeus nearest airports error: %s", e)
        return []

    def geocode_place(self, place_name: str) -> tuple[float, float] | None:
        """
        Convert a place name to lat/lon using the Amadeus Location Search API.
        Endpoint: GET /v1/reference-data/locations
        keyword: the place name, subType: CITY or AIRPORT

        Returns (lat, lon) or None.
        """
        headers = self._auth_header()
        if not headers:
            return None
        try:
            r = get(
                f"{AMADEUS_BASE}/v1/reference-data/locations",
                params={
                    "keyword":  place_name,
                    "subType":  "CITY,AIRPORT",
                    "page[limit]": 3,
                },
                headers=headers,
                timeout=8,
            )
            if r.ok:
                items = r.json().get("data", [])
                for item in items:
                    geo = item.get("geoCode", {})
                    lat = geo.get("latitude")
                    lon = geo.get("longitude")
                    if lat and lon:
                        log.info("Amadeus geocode '%s' → (%s, %s)", place_name, lat, lon)
                        return float(lat), float(lon)
            log.debug("Amadeus geocode %s: %s", r.status_code, r.text[:200])
        except Exception as e:
            log.debug("Amadeus geocode error: %s", e)
        return None


# Module-level singleton
amadeus = AmadeusClient()
