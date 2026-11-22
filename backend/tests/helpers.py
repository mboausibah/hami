"""Test helpers: a local static server reachable as http://<name>.localhost:<port>/ (Chromium resolves
*.localhost to loopback), so captures run without the internet."""
from __future__ import annotations

import functools
import http.server
import socket
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # noqa: ANN002
        pass


class _DualStackServer(http.server.ThreadingHTTPServer):
    address_family = socket.AF_INET6

    def server_bind(self) -> None:
        try:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except (AttributeError, OSError):
            pass
        super().server_bind()


def serve_dir(directory: Path) -> tuple[str, http.server.ThreadingHTTPServer]:
    handler = functools.partial(_Quiet, directory=str(directory))
    try:
        srv = _DualStackServer(("::", 0), handler)
    except OSError:
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://corpus.localhost:{port}", srv
