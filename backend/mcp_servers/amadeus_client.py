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
AMADEUS_JSON_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
}
AMADEUS_FORM_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/x-www-form-urlencoded",
}


class AmadeusClient:
    """Thread-safe Amadeus client with automatic token refresh."""

    def __init__(self):
        self._client_id  = os.getenv("AMADEUS_CLIENT_ID",  "").strip()
        self._client_sec = os.getenv("AMADEUS_CLIENT_SECRET", "").strip()
        self._token      = None
        self._expires_at = 0.0
        self.last_diagnostic = {}

    def _set_diag(self, operation: str, **data) -> None:
        self.last_diagnostic[operation] = data

    def _debug_log(self):
        try:
            from core.logging_config import get_logger
            return get_logger("mcp.amadeus")
        except Exception:
            return log

    def _redact_headers(self, headers: dict | None) -> dict:
        safe = dict(headers or {})
        if "Authorization" in safe:
            safe["Authorization"] = "Bearer ***REDACTED***"
        return safe

    def _redact_payload(self, payload):
        if not isinstance(payload, dict):
            return payload
        safe = dict(payload)
        for key in ("client_secret", "access_token", "token"):
            if key in safe:
                safe[key] = "***REDACTED***"
        if "client_id" in safe and safe["client_id"]:
            safe["client_id"] = f"{str(safe['client_id'])[:6]}***"
        return safe

    def _response_object(self, r) -> dict:
        try:
            parsed = r.json()
        except Exception:
            parsed = None
        return {
            "status_code": r.status_code,
            "ok": r.ok,
            "url": getattr(r, "url", ""),
            "elapsed_ms": round(getattr(getattr(r, "elapsed", None), "total_seconds", lambda: 0)() * 1000, 1),
            "headers": dict(getattr(r, "headers", {}) or {}),
            "json": parsed,
            "text": (r.text or "")[:4000],
        }

    def _log_request(self, operation: str, method: str, url: str,
                     params: dict | None = None, headers: dict | None = None,
                     data: dict | None = None) -> None:
        self._debug_log().debug("Amadeus API request", extra={
            "operation": operation,
            "method": method,
            "url": url,
            "params": params or {},
            "headers": self._redact_headers(headers),
            "data": self._redact_payload(data or {}),
        })

    def _log_response(self, operation: str, response=None, error: Exception | None = None) -> None:
        extra = {"operation": operation}
        if response is not None:
            extra["response"] = self._response_object(response)
        if error is not None:
            extra["error"] = {
                "type": type(error).__name__,
                "message": str(error),
            }
        self._debug_log().debug("Amadeus API response", extra=extra)

    @property
    def configured(self) -> bool:
        return bool(self._client_id and self._client_sec)

    def _refresh_token(self) -> bool:
        """Fetch a new OAuth token. Returns True on success."""
        data = {
            "grant_type":    "client_credentials",
            "client_id":     self._client_id,
            "client_secret": self._client_sec,
        }
        self._log_request("auth", "POST", AMADEUS_AUTH_URL,
                          headers=AMADEUS_FORM_HEADERS, data=data)
        try:
            r = post(
                AMADEUS_AUTH_URL,
                data=data,
                headers=AMADEUS_FORM_HEADERS,
                timeout=6,
            )
            self._log_response("auth", response=r)
            if r.ok:
                d = r.json()
                self._token      = d["access_token"]
                self._expires_at = time.time() + d.get("expires_in", 1740) - 60
                self._set_diag("auth", status="ok")
                return True
            self._set_diag("auth", status="http_error", http_status=r.status_code,
                           body=r.text[:500])
            log.warning("Amadeus token refresh failed: %s %s", r.status_code, r.text[:200])
        except Exception as e:
            self._log_response("auth", error=e)
            self._set_diag("auth", status="exception", error=str(e))
            log.warning("Amadeus token refresh error: %s", e)
        return False

    def _auth_header(self) -> dict | None:
        if not self.configured:
            self._set_diag("auth", status="not_configured",
                           reason="AMADEUS_CLIENT_ID or AMADEUS_CLIENT_SECRET is missing.")
            return None
        if time.time() >= self._expires_at:
            if not self._refresh_token():
                return None
        return {
            **AMADEUS_JSON_HEADERS,
            "Authorization": f"Bearer {self._token}",
        }

    def flight_offers(self, origin: str, destination: str, date: str,
                      adults: int = 1, direct_only: bool = False,
                      currency: str | None = "GBP", max_results: int = 8) -> list[dict]:
        """Search flight offers. Returns list of parsed offer dicts."""
        headers = self._auth_header()
        if not headers:
            self._set_diag("flight_offers", status="auth_unavailable",
                           auth=self.last_diagnostic.get("auth", {}))
            return []
        req = {
            "origin": origin, "destination": destination, "date": date,
            "adults": adults, "direct_only": direct_only,
        }
        params = {
            "originLocationCode":      origin,
            "destinationLocationCode": destination,
            "departureDate":           date,
            "adults":                  adults,
            "nonStop":                 str(direct_only).lower(),
            "max":                     max_results,
        }
        if currency:
            params["currencyCode"] = currency
        url = f"{AMADEUS_BASE}/v2/shopping/flight-offers"
        self._log_request("flight_offers", "GET", url, params=params, headers=headers)
        try:
            r = get(
                url,
                params=params,
                headers=headers,
                timeout=10,
            )
            self._log_response("flight_offers", response=r)
            if r.ok:
                data = r.json().get("data", [])
                self._set_diag("flight_offers", status="ok", count=len(data), request=req)
                return data
            self._set_diag("flight_offers", status="http_error",
                           http_status=r.status_code, body=r.text[:500],
                           request=req)
            if r.status_code == 500:
                log.debug("Amadeus sandbox 500 on flights — using fallback")
            else:
                log.warning("Amadeus flight search %s: %s", r.status_code, r.text[:200])
        except Exception as e:
            self._log_response("flight_offers", error=e)
            self._set_diag("flight_offers", status="exception", error=str(e),
                           request=req)
            log.debug("Amadeus flight error (fallback will be used): %s", type(e).__name__)
        return []

    def hotel_list(self, city_code: str, radius: int = 5,
                   amenities: list = None) -> list[dict]:
        """Get hotels in a city."""
        headers = self._auth_header()
        if not headers:
            self._set_diag("hotel_list", status="auth_unavailable",
                           auth=self.last_diagnostic.get("auth", {}))
            return []
        params = {
            "cityCode": city_code,
            "radius":   radius,
            "radiusUnit": "KM",
        }
        if amenities:
            params["amenities"] = ",".join(amenities)
        url = f"{AMADEUS_BASE}/v1/reference-data/locations/hotels/by-city"
        self._log_request("hotel_list", "GET", url, params=params, headers=headers)
        try:
            r = get(url, params=params, headers=headers, timeout=10)
            self._log_response("hotel_list", response=r)
            if r.ok:
                data = r.json().get("data", [])
                self._set_diag("hotel_list", status="ok", count=len(data), request=params)
                return data
            self._set_diag("hotel_list", status="http_error",
                           http_status=r.status_code, body=r.text[:500],
                           request=params)
            if r.status_code == 500:
                log.debug("Amadeus sandbox 500 on hotels — using fallback")
            else:
                log.warning("Amadeus hotel list %s: %s", r.status_code, r.text[:200])
        except Exception as e:
            self._log_response("hotel_list", error=e)
            self._set_diag("hotel_list", status="exception", error=str(e),
                           request=params)
            log.warning("Amadeus hotel list error: %s", e)
        return []

    def hotel_list_by_geocode(self, lat: float, lon: float,
                              radius: int = 10,
                              amenities: list = None) -> list[dict]:
        """Get hotels near latitude/longitude."""
        headers = self._auth_header()
        if not headers:
            self._set_diag("hotel_list_by_geocode", status="auth_unavailable",
                           auth=self.last_diagnostic.get("auth", {}))
            return []
        params = {
            "latitude":  round(float(lat), 6),
            "longitude": round(float(lon), 6),
            "radius":    radius,
            "radiusUnit": "KM",
        }
        if amenities:
            params["amenities"] = ",".join(amenities)
        url = f"{AMADEUS_BASE}/v1/reference-data/locations/hotels/by-geocode"
        self._log_request("hotel_list_by_geocode", "GET", url, params=params, headers=headers)
        try:
            r = get(url, params=params, headers=headers, timeout=10)
            self._log_response("hotel_list_by_geocode", response=r)
            if r.ok:
                data = r.json().get("data", [])
                self._set_diag("hotel_list_by_geocode", status="ok", count=len(data), request=params)
                return data
            self._set_diag("hotel_list_by_geocode", status="http_error",
                           http_status=r.status_code, body=r.text[:500],
                           request=params)
            log.warning("Amadeus hotel geocode list %s: %s", r.status_code, r.text[:200])
        except Exception as e:
            self._log_response("hotel_list_by_geocode", error=e)
            self._set_diag("hotel_list_by_geocode", status="exception", error=str(e),
                           request=params)
            log.warning("Amadeus hotel geocode list error: %s", e)
        return []

    def hotel_offers(self, hotel_ids: list[str], check_in: str,
                     check_out: str, adults: int = 2,
                     currency: str | None = "GBP",
                     max_ids: int = 20) -> list[dict]:
        """Get offers for specific hotel IDs."""
        headers = self._auth_header()
        if not headers or not hotel_ids:
            self._set_diag("hotel_offers", status="auth_or_ids_unavailable",
                           hotel_count=len(hotel_ids or []),
                           auth=self.last_diagnostic.get("auth", {}))
            return []
        req = {
            "hotel_count": len(hotel_ids), "check_in": check_in,
            "check_out": check_out, "adults": adults, "max_ids": max_ids,
        }
        params = {
            "hotelIds":  ",".join(hotel_ids[:max_ids]),
            "checkInDate":  check_in,
            "checkOutDate": check_out,
            "adults":       adults,
            "bestRateOnly": "true",
        }
        if currency:
            params["currency"] = currency
        url = f"{AMADEUS_BASE}/v3/shopping/hotel-offers"
        self._log_request("hotel_offers", "GET", url, params=params, headers=headers)
        try:
            r = get(
                url,
                params=params,
                headers=headers,
                timeout=12,
            )
            self._log_response("hotel_offers", response=r)
            if r.ok:
                data = r.json().get("data", [])
                self._set_diag("hotel_offers", status="ok", count=len(data), request=req)
                return data
            self._set_diag("hotel_offers", status="http_error",
                           http_status=r.status_code, body=r.text[:500],
                           request=req)
            if r.status_code == 500:
                log.debug("Amadeus sandbox 500 on hotel offers — using fallback")
            else:
                log.warning("Amadeus hotel offers %s: %s", r.status_code, r.text[:200])
        except Exception as e:
            self._log_response("hotel_offers", error=e)
            self._set_diag("hotel_offers", status="exception", error=str(e),
                           request=req)
            log.warning("Amadeus hotel offers error: %s", e)
        return []

    def activities(self, lat: float, lon: float,
                   radius: int = 20) -> list[dict]:
        """Get activities/experiences near a location."""
        headers = self._auth_header()
        if not headers:
            return []
        url = f"{AMADEUS_BASE}/v1/shopping/activities"
        params = {"latitude": lat, "longitude": lon, "radius": radius}
        self._log_request("activities", "GET", url, params=params, headers=headers)
        try:
            r = get(
                url,
                params=params,
                headers=headers,
                timeout=10,
            )
            self._log_response("activities", response=r)
            if r.ok:
                return r.json().get("data", [])
            if r.status_code == 500:
                log.debug("Amadeus sandbox 500 on activities — using fallback")
            else:
                log.warning("Amadeus activities %s: %s", r.status_code, r.text[:200])
        except Exception as e:
            self._log_response("activities", error=e)
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
        url = f"{AMADEUS_BASE}/v1/reference-data/locations/airports"
        params = {
            "latitude":   round(lat, 6),
            "longitude":  round(lon, 6),
            "radius":     radius,
            "page[limit]":max_results,
            "sort":       sort,
        }
        self._log_request("nearest_relevant_airports", "GET", url, params=params, headers=headers)
        try:
            r = get(
                url,
                params=params,
                headers=headers,
                timeout=10,
            )
            self._log_response("nearest_relevant_airports", response=r)
            if r.ok:
                data = r.json().get("data", [])
                log.info("Amadeus nearest airports: found %d results for (%s,%s)",
                         len(data), lat, lon)
                return data
            log.warning("Amadeus nearest airports %s: %s", r.status_code, r.text[:200])
        except Exception as e:
            self._log_response("nearest_relevant_airports", error=e)
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
        url = f"{AMADEUS_BASE}/v1/reference-data/locations"
        params = {
            "keyword":  place_name,
            "subType":  "CITY,AIRPORT",
            "page[limit]": 3,
        }
        self._log_request("geocode_place", "GET", url, params=params, headers=headers)
        try:
            r = get(
                url,
                params=params,
                headers=headers,
                timeout=8,
            )
            self._log_response("geocode_place", response=r)
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
            self._log_response("geocode_place", error=e)
            log.debug("Amadeus geocode error: %s", e)
        return None


# Module-level singleton
amadeus = AmadeusClient()
