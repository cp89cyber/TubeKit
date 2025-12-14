from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from typing import Any, Callable

_CACHE: dict[str, tuple[float, Any]] = {}
_CACHE_TTL_S = 60.0


def _fetch_bytes(url: str, *, timeout_s: float = 15.0) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "TubeKit/0.1 (+https://example.invalid) python-urllib",
            "Accept": "*/*",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return resp.read()


def _cached(key: str, fetcher: Callable[[], Any]) -> Any:
    now = time.time()
    cached = _CACHE.get(key)
    if cached and (now - cached[0]) < _CACHE_TTL_S:
        return cached[1]
    value = fetcher()
    _CACHE[key] = (now, value)
    return value


class handler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802 - Vercel handler convention
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802 - Vercel handler convention
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        v = (qs.get("v") or [""])[0].strip()
        url = (qs.get("url") or [""])[0].strip()

        if not url and v:
            url = f"https://www.youtube.com/watch?v={urllib.parse.quote(v)}"
        if not url:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Provide v or url"})
            return

        oembed_url = "https://www.youtube.com/oembed?" + urllib.parse.urlencode(
            {"url": url, "format": "json"}
        )

        try:
            payload = _cached(
                oembed_url,
                lambda: json.loads(_fetch_bytes(oembed_url).decode("utf-8")),
            )
        except Exception as e:  # noqa: BLE001 - return safe error to client
            self._send_json(
                HTTPStatus.BAD_GATEWAY,
                {"error": "Failed to fetch oEmbed", "detail": str(e)},
            )
            return

        self._send_json(HTTPStatus.OK, payload)

