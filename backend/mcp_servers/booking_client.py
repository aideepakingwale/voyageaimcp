"""
Booking.com Demand API client for accommodation search.

Official docs used for this integration:
- https://developers.booking.com/demand/docs/open-api/demand-api/accommodations
- https://developers.booking.com/demand/docs/getting-started/sandbox
"""
import logging
import os

from .http_client import post

log = logging.getLogger(__name__)

BOOKING_BASE = os.getenv(
    "BOOKING_API_BASE",
    "https://demandapi-sandbox.booking.com/3.1",
).rstrip("/")
BOOKING_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
}


class BookingClient:
    def __init__(self):
        self._token = os.getenv("BOOKING_API_TOKEN", "").strip()
        self._affiliate_id = os.getenv("BOOKING_AFFILIATE_ID", "").strip()
        self._booker_country = os.getenv("BOOKING_BOOKER_COUNTRY", "gb").strip().lower() or "gb"
        self._booker_platform = os.getenv("BOOKING_BOOKER_PLATFORM", "desktop").strip().lower() or "desktop"
        self.last_diagnostic = {}

    @property
    def configured(self) -> bool:
        return bool(self._token and self._affiliate_id)

    def _set_diag(self, operation: str, **data) -> None:
        self.last_diagnostic[operation] = data

    def _debug_log(self):
        try:
            from core.logging_config import get_logger

            return get_logger("mcp.booking")
        except Exception:
            return log

    def _redact_headers(self, headers: dict | None) -> dict:
        safe = dict(headers or {})
        if "Authorization" in safe:
            safe["Authorization"] = "Bearer ***REDACTED***"
        return safe

    def _response_object(self, response) -> dict:
        try:
            parsed = response.json()
        except Exception:
            parsed = None
        return {
            "status_code": response.status_code,
            "ok": response.ok,
            "url": getattr(response, "url", ""),
            "elapsed_ms": round(
                getattr(getattr(response, "elapsed", None), "total_seconds", lambda: 0)()
                * 1000,
                1,
            ),
            "headers": dict(getattr(response, "headers", {}) or {}),
            "json": parsed,
            "text": (response.text or "")[:4000],
        }

    def _log_request(self, operation: str, method: str, url: str,
                     headers: dict | None = None, payload: dict | None = None) -> None:
        self._debug_log().debug("Booking API request", extra={
            "operation": operation,
            "method": method,
            "url": url,
            "headers": self._redact_headers(headers),
            "json": payload or {},
        })

    def _log_response(self, operation: str, response=None,
                      error: Exception | None = None) -> None:
        extra = {"operation": operation}
        if response is not None:
            extra["response"] = self._response_object(response)
        if error is not None:
            extra["error"] = {"type": type(error).__name__, "message": str(error)}
        self._debug_log().debug("Booking API response", extra=extra)

    def _auth_headers(self) -> dict | None:
        if not self.configured:
            self._set_diag(
                "auth",
                status="not_configured",
                reason="BOOKING_API_TOKEN or BOOKING_AFFILIATE_ID is missing.",
            )
            return None
        self._set_diag("auth", status="ok")
        return {
            **BOOKING_HEADERS,
            "Authorization": f"Bearer {self._token}",
            "X-Affiliate-Id": self._affiliate_id,
        }

    def _booker(self) -> dict:
        return {
            "country": self._booker_country,
            "platform": self._booker_platform,
            "travel_purpose": "leisure",
        }

    def search_accommodations(self, airport_code: str, check_in: str,
                              check_out: str, adults: int, rooms: int,
                              currency: str = "GBP", rows: int = 20) -> list[dict]:
        headers = self._auth_headers()
        if not headers:
            self._set_diag("accommodations_search", status="auth_unavailable",
                           auth=self.last_diagnostic.get("auth", {}))
            return []

        payload = {
            "booker": self._booker(),
            "checkin": check_in,
            "checkout": check_out,
            "airport": airport_code,
            "currency": currency,
            "extras": ["extra_charges", "products"],
            "guests": {
                "number_of_adults": max(1, adults),
                "number_of_rooms": max(1, rooms),
            },
            "rows": max(10, min(rows, 100)),
        }
        url = f"{BOOKING_BASE}/accommodations/search"
        self._log_request("accommodations_search", "POST", url,
                          headers=headers, payload=payload)
        try:
            response = post(url, json=payload, headers=headers, timeout=20)
            self._log_response("accommodations_search", response=response)
            if response.ok:
                body = response.json() or {}
                data = body.get("data", []) or []
                self._set_diag(
                    "accommodations_search",
                    status="ok",
                    count=len(data),
                    request={
                        "airport": airport_code,
                        "check_in": check_in,
                        "check_out": check_out,
                        "adults": adults,
                        "rooms": rooms,
                        "currency": currency,
                    },
                )
                return data
            self._set_diag(
                "accommodations_search",
                status="http_error",
                http_status=response.status_code,
                body=response.text[:1000],
                request={
                    "airport": airport_code,
                    "check_in": check_in,
                    "check_out": check_out,
                    "adults": adults,
                    "rooms": rooms,
                    "currency": currency,
                },
            )
            log.warning("Booking accommodation search failed: %s %s",
                        response.status_code, response.text[:200])
        except Exception as exc:
            self._log_response("accommodations_search", error=exc)
            self._set_diag(
                "accommodations_search",
                status="exception",
                error=str(exc),
                request={
                    "airport": airport_code,
                    "check_in": check_in,
                    "check_out": check_out,
                    "adults": adults,
                    "rooms": rooms,
                    "currency": currency,
                },
            )
            log.warning("Booking accommodation search error: %s", exc)
        return []


booking = BookingClient()
