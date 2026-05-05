"""
Duffel API client for flight offer requests.

Official docs used for this integration:
- https://duffel.com/docs/api/v2/offer-requests
"""
import logging
import os
from urllib.parse import urlencode

from .http_client import post

log = logging.getLogger(__name__)

DUFFEL_BASE = os.getenv("DUFFEL_API_BASE", "https://api.duffel.com").rstrip("/")
DUFFEL_VERSION = os.getenv("DUFFEL_API_VERSION", "v2").strip() or "v2"
DUFFEL_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Duffel-Version": DUFFEL_VERSION,
}


class DuffelClient:
    def __init__(self):
        self._token = os.getenv("DUFFEL_API_TOKEN", "").strip()
        self.last_diagnostic = {}

    @property
    def configured(self) -> bool:
        return bool(self._token)

    def _set_diag(self, operation: str, **data) -> None:
        self.last_diagnostic[operation] = data

    def _debug_log(self):
        try:
            from core.logging_config import get_logger

            return get_logger("mcp.duffel")
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
                     headers: dict | None = None, params: dict | None = None,
                     payload: dict | None = None) -> None:
        self._debug_log().debug("Duffel API request", extra={
            "operation": operation,
            "method": method,
            "url": url,
            "headers": self._redact_headers(headers),
            "params": params or {},
            "json": payload or {},
        })

    def _log_response(self, operation: str, response=None,
                      error: Exception | None = None) -> None:
        extra = {"operation": operation}
        if response is not None:
            extra["response"] = self._response_object(response)
        if error is not None:
            extra["error"] = {"type": type(error).__name__, "message": str(error)}
        self._debug_log().debug("Duffel API response", extra=extra)

    def _auth_headers(self) -> dict | None:
        if not self.configured:
            self._set_diag("auth", status="not_configured",
                           reason="DUFFEL_API_TOKEN is missing.")
            return None
        self._set_diag("auth", status="ok")
        return {
            **DUFFEL_HEADERS,
            "Authorization": f"Bearer {self._token}",
        }

    def offer_request(self, origin: str, destination: str, date: str,
                      adults: int = 1, direct_only: bool = False,
                      cabin_class: str = "economy",
                      supplier_timeout_ms: int = 12000) -> list[dict]:
        headers = self._auth_headers()
        if not headers:
            self._set_diag("offer_request", status="auth_unavailable",
                           auth=self.last_diagnostic.get("auth", {}))
            return []

        params = {
            "return_offers": "true",
            "supplier_timeout": supplier_timeout_ms,
        }
        url = f"{DUFFEL_BASE}/air/offer_requests?{urlencode(params)}"
        payload = {
            "data": {
                "slices": [
                    {
                        "origin": origin,
                        "destination": destination,
                        "departure_date": date,
                    }
                ],
                "passengers": [{"type": "adult"} for _ in range(max(1, adults))],
                "cabin_class": cabin_class,
                "max_connections": 0 if direct_only else 1,
            }
        }

        self._log_request("offer_request", "POST", url, headers=headers,
                          params=params, payload=payload)
        try:
            response = post(url, json=payload, headers=headers, timeout=25)
            self._log_response("offer_request", response=response)
            if response.ok:
                body = response.json() or {}
                data = body.get("data", {}) or {}
                offers = data.get("offers", []) or []
                self._set_diag(
                    "offer_request",
                    status="ok",
                    count=len(offers),
                    request={
                        "origin": origin,
                        "destination": destination,
                        "date": date,
                        "adults": adults,
                        "direct_only": direct_only,
                        "cabin_class": cabin_class,
                    },
                )
                return offers
            self._set_diag(
                "offer_request",
                status="http_error",
                http_status=response.status_code,
                body=response.text[:1000],
                request={
                    "origin": origin,
                    "destination": destination,
                    "date": date,
                    "adults": adults,
                    "direct_only": direct_only,
                    "cabin_class": cabin_class,
                },
            )
            log.warning("Duffel offer request failed: %s %s",
                        response.status_code, response.text[:200])
        except Exception as exc:
            self._log_response("offer_request", error=exc)
            self._set_diag(
                "offer_request",
                status="exception",
                error=str(exc),
                request={
                    "origin": origin,
                    "destination": destination,
                    "date": date,
                    "adults": adults,
                    "direct_only": direct_only,
                    "cabin_class": cabin_class,
                },
            )
            log.warning("Duffel offer request error: %s", exc)
        return []


duffel = DuffelClient()
