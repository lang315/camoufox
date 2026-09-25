"""The site and proxies work before any browser is pointed at them."""

import hashlib
import json
import socket
import struct
import urllib.request

import pytest

from web.proxy import Proxy
from web.server import DOWNLOAD_SHA, Site
from web.stun import MAGIC, Stun


@pytest.fixture(scope="module")
def site():
    s = Site().start()
    yield s
    s.stop()


def get(url, opener=urllib.request):
    with opener.urlopen(url, timeout=10) as r:
        return r.status, r.read()


def test_pages_render_with_both_origins(site):
    status, body = get(site.url("/frames"))
    assert status == 200 and site.url2("/child.html").encode() in body


def test_download_has_known_hash(site):
    assert hashlib.sha256(get(site.url("/download/file.bin"))[1]).hexdigest() == DOWNLOAD_SHA


def test_login_sets_cookie_only_for_right_password(site):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    for pw, loc in (("s3cret", "/account"), ("nope", "/login?err=1")):
        try:
            opener.open(urllib.request.Request(site.url("/login"), data=f"user=alice&pass={pw}".encode()), timeout=10)
        except urllib.error.HTTPError as e:
            assert e.code == 303 and e.headers["Location"] == loc
            assert ("session=ok" in (e.headers.get("Set-Cookie") or "")) == (pw == "s3cret")


def test_request_record_keeps_headers(site):
    urllib.request.urlopen(urllib.request.Request(site.url("/fp"), headers={"User-Agent": "probe"}), timeout=10).read()
    assert ("User-Agent", "probe") in site.seen("/fp")[-1]["headers"]


def test_http_proxy_requires_auth_and_resolves_test_hosts(site):
    p = Proxy("http", auth=("u", "p"))
    try:
        url = f"http://e2e.test:{site.port1}/login"
        bare = urllib.request.build_opener(urllib.request.ProxyHandler({"http": f"http://127.0.0.1:{p.port}"}))
        with pytest.raises(urllib.error.HTTPError) as e:
            bare.open(url, timeout=10)
        assert e.value.code == 407
        authed = urllib.request.build_opener(urllib.request.ProxyHandler({"http": f"http://u:p@127.0.0.1:{p.port}"}))
        assert authed.open(url, timeout=10).status == 200 and "e2e.test" in p.hosts
    finally:
        p.stop()


def test_socks5_proxy_with_auth(site):
    p = Proxy("socks5", auth=("u", "p"))
    try:
        s = socket.create_connection(("127.0.0.1", p.port), timeout=10)
        s.sendall(b"\x05\x01\x02")
        assert s.recv(2) == b"\x05\x02"
        s.sendall(b"\x01\x01u\x01p")
        assert s.recv(2) == b"\x01\x00"
        host = b"e2e.test"
        s.sendall(b"\x05\x01\x00\x03" + bytes([len(host)]) + host + struct.pack(">H", site.port1))
        assert s.recv(10)[1] == 0
        s.sendall(b"GET /login HTTP/1.1\r\nHost: e2e.test\r\nConnection: close\r\n\r\n")
        assert s.recv(12).startswith(b"HTTP/1.")
        s.close()
        assert "e2e.test" in p.hosts
    finally:
        p.stop()


def test_stun_answers_with_xor_mapped_address():
    st = Stun("127.0.0.1")
    try:
        c = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        c.settimeout(5)
        c.sendto(struct.pack(">HHI", 1, 0, MAGIC) + b"t" * 12, ("127.0.0.1", st.port))
        data = c.recv(2048)
        port = struct.unpack(">H", data[26:28])[0] ^ (MAGIC >> 16)
        assert struct.unpack(">H", data[:2])[0] == 0x0101 and port == c.getsockname()[1]
    finally:
        st.stop()


def test_websocket_upgrade_echoes(site):
    s = socket.create_connection(("127.0.0.1", site.port1), timeout=10)
    s.sendall(b"GET /ws HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
              b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n")
    head = b""
    while not head.endswith(b"\r\n\r\n"):
        head += s.recv(1)
    assert b"101" in head and b"s3pPLMBiTxaQ9kYGzzhZRbK+xOo=" in head
    mask = b"\x01\x02\x03\x04"
    s.sendall(b"\x81\x84" + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(b"ping")))
    assert s.recv(6) == b"\x81\x04ping"
    s.close()
