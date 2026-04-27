"""
Shared HTTP client for all MCP server API calls.
NOTE: We do NOT retry 5xx errors — Amadeus sandbox returns 500s that
are not transient. Retrying them just causes a flood of errors.
Only 429 (rate limit) triggers a brief backoff.
"""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Standard session — no 5xx retry (would flood Amadeus sandbox)
def build_session(timeout: int = 8) -> requests.Session:
    session = requests.Session()
    # Only retry on connection errors and 429 rate limits
    retry = Retry(
        total=1,
        backoff_factor=0.5,
        status_forcelist=[429],        # only rate-limit triggers retry
        allowed_methods=["GET", "POST"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://",  adapter)
    return session


HTTP = build_session()


def get(url: str, params: dict = None, headers: dict = None,
        timeout: int = 8) -> requests.Response:
    return HTTP.get(url, params=params, headers=headers, timeout=timeout)


def post(url: str, data=None, json=None, headers: dict = None,
         timeout: int = 8) -> requests.Response:
    return HTTP.post(url, data=data, json=json, headers=headers, timeout=timeout)
