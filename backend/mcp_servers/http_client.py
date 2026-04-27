"""
Shared HTTP client for all MCP server API calls.
Handles: retries, timeouts, connection errors, rate limits.
"""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def build_session(retries: int = 2, backoff: float = 0.3,
                  timeout: int = 8) -> requests.Session:
    """Build a requests.Session with retry logic and sensible timeouts."""
    session = requests.Session()
    retry   = Retry(
        total=retries,
        backoff_factor=backoff,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://",  adapter)
    session._default_timeout = timeout
    return session


# Module-level shared session (connection-pool reuse)
HTTP = build_session()


def get(url: str, params: dict = None, headers: dict = None,
        timeout: int = 8) -> requests.Response:
    return HTTP.get(url, params=params, headers=headers, timeout=timeout)


def post(url: str, data=None, json=None, headers: dict = None,
         timeout: int = 8) -> requests.Response:
    return HTTP.post(url, data=data, json=json, headers=headers, timeout=timeout)
