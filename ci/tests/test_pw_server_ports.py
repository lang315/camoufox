"""ci/pw_camoufox_plugin.py: upstream's test servers bind on kernel-chosen ports (#390).

playwright-python's tests/server.py draws each server's port in `Server.__init__`
(bind 0, read, close) and listens in `start()`. The stand-in below has that shape
with real sockets, because the CI environment has no twisted. The control tests
show the stand-in fails the way run 41633372099 did without the fix.
"""

import socket
import types
from contextlib import closing

import pytest

from ci.pw_camoufox_plugin import install_kernel_chosen_ports


class CannotListenError(OSError):
    pass


class Listener:
    def __init__(self, sock):
        self.sock = sock

    def getHost(self):  # noqa: N802
        return types.SimpleNamespace(port=self.sock.getsockname()[1])


class Reactor:
    def __init__(self):
        self.listeners = []

    def _listen(self, port, interface):
        family = socket.AF_INET6 if ":" in interface else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((interface, port))
        except OSError as exc:
            sock.close()
            raise CannotListenError(f"Couldn't listen on {interface}:{port}: {exc}") from exc
        sock.listen()
        self.listeners.append(sock)
        return Listener(sock)

    def listenTCP(self, port, factory, backlog=50, interface=""):  # noqa: N802
        return self._listen(port, interface)

    def listenSSL(self, port, factory, contextFactory, backlog=50, interface=""):  # noqa: N802
        return self._listen(port, interface)


def make_upstream_module():
    """tests/server.py at v1.62.0, with the twisted parts reduced to sockets."""
    module = types.ModuleType("tests.server")
    module.reactor = Reactor()

    def find_free_port():
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
            s.bind(("", 0))
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            return s.getsockname()[1]

    module.find_free_port = find_free_port

    class Server:
        protocol = "http"

        def __init__(self):
            self.PORT = module.find_free_port()
            self.EMPTY_PAGE = f"{self.protocol}://localhost:{self.PORT}/empty.html"
            self.PREFIX = f"{self.protocol}://localhost:{self.PORT}"
            self.CROSS_PROCESS_PREFIX = f"{self.protocol}://127.0.0.1:{self.PORT}"

        def start(self):
            self.listen(None)

    class HTTPServer(Server):
        def listen(self, factory):
            module.reactor.listenTCP(self.PORT, factory, interface="127.0.0.1")
            try:
                module.reactor.listenTCP(self.PORT, factory, interface="::1")
            except Exception:
                pass

    class HTTPSServer(Server):
        protocol = "https"

        def listen(self, factory):
            module.reactor.listenSSL(self.PORT, factory, None, interface="127.0.0.1")
            try:
                module.reactor.listenSSL(self.PORT, factory, None, interface="::1")
            except Exception:
                pass

    module.Server, module.HTTPServer, module.HTTPSServer = Server, HTTPServer, HTTPSServer
    return module


def start_both(module):
    http, https = module.HTTPServer(), module.HTTPSServer()
    http.start()
    https.start()
    return http, https


def hold(port):
    sock = socket.socket()
    sock.bind(("127.0.0.1", port))
    sock.listen()
    return sock


@pytest.fixture
def module():
    mod = make_upstream_module()
    yield mod
    for sock in mod.reactor.listeners:
        sock.close()


def test_control_the_same_drawn_port_fails_to_listen_without_the_fix(module, monkeypatch):
    monkeypatch.setattr(module, "find_free_port", lambda: 41247)
    with pytest.raises(CannotListenError, match="127.0.0.1:41247"):
        start_both(module)


def test_control_a_port_taken_after_the_draw_fails_to_listen_without_the_fix(module):
    http = module.HTTPServer()
    taken = hold(http.PORT)
    try:
        with pytest.raises(CannotListenError):
            http.start()
    finally:
        taken.close()


def test_two_servers_drawn_the_same_port_get_different_ones(module, monkeypatch):
    monkeypatch.setattr(module, "find_free_port", lambda: 41247)
    install_kernel_chosen_ports(module)
    http, https = start_both(module)
    assert http.PORT != https.PORT
    assert http.PORT != 0 and https.PORT != 0


def test_a_port_taken_after_the_draw_is_not_used(module):
    install_kernel_chosen_ports(module)
    http = module.HTTPServer()
    drawn = http.PORT
    taken = hold(drawn)
    try:
        http.start()
    finally:
        taken.close()
    assert http.PORT != drawn


def test_the_urls_carry_the_bound_port_and_it_is_listening(module):
    install_kernel_chosen_ports(module)
    http, https = start_both(module)
    for server, scheme in ((http, "http"), (https, "https")):
        assert server.PREFIX == f"{scheme}://localhost:{server.PORT}"
        assert server.EMPTY_PAGE == f"{scheme}://localhost:{server.PORT}/empty.html"
        assert server.CROSS_PROCESS_PREFIX == f"{scheme}://127.0.0.1:{server.PORT}"
        with closing(socket.create_connection(("127.0.0.1", server.PORT), timeout=5)):
            pass


def test_the_reactor_is_put_back_and_the_fix_installs_once(module):
    real = module.reactor
    install_kernel_chosen_ports(module)
    wrapped = module.Server.start
    install_kernel_chosen_ports(module)
    assert module.Server.start is wrapped
    start_both(module)
    assert module.reactor is real


def test_a_changed_upstream_shape_fails_loudly(module):
    module.HTTPServer.start = lambda self: None
    with pytest.raises(AssertionError, match="overrides start"):
        install_kernel_chosen_ports(module)

    module = make_upstream_module()
    module.HTTPServer.listen = lambda self, factory: None
    install_kernel_chosen_ports(module)
    with pytest.raises(AssertionError, match="read the kernel-chosen port back"):
        module.HTTPServer().start()
