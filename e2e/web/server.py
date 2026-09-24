"""The local site every journey runs against: two origins, realistic pages, and
a record of every request as the server received it."""

from __future__ import annotations

import hashlib
import io
import json
import math
import struct
import threading
import wave
from email.parser import BytesParser
from email.policy import default as email_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import ws

PAGES = Path(__file__).with_name("pages")
DOWNLOAD = bytes(range(256)) * 4096  # 1 MiB of known content
DOWNLOAD_SHA = hashlib.sha256(DOWNLOAD).hexdigest()
USER, PASSWORD = "alice", "s3cret"


def _tone() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / 8000))) for i in range(4000)))
    return buf.getvalue()


def _multipart(ctype: str, body: bytes):
    msg = BytesParser(policy=email_policy).parsebytes(b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + body)
    return [
        {"name": part.get_filename(), "sha256": hashlib.sha256(part.get_payload(decode=True)).hexdigest()}
        for part in msg.iter_parts()
        if part.get_filename()
    ]


class Site:
    def __init__(self) -> None:
        self.requests: list = []
        self.lock = threading.Lock()
        self.servers = [ThreadingHTTPServer(("127.0.0.1", 0), _handler(self)) for _ in range(2)]
        for s in self.servers:
            s.daemon_threads = True
        self.port1, self.port2 = (s.server_address[1] for s in self.servers)
        self.stun_port = 0
        self.markers = {"windows": [], "macos": [], "linux": []}  # set by the suite (oracle A)

    def start(self) -> "Site":
        for s in self.servers:
            threading.Thread(target=s.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        for s in self.servers:
            s.shutdown()
            s.server_close()

    def url(self, path: str = "/") -> str:
        return f"http://127.0.0.1:{self.port1}{path}"

    def url2(self, path: str = "/") -> str:
        return f"http://localhost:{self.port2}{path}"

    def record(self, entry: dict) -> None:
        with self.lock:
            self.requests.append(entry)

    def seen(self, path: str) -> list:
        with self.lock:
            return [r for r in self.requests if urlsplit(r["path"]).path == path]

    def render(self, name: str) -> bytes:
        text = (PAGES / name).read_text(encoding="utf-8")
        for key, value in {"{{O1}}": self.url("").rstrip("/"), "{{O2}}": self.url2("").rstrip("/"),
                           "{{STUN}}": str(self.stun_port)}.items():
            text = text.replace(key, value)
        return text.encode()


def _handler(site: Site):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def _path(self) -> str:
            # A request relayed by the HTTP proxy arrives in absolute form.
            p = self.path
            if p.startswith("http://"):
                parts = p.split("/", 3)
                p = "/" + (parts[3] if len(parts) > 3 else "")
            return p

        def _send(self, code, body=b"", ctype="text/html; charset=utf-8", headers=()):
            if isinstance(body, str):
                body = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in headers:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _record(self, body=b""):
            site.record({
                "method": self.command, "path": self._path(), "host": self.headers.get("Host"),
                "headers": list(self.headers.items()), "ip": self.client_address[0],
                "body_sha": hashlib.sha256(body).hexdigest(), "body": body[:65536],
            })

        def _cookies(self) -> dict:
            out = {}
            for part in (self.headers.get("Cookie") or "").split(";"):
                if "=" in part:
                    k, v = part.strip().split("=", 1)
                    out[k] = v
            return out

        def do_GET(self):
            self._record()
            route = urlsplit(self._path()).path
            if route == "/ws" and ws.is_upgrade(self.headers):
                return ws.serve_echo(self)
            if route == "/account":
                if self._cookies().get("session") == "ok":
                    return self._send(200, site.render("account.html"))
                return self._send(303, headers=[("Location", "/login")])
            if route == "/download/file.bin":
                return self._send(200, DOWNLOAD, "application/octet-stream",
                                  [("Content-Disposition", 'attachment; filename="file.bin"')])
            if route == "/tone.wav":
                return self._send(200, _tone(), "audio/wav")
            if route == "/fp-markers.json":
                return self._send(200, json.dumps(site.markers), "application/json")
            if route == "/sw-probe":
                return self._send(200, "from-network", "text/plain")
            if route.startswith("/shop"):
                route = "/shop"  # the SPA serves every /shop/* route
            name = "index.html" if route == "/" else route.lstrip("/")
            if not name.endswith((".html", ".js")):
                name += ".html"
            if (PAGES / name).is_file():
                ctype = "text/javascript" if name.endswith(".js") else "text/html; charset=utf-8"
                return self._send(200, site.render(name), ctype)
            self._send(404, "not found", "text/plain")

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            self._record(body)
            route = urlsplit(self._path()).path
            if route == "/login":
                form = {k: v[0] for k, v in parse_qs(body.decode()).items()}
                if form.get("user") == USER and form.get("pass") == PASSWORD:
                    return self._send(303, headers=[("Location", "/account"),
                                                    ("Set-Cookie", "session=ok; Path=/; SameSite=Lax")])
                return self._send(303, headers=[("Location", "/login?err=1")])
            if route == "/upload":
                return self._send(200, json.dumps(_multipart(self.headers["Content-Type"], body)), "application/json")
            self._send(404, "not found", "text/plain")

    return Handler
