"""Kalshi read client and series discovery.

Reads on this host are public; no credentials are used anywhere in this package.
"""

from __future__ import annotations

import time
from collections.abc import Sequence

import requests

API_BASE = "https://api.elections.kalshi.com/trade-api/v2"
USER_AGENT = "kiix-ingest/0.2 (+political sleeves)"

# Retry only what can plausibly succeed on a second attempt. 4xx other than
# these is a bad request and will never succeed, so it must not burn backoff.
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

# Hard ceiling on cursor pagination. A server that returns a stable cursor
# alongside a non-empty batch would otherwise spin forever inside a systemd
# timer with nothing to stop it.
MAX_PAGES = 250


class KalshiError(RuntimeError):
    """Any unrecoverable failure talking to the API."""


class Client:
    """Thin Kalshi read client with retries and cursor pagination.

    One Session for connection reuse: a run makes a couple of dozen requests,
    and many more with --orderbook, so pooling avoids redoing the TLS handshake
    every call against a rate-limited API.
    """

    def __init__(
        self,
        timeout: float = 30.0,
        retries: int = 4,
        base_url: str = API_BASE,
        max_backoff: float = 30.0,
    ) -> None:
        self.timeout = timeout
        self.retries = retries
        self.base_url = base_url.rstrip("/")
        self.max_backoff = max_backoff
        self.session = requests.Session()
        self.session.headers.update(
            {"Accept": "application/json", "User-Agent": USER_AGENT}
        )

    def _backoff(self, attempt: int, retry_after: str | None) -> float:
        """Honour the server's Retry-After when it sends one; else exponential."""
        if retry_after:
            try:
                return min(float(retry_after), self.max_backoff)
            except ValueError:
                pass  # Retry-After may be an HTTP date; fall through.
        return min(1.5 * (2**attempt), self.max_backoff)

    def get(self, path: str, **params) -> dict:
        """GET a JSON endpoint. Query parameters are passed as keyword arguments."""
        url = f"{self.base_url}{path}"
        last_error: Exception | None = None

        for attempt in range(self.retries):
            delay: float | None = None
            try:
                resp = self.session.get(
                    url, params=params or None, timeout=self.timeout
                )
            except requests.RequestException as exc:
                last_error = exc
                delay = self._backoff(attempt, None)
            else:
                if resp.status_code in RETRYABLE_STATUS:
                    last_error = KalshiError(f"HTTP {resp.status_code} from {path}")
                    delay = self._backoff(attempt, resp.headers.get("Retry-After"))
                elif resp.status_code >= 400:
                    # Not retryable: a bad ticker or malformed query.
                    raise KalshiError(
                        f"HTTP {resp.status_code} from {path}: {resp.text[:200]}"
                    )
                else:
                    try:
                        return resp.json()
                    except ValueError as exc:
                        last_error = exc
                        delay = self._backoff(attempt, None)

            if attempt < self.retries - 1 and delay:
                time.sleep(delay)

        raise KalshiError(
            f"GET {path} failed after {self.retries} attempts: {last_error}"
        ) from last_error

    def paginate(self, path: str, key: str, max_pages: int = MAX_PAGES, **params) -> list[dict]:
        """Follow Kalshi's opaque cursor until it runs out.

        `key` is the payload wrapper, which differs per endpoint: /series returns
        {"series": [...]}, /markets returns {"markets": [...]}.

        Note this endpoint family keeps returning a cursor on the final page, so
        the empty-batch check is what actually terminates the loop — at the cost
        of one empty request per paginated endpoint per run.
        """
        rows: list[dict] = []
        cursor: str | None = None

        for _ in range(max_pages):
            page = self.get(path, **params, **({"cursor": cursor} if cursor else {}))
            batch = page.get(key) or []
            rows.extend(batch)
            cursor = page.get("cursor")
            if not cursor or not batch:
                return rows

        raise KalshiError(
            f"GET {path} exceeded {max_pages} pages ({len(rows)} rows); "
            "suspect a stuck cursor"
        )


def discover_series(client: Client, categories: Sequence[str]) -> dict[str, list[str]]:
    """Enumerate series across several categories, unioned.

    Returns {series_ticker: [categories it appeared under]}.

    Several categories, not one, because the board does not agree with itself:
    the approval series report category "Politics" while the seat and
    chamber-control series are only reachable under "Elections". Querying one
    category would silently return nothing for two of the three sleeves.
    Unioning also means a series recategorized by the exchange keeps ingesting.

    Discovery on every run is what turns a rename into a visible diff plus an
    alert instead of silently missing data.
    """
    found: dict[str, list[str]] = {}
    for category in categories:
        rows = client.paginate("/series", "series", category=category)
        for row in rows:
            ticker = row.get("ticker")
            if ticker:
                found.setdefault(ticker, []).append(category)
    return dict(sorted(found.items()))


def series_detail(client: Client, series_ticker: str) -> dict:
    return client.get(f"/series/{series_ticker}").get("series", {})


def open_markets(client: Client, series_ticker: str) -> list[dict]:
    return client.paginate(
        "/markets", "markets", series_ticker=series_ticker, status="open"
    )


def orderbook(client: Client, ticker: str) -> dict:
    return client.get(f"/markets/{ticker}/orderbook").get("orderbook", {})
