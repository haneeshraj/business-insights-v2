"""The review page's server. It serves the page and the run's pictures to your browser, and
saves each check the page sends.

Only this machine can reach it, since it listens on 127.0.0.1, and only the page it served can
save checks: every save carries a random token that's in the page, and requests that name
another host are refused, so no website you visit can save checks or read the page. The page
may run only its own scripts, and a picture opened on its own (an SVG can hold scripts) runs
sandboxed, with nothing it can reach.
"""

import json
import secrets
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Final
from urllib.parse import unquote, urlsplit

from pydantic import ValidationError

from bi2.cli.review.session import BadAnswer, CheckRequest, NoSuchAnswer, ReviewSession

_PICTURES: Final = {
    ".avif": "image/avif",
    ".gif": "image/gif",
    ".ico": "image/x-icon",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}
_PICTURE_POLICY: Final = (
    "sandbox; default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src data:"
)
_MAX_CHECK_BYTES: Final = 16_384
_BAD_CHECK: Final = (
    "a check needs a site, a field, right or wrong, and a note of at most 1000 characters"
)


def _page_policy(nonce: str) -> str:
    return "; ".join(
        (
            "default-src 'none'",
            f"script-src 'nonce-{nonce}'",
            "style-src 'unsafe-inline'",
            "img-src 'self' https: http: data:",  # logo candidates load from their own sites
            "connect-src 'self'",
            "base-uri 'none'",
            "form-action 'none'",
            "frame-ancestors 'none'",
        )
    )


class ReviewServer(ThreadingHTTPServer):
    """Serves one review session until it's stopped."""

    daemon_threads = True
    # On Windows, reusing an address would let another program listen on the same port.
    allow_reuse_address = sys.platform != "win32"

    def __init__(self, session: ReviewSession, port: int = 0) -> None:
        super().__init__(("127.0.0.1", port), _Handler)
        self.session = session
        self.token = secrets.token_urlsafe(24)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_port}/"


class _Handler(BaseHTTPRequestHandler):
    server: ReviewServer

    def log_message(self, format: str, *args: object) -> None:
        """Every request isn't worth a line in the terminal."""

    def _send(
        self, status: HTTPStatus, body: bytes, content_type: str, policy: str | None = None
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        if policy is not None:
            self.send_header("Content-Security-Policy", policy)
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: HTTPStatus, data: object) -> None:
        self._send(status, json.dumps(data).encode(), "application/json")

    def _from_this_machine(self) -> bool:
        """Whether the request names this server, not a website's host that points here."""
        port = self.server.server_port
        return self.headers.get("Host", "") in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _picture(self, path: str) -> tuple[bytes, str] | None:
        """A picture in the results folder, like a screenshot or a logo, and its type. Nothing
        else is served."""
        root = self.server.session.results_dir.resolve()
        try:
            file = (root / path.lstrip("/")).resolve()
            kind = _PICTURES.get(file.suffix.lower())
            if kind is None or not file.is_relative_to(root) or not file.is_file():
                return None
            return file.read_bytes(), kind
        except (OSError, ValueError):  # ValueError: a null character in the path
            return None

    def do_GET(self) -> None:
        if not self._from_this_machine():
            self._send(HTTPStatus.FORBIDDEN, b"Forbidden", "text/plain; charset=utf-8")
            return
        path = unquote(urlsplit(self.path).path)
        if path == "/":
            nonce = secrets.token_urlsafe(16)
            page = self.server.session.page(self.server.token, nonce)
            self._send(
                HTTPStatus.OK, page.encode(), "text/html; charset=utf-8", _page_policy(nonce)
            )
            return
        picture = self._picture(path)
        if picture is None:
            self._send(HTTPStatus.NOT_FOUND, b"Not found", "text/plain; charset=utf-8")
            return
        body, kind = picture
        self._send(HTTPStatus.OK, body, kind, _PICTURE_POLICY)

    def do_POST(self) -> None:
        token = self.headers.get("X-Review-Token", "").encode()
        if not self._from_this_machine() or not secrets.compare_digest(
            token, self.server.token.encode()
        ):
            error = "this page can't save checks: reload it from the address bi2 review shows"
            self._send_json(HTTPStatus.FORBIDDEN, {"error": error})
            return
        if urlsplit(self.path).path != "/checks":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            length = 0
        is_json = self.headers.get_content_type() == "application/json"
        if not is_json or not 0 < length <= _MAX_CHECK_BYTES:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": _BAD_CHECK})
            return
        try:
            self.server.session.check(CheckRequest.model_validate_json(self.rfile.read(length)))
        except ValidationError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": _BAD_CHECK})
            return
        except NoSuchAnswer as exc:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
            return
        except BadAnswer as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        except OSError as exc:
            error = f"the checks file couldn't be written: {exc.strerror or exc}"
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": error})
            return
        self._send_json(HTTPStatus.OK, self.server.session.update())
