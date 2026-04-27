"""Minimal HTTP helper used by geo_location (avoids circular import with mcp http_client)."""
import requests

def safe_get(url: str, params: dict = None, timeout: int = 5):
    try:
        return requests.get(url, params=params, timeout=timeout)
    except Exception:
        return None
