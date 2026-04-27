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
            log.warning("Amadeus flight search %s: %s", r.status_code, r.text[:300])
        except Exception as e:
            log.warning("Amadeus flight error: %s", e)
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
            log.warning("Amadeus hotel list %s: %s", r.status_code, r.text[:300])
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
            log.warning("Amadeus hotel offers %s: %s", r.status_code, r.text[:300])
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
            log.warning("Amadeus activities %s: %s", r.status_code, r.text[:300])
        except Exception as e:
            log.warning("Amadeus activities error: %s", e)
        return []


# Module-level singleton
amadeus = AmadeusClient()
