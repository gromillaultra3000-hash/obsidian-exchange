"""Loopback-only HTTPS harness for the test-only Android RP contract.

The harness is deliberately not a production service. It may be constructed
for an explicit local rehearsal, but it never starts itself, accepts a
non-loopback bind address, reads environment variables, or enables credential
authentication. The route behavior comes from the pure RP contract module.
"""

from __future__ import annotations

import json
import ssl
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from e5_android_webauthn_rp_contract import handle_test_only_request


MAX_BODY_BYTES = 32_768
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
LOCAL_RP_IDS = frozenset({"127.0.0.1", "localhost"})


class TestServerConfigError(ValueError):
    """Raised when the local-only harness configuration is unsafe."""


@dataclass(frozen=True)
class TestOnlyRpConfig:
    bind_host: str
    bind_port: int
    rp_id: str
    origin: str
    tls_certificate_file: str
    tls_private_key_file: str

    def validate(self) -> "TestOnlyRpConfig":
        if self.bind_host not in LOOPBACK_HOSTS:
            raise TestServerConfigError("test harness may bind only to loopback")
        if isinstance(self.bind_port, bool) or not isinstance(self.bind_port, int):
            raise TestServerConfigError("bind port must be an integer")
        if not 1024 <= self.bind_port <= 65_535:
            raise TestServerConfigError("test harness port must be 1024..65535")
        if self.rp_id not in LOCAL_RP_IDS:
            raise TestServerConfigError("local harness accepts only loopback RP IDs")
        if not isinstance(self.origin, str):
            raise TestServerConfigError("origin is required")
        parsed = urlsplit(self.origin)
        if (
            parsed.scheme != "https"
            or parsed.hostname != self.rp_id
            or parsed.port is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise TestServerConfigError("origin must be exact HTTPS origin for RP ID")
        for field, value in [
            ("tls_certificate_file", self.tls_certificate_file),
            ("tls_private_key_file", self.tls_private_key_file),
        ]:
            if not isinstance(value, str) or not value.startswith("/") or "\x00" in value:
                raise TestServerConfigError(f"{field} must be an absolute local path")
        return self


class TestOnlyRpApplication:
    """Explicitly constructed in-memory adapter; it does not listen."""

    def __init__(
        self,
        *,
        sessions: Mapping[str, Mapping[str, object]],
        expected_context: Mapping[str, object],
        now_epoch_ms: Callable[[], int],
    ) -> None:
        self._sessions = sessions
        self._expected_context = expected_context
        self._now_epoch_ms = now_epoch_ms

    def dispatch(
        self, *, method: str, path: str, body: bytes | bytearray | None
    ) -> tuple[int, dict[str, object]]:
        return handle_test_only_request(
            method=method,
            path=path,
            body=body,
            sessions=self._sessions,
            expected_context=self._expected_context,
            now_epoch_ms=self._now_epoch_ms(),
        )


def build_loopback_https_server(
    *, config: TestOnlyRpConfig, application: TestOnlyRpApplication
) -> ThreadingHTTPServer:
    """Build, but do not start, a loopback-only TLS server."""
    config.validate()

    class Handler(BaseHTTPRequestHandler):
        server_version = "E5TestOnlyRP/0"
        sys_version = ""

        def _respond(self, status: int, payload: Mapping[str, object]) -> None:
            encoded = json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(encoded)

        def _body(self) -> bytes | None:
            raw_length = self.headers.get("Content-Length")
            if raw_length is None:
                return None
            try:
                length = int(raw_length)
            except ValueError:
                return b"!invalid-content-length!"
            if length < 0 or length > MAX_BODY_BYTES:
                return b"!oversized-body!"
            return self.rfile.read(length)

        def _handle(self) -> None:
            body = self._body()
            status, payload = application.dispatch(
                method=self.command,
                path=self.path,
                body=body,
            )
            self._respond(status, payload)

        do_GET = _handle
        do_POST = _handle
        do_PUT = _handle
        do_DELETE = _handle
        do_PATCH = _handle

        def log_message(self, _format: str, *_args: object) -> None:
            return None

    server = ThreadingHTTPServer((config.bind_host, config.bind_port), Handler)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(
        certfile=config.tls_certificate_file,
        keyfile=config.tls_private_key_file,
    )
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    return server
