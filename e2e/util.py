"""Small helpers shared by the journeys. Nothing here knows which driver is in use."""

from __future__ import annotations

import json
import socket
import time
from pathlib import Path
from typing import Any, List, Optional, Set

import psutil


class Checks:
    """Collect failures so one failing step does not hide the steps after it.
    A check that matches a filed finding (known.py) reports KNOWN instead."""

    def __init__(self, nodeid: str = "") -> None:
        self.nodeid = nodeid
        self.failed: List[str] = []

    def __call__(self, ok: Any, what: str) -> bool:
        import known

        k = known.for_check(self.nodeid, what)
        if k and not ok:
            print(f"KNOWN #{k[0]} {what}", flush=True)
            return False
        if k and ok and k[1]:
            print(f"FIXED? #{k[0]} {what}", flush=True)
            self.failed.append(f"{what} now passes; is #{k[0]} fixed? remove it from e2e/known.py")
            return True
        print(f"{'ok  ' if ok else 'FAIL'} {what}", flush=True)
        if not ok:
            self.failed.append(what)
        return bool(ok)

    def done(self) -> None:
        assert not self.failed, "failed: " + "; ".join(self.failed)


# Pages publish their result as JSON in #out and set data-done=1. Reading the DOM
# works from any world, which matters: Playwright's evaluate runs in an isolated
# world and cannot see page globals.
OUT_JS = (
    "(() => { const o = document.getElementById('out');"
    " return o && o.dataset.done === '1' ? o.textContent : null; })()"
)


def wait_for(page, js: str, timeout: float = 15) -> Any:
    end = time.monotonic() + timeout
    last_error = None
    while True:
        try:
            value = page.eval(js)
        except Exception as e:  # navigation in flight destroys the context; try again
            value, last_error = None, e
        if value:
            return value
        if time.monotonic() > end:
            why = f"; last error: {str(last_error)[:300]}" if last_error else ""
            raise TimeoutError(f"timed out waiting for {js}{why}")
        time.sleep(0.2)


def wait_out(page, timeout: float = 60) -> Any:
    try:
        return json.loads(wait_for(page, OUT_JS, timeout))
    except TimeoutError as e:
        try:
            where = page.eval("(() => { const o = document.getElementById('out'); "
                              "return [location.href, document.readyState, o ? o.dataset.progress || 'no progress' : 'no #out']; })()")
        except Exception as e:
            where = f"page did not answer: {str(e)[:120]}"
        raise TimeoutError(f"page never published #out in {timeout:.0f}s; page state {where}; {e}") from None


def header(req: dict, name: str) -> Optional[str]:
    return next((v for k, v in req["headers"] if k.lower() == name.lower()), None)


def browser_procs(binary: Path) -> List[psutil.Process]:
    """Every live process started from the browser's own directory, children included."""
    root = str(Path(binary).resolve().parent.parent if Path(binary).parent.name == "MacOS" else Path(binary).resolve().parent)
    found = []
    for p in psutil.process_iter(["exe", "cmdline"]):
        try:
            exe = p.info["exe"] or (p.info["cmdline"] or [""])[0]
        except (psutil.Error, IndexError):
            continue
        if exe and str(exe).startswith(root):
            found.append(p)
    return found


def wait_gone(binary: Path, timeout: float = 15) -> List[str]:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        left = [p for p in browser_procs(binary) if p.is_running() and p.status() != psutil.STATUS_ZOMBIE]
        if not left:
            return []
        time.sleep(0.5)
    return [f"{p.pid}:{p.name()}" for p in left]


def rss_mb(binary: Path) -> float:
    total = 0
    for p in browser_procs(binary):
        try:
            total += p.memory_info().rss
        except psutil.Error:
            pass
    return round(total / 2**20, 1)


def lan_ips() -> Set[str]:
    """This host's non-loopback IPv4 addresses, found without sending traffic."""
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 9))  # TEST-NET-1: routes, never answers
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        ips.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    return {ip for ip in ips if not ip.startswith("127.")}


BINARY_NAMES = ("camoufox-bin", "camoufox.exe")


def find_binary(root: Path) -> Path:
    """The browser executable inside an unpacked release or build zip."""
    for app in root.rglob("Camoufox.app"):
        exe = app / "Contents" / "MacOS" / "camoufox"
        if exe.exists():
            return exe
    for name in BINARY_NAMES:
        for exe in root.rglob(name):
            return exe
    raise FileNotFoundError(f"no Camoufox executable under {root}")


def build_id(binary: Path) -> str:
    binary = Path(binary)
    for ini in (binary.parent / "application.ini", binary.parent.parent / "Resources" / "application.ini"):
        if ini.exists():
            for line in ini.read_text(errors="replace").splitlines():
                if line.startswith("BuildID="):
                    return line.split("=", 1)[1]
    return "unknown"
