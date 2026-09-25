"""HTTP and SOCKS5 proxies for the proxy journey.

Any host ending in `.test` resolves to 127.0.0.1 here and nowhere else, so a page
that loads from a `.test` name can only have come through this proxy.
"""

from __future__ import annotations

import base64
import socket
import socketserver
import struct
import threading
from urllib.parse import urlsplit


def _recvn(sock, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("peer closed")
        buf += chunk
    return buf


def _read_head(sock) -> bytes:
    head = b""
    while not head.endswith(b"\r\n\r\n"):
        c = sock.recv(1)  # byte at a time so nothing past the head is consumed
        if not c:
            raise ConnectionError("peer closed")
        head += c
    return head


def _pipe(a, b) -> None:
    def one(src, dst):
        try:
            while True:
                data = src.recv(65536)
                if not data:
                    break
                dst.sendall(data)
        except OSError:
            pass
        finally:
            for s in (src, dst):
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    t = threading.Thread(target=one, args=(b, a), daemon=True)
    t.start()
    one(a, b)
    t.join()


class Proxy:
    def __init__(self, kind: str, auth=None) -> None:
        assert kind in ("http", "socks5")
        self.kind, self.auth = kind, auth
        self.hosts: list = []
        proxy = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                try:
                    (proxy._http if proxy.kind == "http" else proxy._socks)(self.request)
                except (OSError, ConnectionError, ValueError):
                    pass

        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def playwright(self) -> dict:
        d = {"server": f"{'http' if self.kind == 'http' else 'socks5'}://127.0.0.1:{self.port}"}
        if self.auth:
            d["username"], d["password"] = self.auth
        return d

    def _resolve(self, host: str) -> str:
        self.hosts.append(host)
        return "127.0.0.1" if host.endswith(".test") else host

    def _http(self, c) -> None:
        want = "Basic " + base64.b64encode(":".join(self.auth).encode()).decode() if self.auth else None
        while True:
            head = _read_head(c)
            lines = head.decode("latin-1").split("\r\n")
            method, target, _ = lines[0].split(" ", 2)
            headers = {l.split(":", 1)[0].lower(): l.split(":", 1)[1].strip() for l in lines[1:] if ":" in l}
            if want and headers.get("proxy-authorization") != want:
                c.sendall(b'HTTP/1.1 407 Proxy Authentication Required\r\nProxy-Authenticate: Basic realm="e2e"\r\n'
                          b"Content-Length: 0\r\n\r\n")
                continue
            break
        if method == "CONNECT":
            host, port = target.rsplit(":", 1)
            up = socket.create_connection((self._resolve(host), int(port)))
            c.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
        else:
            # ponytail: later requests on this keep-alive connection go to the same
            # upstream; fine while every proxied page lives on one .test origin.
            u = urlsplit(target)
            up = socket.create_connection((self._resolve(u.hostname), u.port or 80))
            up.sendall(head)
        _pipe(c, up)

    def _socks(self, c) -> None:
        ver, n = _recvn(c, 2)
        methods = _recvn(c, n)
        want = 2 if self.auth else 0
        if ver != 5 or want not in methods:
            c.sendall(b"\x05\xff")
            return
        c.sendall(bytes([5, want]))
        if self.auth:
            _, ulen = _recvn(c, 2)
            user = _recvn(c, ulen).decode()
            password = _recvn(c, _recvn(c, 1)[0]).decode()
            ok = (user, password) == tuple(self.auth)
            c.sendall(b"\x01" + (b"\x00" if ok else b"\x01"))
            if not ok:
                return
        _, cmd, _, atyp = _recvn(c, 4)
        if atyp == 1:
            host = socket.inet_ntoa(_recvn(c, 4))
        elif atyp == 3:
            host = _recvn(c, _recvn(c, 1)[0]).decode()
        else:
            host = socket.inet_ntop(socket.AF_INET6, _recvn(c, 16))
        port = struct.unpack(">H", _recvn(c, 2))[0]
        up = socket.create_connection((self._resolve(host), port))
        c.sendall(b"\x05\x00\x00\x01" + socket.inet_aton("127.0.0.1") + struct.pack(">H", port))
        _pipe(c, up)
