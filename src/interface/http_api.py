from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from src.interface.api_service import APIServiceError, DemoAPIService


def create_handler(
    service: DemoAPIService,
) -> type[BaseHTTPRequestHandler]:
    class DemoAPIHandler(BaseHTTPRequestHandler):
        server_version = "VehicleMemoryDemoHTTP/0.1"

        def do_OPTIONS(self) -> None:  # noqa: N802
            self._send_json(HTTPStatus.NO_CONTENT, {})

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                self._dispatch(lambda: service.health())
                return
            if parsed.path == "/preferences":
                params = parse_qs(parsed.query)
                self._dispatch(
                    lambda: service.preferences(
                        session_id=_first_value(params.get("session_id"))
                    )
                )
                return
            self._send_error_payload(HTTPStatus.NOT_FOUND, "route not found")

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                body = self._read_json_body()
            except APIServiceError as exc:
                self._send_error_payload(HTTPStatus(exc.status_code), str(exc))
                return
            if parsed.path == "/turn":
                self._dispatch(
                    lambda: service.turn(
                        text=body.get("text", ""),
                        session_id=body.get("session_id"),
                    )
                )
                return
            if parsed.path == "/clarification":
                self._dispatch(
                    lambda: service.clarification(
                        answer=body.get("answer", ""),
                        pending_id=body.get("pending_id", ""),
                        session_id=body.get("session_id"),
                    )
                )
                return
            if parsed.path == "/summarize":
                self._dispatch(
                    lambda: service.summarize(session_id=body.get("session_id"))
                )
                return
            if parsed.path == "/reset":
                self._dispatch(lambda: service.reset(session_id=body.get("session_id")))
                return
            if parsed.path == "/preferences/update":
                self._dispatch(
                    lambda: service.update_preference(
                        record_id=int(body.get("id", 0)),
                        preference=body.get("preference"),
                        value=body.get("value"),
                        condition=body.get("condition"),
                        status=body.get("status"),
                        source=body.get("source"),
                        evidence=body.get("evidence"),
                        session_id=body.get("session_id"),
                    )
                )
                return
            if parsed.path == "/preferences/delete":
                self._dispatch(
                    lambda: service.delete_preference(
                        record_id=int(body.get("id", 0)),
                        session_id=body.get("session_id"),
                    )
                )
                return
            self._send_error_payload(HTTPStatus.NOT_FOUND, "route not found")

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

        def _dispatch(self, fn: Callable[[], dict[str, Any]]) -> None:
            try:
                payload = fn()
            except APIServiceError as exc:
                self._send_error_payload(
                    HTTPStatus(exc.status_code),
                    str(exc),
                )
                return
            except Exception as exc:  # pragma: no cover - live server path
                self._send_error_payload(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    f"internal server error: {exc}",
                )
                return
            self._send_json(HTTPStatus.OK, payload)

        def _read_json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length <= 0:
                return {}
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise APIServiceError(f"invalid JSON body: {exc}") from exc
            if not isinstance(payload, dict):
                raise APIServiceError("JSON body must be an object")
            return payload

        def _send_error_payload(self, status: HTTPStatus, message: str) -> None:
            self._send_json(status, {"error": message})

        def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status.value)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()
            if status != HTTPStatus.NO_CONTENT:
                self.wfile.write(body)

    return DemoAPIHandler


def run_server(
    *,
    host: str,
    port: int,
    service: DemoAPIService | None = None,
) -> None:
    service = service or DemoAPIService()
    handler = create_handler(service)
    server = ThreadingHTTPServer((host, port), handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover - live server path
        pass
    finally:
        server.server_close()


def _first_value(values: list[str] | None) -> str | None:
    if not values:
        return None
    return values[0]
