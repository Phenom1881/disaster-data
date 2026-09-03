"""Dependency-free JSON HTTP API."""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__
from .service import WeatherService


class WeatherApiHandler(BaseHTTPRequestHandler):
    service = WeatherService()

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, path: Path, content_type: str) -> None:
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src https://fonts.gstatic.com; script-src 'self' 'unsafe-inline'; "
            "connect-src 'self' http://127.0.0.1:* http://localhost:*",
        )
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _one(query: dict[str, list[str]], name: str, required: bool = False, default=None):
        value = query.get(name, [default])[0]
        if required and not value:
            raise ValueError(f"Missing required query parameter: {name}")
        return value

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler interface
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            if parsed.path in {"/weather", "/weather/", "/weather/index.html"}:
                page = Path(__file__).resolve().parent.parent / "weather" / "index.html"
                self._send_static(page, "text/html; charset=utf-8")
                return
            if parsed.path == "/nav.js":
                script = Path(__file__).resolve().parent.parent / "weather" / "nav.js"
                self._send_static(script, "text/javascript; charset=utf-8")
                return
            if parsed.path == "/health":
                payload = {"status": "ok", "service": "disasterdata-weather", "version": __version__}
            elif parsed.path == "/v1/places/search":
                payload = self.service.search_places(
                    self._one(query, "q", required=True),
                    int(self._one(query, "limit", default="10")),
                )
            elif parsed.path == "/v1/places/detail":
                payload = self.service.get_place(self._one(query, "place_id", required=True))
            elif parsed.path == "/v1/weather/events":
                types = query.get("event_type")
                payload = self.service.events(
                    self._one(query, "place_id", required=True),
                    self._one(query, "from", required=True),
                    self._one(query, "to", required=True),
                    set(types) if types else None,
                    int(self._one(query, "limit", default="1000")),
                    int(self._one(query, "offset", default="0")),
                )
            elif parsed.path == "/v1/weather/climatology":
                payload = self.service.climatology(
                    self._one(query, "place_id", required=True),
                    self._one(query, "from", required=True),
                    self._one(query, "to", required=True),
                    float(self._one(query, "radius_km", default="40")),
                )
            elif parsed.path == "/v1/weather/profile":
                payload = self.service.profile(
                    self._one(query, "place_id", required=True),
                    self._one(query, "from", required=True),
                    self._one(query, "to", required=True),
                    float(self._one(query, "radius_km", default="40")),
                )
            else:
                self._send(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            self._send(HTTPStatus.OK, payload)
        except (KeyError, ValueError) as exc:
            self._send(HTTPStatus.BAD_REQUEST, {"error": "bad_request", "message": str(exc)})
        except Exception as exc:  # keep upstream failures legible to API clients
            self._send(
                HTTPStatus.BAD_GATEWAY,
                {"error": "upstream_data_error", "message": str(exc)},
            )

    def log_message(self, format: str, *args) -> None:
        return


def serve(host: str = "127.0.0.1", port: int = 8080) -> None:
    server = ThreadingHTTPServer((host, port), WeatherApiHandler)
    print(f"DisasterData Weather API listening on http://{host}:{port}")
    server.serve_forever()
