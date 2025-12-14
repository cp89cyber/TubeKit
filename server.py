#!/usr/bin/env python3
from __future__ import annotations

import argparse
import functools
import json
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

WEB_ROOT = Path(__file__).resolve().parent / "web"

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


def _cached_json(key: str, fetcher) -> Any:
    now = time.time()
    cached = _CACHE.get(key)
    if cached and (now - cached[0]) < _CACHE_TTL_S:
        return cached[1]
    value = fetcher()
    _CACHE[key] = (now, value)
    return value


def _parse_youtube_feed(xml_bytes: bytes) -> dict[str, Any]:
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "yt": "http://www.youtube.com/xml/schemas/2015",
        "media": "http://search.yahoo.com/mrss/",
    }
    root = ET.fromstring(xml_bytes)

    out: dict[str, Any] = {
        "title": root.findtext("atom:title", default="", namespaces=ns),
        "updated": root.findtext("atom:updated", default="", namespaces=ns),
        "author": root.findtext("atom:author/atom:name", default="", namespaces=ns),
        "items": [],
    }

    for entry in root.findall("atom:entry", ns):
        video_id = entry.findtext("yt:videoId", default="", namespaces=ns)
        link_el = entry.find("atom:link[@rel='alternate']", ns)
        thumb_el = entry.find("media:group/media:thumbnail", ns)
        desc = entry.findtext(
            "media:group/media:description", default="", namespaces=ns
        ).strip()

        out["items"].append(
            {
                "videoId": video_id,
                "title": entry.findtext("atom:title", default="", namespaces=ns),
                "published": entry.findtext(
                    "atom:published", default="", namespaces=ns
                ),
                "updated": entry.findtext("atom:updated", default="", namespaces=ns),
                "link": (link_el.attrib.get("href") if link_el is not None else ""),
                "thumbnail": (thumb_el.attrib.get("url") if thumb_el is not None else ""),
                "description": desc,
            }
        )

    return out


class TubeKitHandler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/feed":
            self._handle_api_feed(parsed.query)
            return
        if parsed.path == "/api/oembed":
            self._handle_api_oembed(parsed.query)
            return
        super().do_GET()

    def _send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _handle_api_feed(self, query: str) -> None:
        qs = urllib.parse.parse_qs(query)
        channel_id = (qs.get("channel_id") or [""])[0].strip()
        playlist_id = (qs.get("playlist_id") or [""])[0].strip()
        user = (qs.get("user") or [""])[0].strip()

        provided = [(k, v) for k, v in [("channel_id", channel_id), ("playlist_id", playlist_id), ("user", user)] if v]
        if len(provided) != 1:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": "Provide exactly one of channel_id, playlist_id, or user",
                },
            )
            return

        kind, value = provided[0]
        url = f"https://www.youtube.com/feeds/videos.xml?{urllib.parse.urlencode({kind: value})}"

        try:
            data = _cached_json(
                url,
                lambda: _parse_youtube_feed(_fetch_bytes(url)),
            )
        except Exception as e:  # noqa: BLE001 - return safe error to client
            self._send_json(
                HTTPStatus.BAD_GATEWAY,
                {"error": "Failed to fetch/parse feed", "detail": str(e)},
            )
            return

        self._send_json(
            HTTPStatus.OK,
            {
                "kind": kind,
                "value": value,
                "feedUrl": url,
                **data,
            },
        )

    def _handle_api_oembed(self, query: str) -> None:
        qs = urllib.parse.parse_qs(query)
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
            payload = _cached_json(
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="TubeKit: a tiny YouTube web client using embeds + public RSS feeds (no YouTube Data API)."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if not WEB_ROOT.is_dir():
        raise SystemExit(f"Missing web root: {WEB_ROOT}")

    handler = functools.partial(TubeKitHandler, directory=str(WEB_ROOT))
    httpd = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"TubeKit running on http://{args.host}:{args.port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

