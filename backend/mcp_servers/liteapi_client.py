"""
LiteAPI client for hotel rate and availability search.

Official docs:
- https://docs.liteapi.travel/reference/authentication
- https://docs.liteapi.travel/reference/post_hotels-rates
"""
import logging
import os

from .http_client import post

log = logging.getLogger(__name__)

LITEAPI_BASE = os.getenv("LITEAPI_API_BASE", "https://api.liteapi.travel/v3.0").rstrip("/")
LITEAPI_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
}


class LiteAPIClient:
    def __init__(self):
        self._api_key = os.getenv("LITEAPI_API_KEY", "").strip()
        self._guest_nationality = os.getenv("LITEAPI_GUEST_NATIONALITY", "GB").strip().upper() or "GB"
        self.last_diagnostic = {}

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def _set_diag(self, operation: str, **data) -> None:
        self.last_diagnostic[operation] = data

    def _debug_log(self):
        try:
            from core.logging_config import get_logger
            return get_logger("mcp.liteapi")
        except Exception:
            return log

    def _redact_headers(self, headers: dict | None) -> dict:
        safe = dict(headers or {})
        if "X-API-Key" in safe:
            safe["X-API-Key"] = "***REDACTED***"
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
                getattr(getattr(response, "elapsed", None), "total_seconds", lambda: 0)() * 1000,
                1,
            ),
            "headers": dict(getattr(response, "headers", {}) or {}),
            "json": parsed,
            "text": (response.text or "")[:4000],
        }

    def _log_request(self, operation: str, method: str, url: str,
                     headers: dict | None = None, payload: dict | None = None) -> None:
        self._debug_log().debug("LiteAPI request", extra={
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
        self._debug_log().debug("LiteAPI response", extra=extra)

    def _auth_headers(self) -> dict | None:
        if not self.configured:
            self._set_diag("auth", status="not_configured", reason="LITEAPI_API_KEY is missing.")
            return None
        self._set_diag("auth", status="ok")
        return {
            **LITEAPI_HEADERS,
            "X-API-Key": self._api_key,
        }

    def search_rates(self, iata_code: str, check_in: str, check_out: str,
                     adults: int, rooms: int, currency: str = "GBP",
                     limit: int = 20, min_stars: int | None = None) -> list[dict]:
        headers = self._auth_headers()
        if not headers:
            self._set_diag("hotel_rates", status="auth_unavailable",
                           auth=self.last_diagnostic.get("auth", {}))
            return []

        occupancies = [{"adults": max(1, adults // max(1, rooms)), "children": []} for _ in range(max(1, rooms))]
        remaining_adults = max(0, adults - sum(o["adults"] for o in occupancies))
        for idx in range(remaining_adults):
            occupancies[idx % len(occupancies)]["adults"] += 1

        payload = {
            "checkin": check_in,
            "checkout": check_out,
            "currency": currency,
            "guestNationality": self._guest_nationality,
            "occupancies": occupancies,
            "iataCode": iata_code,
            "includeHotelData": True,
            "limit": max(1, min(limit, 100)),
        }
        if min_stars:
            payload["starRating"] = [float(star) for star in range(int(min_stars), 6)]

        url = f"{LITEAPI_BASE}/hotels/rates"
        self._log_request("hotel_rates", "POST", url, headers=headers, payload=payload)
        try:
            response = post(url, json=payload, headers=headers, timeout=20)
            self._log_response("hotel_rates", response=response)
            if response.ok:
                body = response.json() or {}
                data = body.get("data", body if isinstance(body, list) else []) or []
                self._set_diag("hotel_rates", status="ok", count=len(data), request={
                    "iataCode": iata_code,
                    "check_in": check_in,
                    "check_out": check_out,
                    "adults": adults,
                    "rooms": rooms,
                    "currency": currency,
                })
                return data
            self._set_diag("hotel_rates", status="http_error",
                           http_status=response.status_code,
                           body=response.text[:1000],
                           request={
                               "iataCode": iata_code,
                               "check_in": check_in,
                               "check_out": check_out,
                               "adults": adults,
                               "rooms": rooms,
                               "currency": currency,
                           })
            log.warning("LiteAPI hotel rates failed: %s %s", response.status_code, response.text[:200])
        except Exception as exc:
            self._log_response("hotel_rates", error=exc)
            self._set_diag("hotel_rates", status="exception", error=str(exc), request={
                "iataCode": iata_code,
                "check_in": check_in,
                "check_out": check_out,
                "adults": adults,
                "rooms": rooms,
                "currency": currency,
            })
            log.warning("LiteAPI hotel rates error: %s", exc)
        return []


liteapi = LiteAPIClient()
