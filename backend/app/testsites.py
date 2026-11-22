"""Synthetic test-site server (automated tests and reproducibility only, never shown as real results).

Serves testsites/sites/<name>/ by Host header: http://site-a.localhost:8100/, site-b, site-c, listing.
Chromium resolves *.localhost to the loopback address, so no hosts-file changes are needed."""
from __future__ import annotations

import http.server
import socket
import threading
from pathlib import Path

from app.config import REPO_DIR, settings

SITES_DIR = REPO_DIR / "testsites" / "sites"
_started: dict[int, http.server.ThreadingHTTPServer] = {}


class _Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        super().__init__(*args, directory=str(SITES_DIR), **kwargs)

    def translate_path(self, path: str) -> str:
        host = (self.headers.get("Host") or "").split(":")[0].lower()
        site = host[: -len(".localhost")] if host.endswith(".localhost") else ""
        root = SITES_DIR / site if site and (SITES_DIR / site).is_dir() else SITES_DIR
        self.directory = str(root)  # handler instances are per request
        return super().translate_path(path)

    def list_directory(self, path):  # noqa: ANN001, ANN201
        if Path(path).resolve() == SITES_DIR.resolve():
            names = sorted(p.name for p in SITES_DIR.iterdir() if p.is_dir())
            port = self.server.server_address[1]
            body = "<h1>Hami synthetic test sites</h1><ul>" + "".join(
                f'<li><a href="http://{n}.localhost:{port}/">{n}.localhost</a></li>' for n in names) + "</ul>"
            data = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return None
        self.send_error(404)
        return None

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *args):  # noqa: ANN002
        pass


class _DualStack(http.server.ThreadingHTTPServer):
    address_family = socket.AF_INET6
    daemon_threads = True

    def server_bind(self) -> None:
        try:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except (AttributeError, OSError):
            pass
        super().server_bind()


def make_server(port: int) -> http.server.ThreadingHTTPServer:
    try:
        return _DualStack(("::", port), _Handler)
    except OSError:
        return http.server.ThreadingHTTPServer(("0.0.0.0", port), _Handler)


def start_in_thread(port: int | None = None) -> http.server.ThreadingHTTPServer:
    port = port or settings.testsite_port
    if port in _started:
        return _started[port]
    srv = make_server(port)
    threading.Thread(target=srv.serve_forever, daemon=True, name="hami-testsites").start()
    _started[port] = srv
    return srv


def serve_forever(port: int | None = None) -> None:
    port = port or settings.testsite_port
    srv = make_server(port)
    print(f"Hami synthetic test sites on http://site-a.localhost:{port}/ (also site-b, site-c, listing)")
    srv.serve_forever()

