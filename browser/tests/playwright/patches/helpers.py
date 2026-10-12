"""
Shared helpers for patch verification tests.
"""

from contextlib import asynccontextmanager


@asynccontextmanager
async def launch_camoufox(os: str = "macos", headless: bool = True):
    """
    Launch Camoufox with a random preset.

    Yields (page, fingerprint_config) — the config dict lets tests check
    what values were sent to the browser.
    """
    from camoufox.async_api import AsyncCamoufox
    from camoufox.fingerprints import generate_context_fingerprint, get_random_preset

    fp = generate_context_fingerprint(preset=get_random_preset(os=os))
    async with AsyncCamoufox(
        fingerprint_preset=fp["preset"],
        headless=headless,
        os=os,
    ) as browser:
        context = await browser.new_context(**fp["context_options"])
        await context.add_init_script(fp["init_script"])
        page = await context.new_page()
        await page.goto("about:blank")
        yield page, fp["config"]


# --- chrome-context inspection (Marionette) on a hidden display -----------------
#
# Some guards assert browser-UI state a page cannot read (a URL-bar label, a chrome
# overlay, the graphics decision log). They drive Marionette's chrome context.
# Marionette itself shows the remote-control cue, so these always run on a PRIVATE
# Xvfb display -- never on a real screen.

import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List


def resolve_binary() -> Path:
    """The camoufox binary under test: `--binary <path>`, else the runner's
    CAMOUFOX_EXECUTABLE_PATH, else CAMOUFOX_BINARY, else the newest in-tree Linux
    build (never another target's objdir, which cannot execute here)."""
    if "--binary" in sys.argv:
        return Path(sys.argv[sys.argv.index("--binary") + 1]).resolve()
    for var in ("CAMOUFOX_EXECUTABLE_PATH", "CAMOUFOX_BINARY"):
        if os.environ.get(var):
            return Path(os.environ[var]).resolve()
    root = Path(__file__).resolve().parents[3]
    matches = sorted(root.glob("camoufox-*/obj-*-linux-gnu/dist/bin/camoufox-bin"))
    if not matches:
        raise SystemExit("no camoufox binary: set CAMOUFOX_EXECUTABLE_PATH")
    return matches[-1]


def launch_kwargs(**overrides: Any) -> Dict[str, Any]:
    """Camoufox() kwargs for a guard: headless, on the binary under test."""
    return {"headless": True, "executable_path": str(resolve_binary()), **overrides}


def check(failures: List[str], label: str, got: Any, want: Any) -> None:
    """Print one check and register it in `failures` when it fails; the guard
    triages the list at the end, so every arm still runs."""
    ok = got == want
    print(f"    [{'ok  ' if ok else 'FAIL'}] {label}: {got}" + ("" if ok else f" (expected {want})"))
    if not ok:
        failures.append(label)


@contextlib.contextmanager
def hidden_display() -> Iterator[str]:
    """A private Xvfb display for the duration of the block.

    The process environment points at it too. On a Wayland desktop an inherited
    WAYLAND_DISPLAY makes GTK skip the X display, so the browser never opens it.
    """
    if not shutil.which("Xvfb"):
        raise SystemExit("Xvfb is required for this guard")
    for n in range(140, 160):
        if not os.path.exists(f"/tmp/.X11-unix/X{n}"):
            break
    display = f":{n}"
    proc = subprocess.Popen(["Xvfb", display, "-screen", "0", "1400x900x24", "-nolisten", "tcp"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)
    saved = dict(os.environ)
    os.environ.update(DISPLAY=display, MOZ_ENABLE_WAYLAND="0", GDK_BACKEND="x11")
    os.environ.pop("WAYLAND_DISPLAY", None)
    try:
        yield display
    finally:
        os.environ.clear()
        os.environ.update(saved)
        proc.terminate()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# --- a local STUN server for the WebRTC guards ----------------------------------
#
# nICEr skips a loopback STUN server unless media.peerconnection.ice.loopback is
# set, so the server listens on the default-route address and the browser keeps
# the prefs it ships.

STUN_COOKIE = b"\x21\x12\xa4\x42"


def default_route_ipv4() -> str:
    """The address nICEr's default-address lookup picks. Connecting a UDP socket
    sends nothing; it only selects the source address."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("8.8.8.8", 53))
        return s.getsockname()[0]


def is_binding_request(data: bytes) -> bool:
    return data[:2] == b"\x00\x01" and data[4:8] == STUN_COOKIE


def binding_success(request: bytes, source: tuple) -> bytes:
    """RFC 5389 Binding Success Response to `request`, whose only attribute is an
    XOR-MAPPED-ADDRESS carrying the request's IPv4 source address and port."""
    ip, port = source
    xport = (port ^ 0x2112).to_bytes(2, "big")
    xaddr = bytes(a ^ b for a, b in zip(socket.inet_aton(ip), STUN_COOKIE))
    attr = b"\x00\x20\x00\x08\x00\x01" + xport + xaddr
    return b"\x01\x01" + len(attr).to_bytes(2, "big") + STUN_COOKIE + request[8:20] + attr


class Marionette:
    """Minimal Marionette client: length-prefixed JSON over TCP, chrome context."""

    def __init__(self, port: int, timeout: float = 60):
        deadline = time.time() + timeout
        while True:
            try:
                self.sock = socket.create_connection(("127.0.0.1", port), timeout=5)
                break
            except OSError:
                if time.time() > deadline:
                    raise
                time.sleep(0.5)
        self.sock.settimeout(timeout)
        self._id = 0
        self._recv()  # server hello
        self.call("WebDriver:NewSession", {"capabilities": {}})
        self.call("Marionette:SetContext", {"value": "chrome"})

    def _recv(self):
        buf = b""
        while b":" not in buf:
            buf += self.sock.recv(1)
        size, rest = buf.split(b":", 1)
        while len(rest) < int(size):
            rest += self.sock.recv(int(size) - len(rest))
        return json.loads(rest)

    def call(self, command: str, params: dict):
        self._id += 1
        data = json.dumps([0, self._id, command, params]).encode()
        self.sock.sendall(str(len(data)).encode() + b":" + data)
        while True:
            msg = self._recv()
            if isinstance(msg, list) and msg[1] == self._id:
                if msg[2]:
                    raise RuntimeError(f"{command}: {msg[2]}")
                return msg[3]

    def js(self, script: str):
        """Run chrome-context JS (in the browser window) and return its JSON value."""
        return self.call("WebDriver:ExecuteScript", {"script": script, "args": []}).get("value")

    def close(self):
        with contextlib.suppress(Exception):
            self.sock.close()


def marionette_args() -> List[str]:
    return ["--marionette", "--remote-allow-system-access"]
