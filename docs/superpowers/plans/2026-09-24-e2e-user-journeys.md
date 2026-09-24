# E2E User-Journey Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `e2e/`, a black-box suite that drives Camoufox the way users do, through three entry points, against local realistic pages and real sites.

**Architecture:** Each journey is a pytest test that takes a `drv` fixture, parametrized over `pkg`, `pw` and `go`. Journeys talk to a session-scoped local site, which records every request it receives. Expected values come from three places:

- **A:** quoted public documentation (`oracle/docs.py`).
- **B:** the same journey run on Playwright's bundled Firefox, compared on behaviour only.
- **C:** pure coherence rules (`oracle/coherence.py`). Each rule has a negative control that must go red.

**Tech Stack:**

- Python 3.12 with the stdlib (`http.server`, `socketserver`, `email`, `wave`)
- pytest and pytest-timeout
- psutil (already in `ci/requirements.txt`)
- Playwright ≤1.62 (via `pythonlib`)
- Go 1.22+ (`goapi`)

**Spec:** `docs/superpowers/specs/2026-09-24-e2e-user-journeys-design.md`

## Global Constraints

- **No new third-party dependency.** Use only the stdlib, pytest, pytest-timeout, psutil, playwright, camoufox and goapi.
- **Every expectation cites its source.** It comes from a quoted public document (A), from the reference browser (B), or from a coherence rule with a negative control (C). None is derived from reading `patches/`.
- **A driver that cannot express an option skips.** It calls `pytest.skip("<driver>: no <option>")` and never silently drops the option.
- **Checks are deferred.** A multi-step journey collects failures through `Checks` and reports them at the end.
- **`live` never runs on the PR gate.** Its detector results print aggregates only: a grade, or a count and a total.
- **Each run prints provenance.** That means the binary path, its BuildID and, when a zip was used, its SHA-256.
- **`gh` needs the repo flag.** Every `gh` call takes `--repo lang315/camoufox`.

**Deviations from the spec, and why:**

- **The site package is named `e2e/web/`, not `e2e/site/`.** `site` is a stdlib module, and shadowing it breaks the interpreter.
- **There is no `/echo` page.** The server's own request record for `/fp` supplies the headers. Firefox renders `application/json` in its JSON viewer, which would change the DOM the test reads.
- **Oracle B covers journey 6 (web APIs) and the frames/dialog part of journey 4.** The other steps of journey 4 have absolute expected outcomes (logged in, hash matches), which already hold on any browser.
- **SOCKS5 runs with auth.** If Playwright refuses SOCKS auth, the test skips and names that reason.
- **The soak runs 200 s per driver on CI**, 600 s in total, which matches the spec's ten minutes. By hand, `--soak-seconds` sets it.

---

### Task 1: Scaffold, utilities, coherence oracle (offline, TDD)

**Files:**
- Create: `e2e/pytest.ini`, `e2e/util.py`, `e2e/oracle/__init__.py`, `e2e/oracle/coherence.py`, `e2e/oracle/docs.py`, `e2e/oracle/test_oracle.py`

**Interfaces:**
- Produces: `util.Checks` (`check(ok, what) -> bool`, `check.done()`), `util.wait_out(page, timeout=30) -> Any`, `util.wait_for(page, js, timeout=15) -> Any`, `util.header(req, name) -> str|None`, `util.browser_procs(binary) -> list[psutil.Process]`, `util.lan_ips() -> set[str]`, `util.find_binary(root: Path) -> Path`, `util.build_id(binary) -> str`
- Produces: `coherence.evaluate(fp: dict, req: dict, os_name: str|None) -> list[tuple[name, ok: bool|None, detail, control_red: bool|None]]`
- Produces: `docs.CLAIMS: dict[str, tuple[path, quote]]`, `docs.cite(key) -> str`

- [ ] **Step 1: Write the failing oracle tests** (`e2e/oracle/test_oracle.py`, below)
- [ ] **Step 2: Run** `cd e2e && python3 -m pytest oracle -q`. Expect ImportError.
- [ ] **Step 3: Write `pytest.ini`, `util.py`, `coherence.py`, `docs.py`** (below)
- [ ] **Step 4: Run** `cd e2e && python3 -m pytest oracle -q`. Expect all to pass.
- [ ] **Step 5: Commit** `feat(e2e): scaffold, utilities and the coherence oracle`

<!-- file: e2e/pytest.ini -->
```ini
[pytest]
pythonpath = . ../pythonlib
testpaths = oracle journeys live
markers =
    live: real public sites; never on the PR gate
    slow: lifecycle and soak journeys
addopts = -p no:cacheprovider -rs -m "not live"
```

<!-- file: e2e/util.py -->
```python
"""Small helpers shared by the journeys. Nothing here knows which driver is in use."""

from __future__ import annotations

import json
import socket
import time
from pathlib import Path
from typing import Any, List, Optional, Set

import psutil


class Checks:
    """Collect failures so one failing step does not hide the steps after it."""

    def __init__(self) -> None:
        self.failed: List[str] = []

    def __call__(self, ok: Any, what: str) -> bool:
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
    while True:
        try:
            value = page.eval(js)
        except Exception:  # navigation in flight destroys the context; try again
            value = None
        if value:
            return value
        if time.monotonic() > end:
            raise TimeoutError(f"timed out waiting for {js}")
        time.sleep(0.2)


def wait_out(page, timeout: float = 30) -> Any:
    return json.loads(wait_for(page, OUT_JS, timeout))


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
```

<!-- file: e2e/oracle/__init__.py -->
```python
```

<!-- file: e2e/oracle/coherence.py -->
```python
"""Oracle C: coherence rules.

Each rule compares two sources that a real browser keeps in agreement, so it
needs no absolute truth. A rule is only trusted once it has been seen red: each
one carries a mutation that creates exactly the disagreement it looks for, and
`evaluate` checks the rule fails on it. A rule that cannot go red is VACUOUS.

`fp` is what /fp published; `req` is the server's record of the /fp request.
"""

from __future__ import annotations

import copy
from typing import Callable, List, Optional, Tuple

UA_OS = {"windows": "Windows NT", "macos": "Macintosh", "linux": "Linux"}
PLATFORM_OS = {"windows": "Win", "macos": "Mac", "linux": "Linux"}
WEBGL_MARKERS = {"windows": ("Direct3D", "D3D11"), "macos": ("Apple",), "linux": ("Mesa",)}
WORKER_KEYS = ("ua", "platform", "language", "cores", "tz")

Result = Tuple[Optional[bool], str]


def _header(req, name):
    return next((v for k, v in req["headers"] if k.lower() == name.lower()), None)


def _ua_os(ua: str) -> Optional[str]:
    return next((k for k, v in UA_OS.items() if v in ua), None)


def _platform_os(platform: str) -> Optional[str]:
    return next((k for k, v in PLATFORM_OS.items() if platform.startswith(v)), None)


def ua_matches_header(fp, req, os_name) -> Result:
    js, wire = fp["main"]["ua"], _header(req, "User-Agent")
    return js == wire, f"js={js!r} header={wire!r}"


def platform_matches_ua(fp, req, os_name) -> Result:
    ua_os, plat_os = _ua_os(fp["main"]["ua"]), _platform_os(fp["main"]["platform"])
    return ua_os is not None and ua_os == plat_os, f"ua->{ua_os} platform={fp['main']['platform']!r}->{plat_os}"


def os_is_requested(fp, req, os_name) -> Result:
    if os_name is None:
        return None, "no os requested"
    got = (_ua_os(fp["main"]["ua"]), _platform_os(fp["main"]["platform"]))
    return got == (os_name, os_name), f"requested {os_name}, ua/platform say {got}"


def language_matches_header(fp, req, os_name) -> Result:
    first = (_header(req, "Accept-Language") or "").split(",")[0].split(";")[0].strip()
    return fp["main"]["language"] == first, f"navigator.language={fp['main']['language']!r} accept-language[0]={first!r}"


def languages_lead_with_language(fp, req, os_name) -> Result:
    langs = fp["main"]["languages"]
    return bool(langs) and langs[0] == fp["main"]["language"], f"languages={langs!r}"


def intl_locale_matches_language(fp, req, os_name) -> Result:
    intl, lang = fp["intl"], fp["main"]["language"]
    return intl.split("-")[0] == lang.split("-")[0], f"Intl locale={intl!r} navigator.language={lang!r}"


def timezone_offset_agrees(fp, req, os_name) -> Result:
    tz = fp["tz"]
    return tz["offset"] == tz["derived"], f"getTimezoneOffset={tz['offset']} Intl({tz['tz']})->{tz['derived']}"


def screen_contains_viewport(fp, req, os_name) -> Result:
    s = fp["screen"]
    ok = s["w"] >= s["iw"] and s["h"] >= s["ih"] and s["aw"] <= s["w"] and s["ah"] <= s["h"] and s["ow"] >= s["iw"]
    return ok, f"screen {s['w']}x{s['h']} avail {s['aw']}x{s['ah']} outer {s['ow']}x{s['oh']} inner {s['iw']}x{s['ih']}"


def dpr_plausible(fp, req, os_name) -> Result:
    return 0.5 <= fp["screen"]["dpr"] <= 4, f"devicePixelRatio={fp['screen']['dpr']}"


def webdriver_false(fp, req, os_name) -> Result:
    return fp["webdriver"] is False, f"navigator.webdriver={fp['webdriver']!r}"


def workers_agree(fp, req, os_name) -> Result:
    # Only flags disagreement: a worker agreeing with the main thread is not proof
    # either is right (cross-thread reference, CLAUDE.md lesson 4).
    kinds = [k for k in ("dedicated", "shared", "service") if isinstance(fp.get(k), dict)]
    if not kinds:
        return None, "no worker answered"
    bad = [f"{k}.{key}" for k in kinds for key in WORKER_KEYS if fp[k].get(key) != fp["main"].get(key)]
    return not bad, f"compared {kinds}; mismatched {bad}"


def fonts_measurable(fp, req, os_name) -> Result:
    f = fp["fonts"]["floors"]
    return fp["fonts"]["valid"], f"fallback floors monospace={f['mono']} serif={f['serif']} (equal floors = INVALID)"


def fonts_own_os(fp, req, os_name) -> Result:
    if os_name is None or not fp["fonts"]["valid"]:
        return None, "no os requested or floors INVALID"
    got = fp["fonts"]["rendered"][os_name]
    return bool(got), f"{os_name} marker families rendered: {got}"


def fonts_no_foreign_os(fp, req, os_name) -> Result:
    if os_name is None or not fp["fonts"]["valid"]:
        return None, "no os requested or floors INVALID"
    foreign = {k: v for k, v in fp["fonts"]["rendered"].items() if k != os_name and v}
    return not foreign, f"other-OS marker families rendered: {foreign}"


def webgl_no_foreign_os(fp, req, os_name) -> Result:
    if os_name is None or not fp.get("webgl"):
        return None, "no os requested or no WebGL"
    text = f"{fp['webgl']['vendor']} {fp['webgl']['renderer']}"
    foreign = [m for k, ms in WEBGL_MARKERS.items() if k != os_name for m in ms if m in text]
    return not foreign, f"{text!r}; other-OS markers {foreign}"


def voices_no_foreign_os(fp, req, os_name) -> Result:
    if os_name is None or fp.get("voices") is None:
        return None, "no os requested or no speechSynthesis"
    apple = [v["name"] for v in fp["voices"] if v["uri"].startswith("com.apple")]
    microsoft = [v["name"] for v in fp["voices"] if v["name"].startswith("Microsoft ")]
    foreign = {"windows": apple, "macos": microsoft, "linux": apple + microsoft}[os_name]
    return not foreign, f"{len(fp['voices'])} voices; other-OS voices {foreign[:5]}"


def _other(os_name):
    return next(k for k in UA_OS if k != (os_name or "windows"))


def _set_header(req, name, value):
    req["headers"] = [(k, v) for k, v in req["headers"] if k.lower() != name.lower()] + [(name, value)]


def _m_ua(fp, req, o):
    _set_header(req, "User-Agent", "X")


def _m_platform(fp, req, o):
    fp["main"]["platform"] = "MacIntel" if _ua_os(fp["main"]["ua"]) != "macos" else "Win32"


def _m_language(fp, req, o):
    fp["main"]["language"] = "zz-ZZ"


def _m_languages(fp, req, o):
    fp["main"]["languages"] = ["zz"]


def _m_intl(fp, req, o):
    fp["intl"] = "zz-ZZ"


def _m_tz(fp, req, o):
    fp["tz"]["derived"] = fp["tz"]["offset"] + 60


def _m_screen(fp, req, o):
    fp["screen"]["iw"] = fp["screen"]["w"] + 1


def _m_dpr(fp, req, o):
    fp["screen"]["dpr"] = 9


def _m_webdriver(fp, req, o):
    fp["webdriver"] = True


def _m_workers(fp, req, o):
    fp["dedicated"] = dict(fp["main"], ua="X")


def _m_floors(fp, req, o):
    fp["fonts"]["valid"] = False


def _m_own_fonts(fp, req, o):
    fp["fonts"]["rendered"][o] = []


def _m_foreign_fonts(fp, req, o):
    fp["fonts"]["rendered"][_other(o)] = ["X"]


def _m_webgl(fp, req, o):
    fp["webgl"]["renderer"] += " " + WEBGL_MARKERS[_other(o)][0]


def _m_voices(fp, req, o):
    fp["voices"] = fp["voices"] + [{"name": "Microsoft X", "uri": "com.apple.x"}]


# (rule, mutation that must make it fail, optional os override for the control)
RULES: List[Tuple[Callable, Callable]] = [
    (ua_matches_header, _m_ua),
    (platform_matches_ua, _m_platform),
    (os_is_requested, None),  # control: ask about a different OS, below
    (language_matches_header, _m_language),
    (languages_lead_with_language, _m_languages),
    (intl_locale_matches_language, _m_intl),
    (timezone_offset_agrees, _m_tz),
    (screen_contains_viewport, _m_screen),
    (dpr_plausible, _m_dpr),
    (webdriver_false, _m_webdriver),
    (workers_agree, _m_workers),
    (fonts_measurable, _m_floors),
    (fonts_own_os, _m_own_fonts),
    (fonts_no_foreign_os, _m_foreign_fonts),
    (webgl_no_foreign_os, _m_webgl),
    (voices_no_foreign_os, _m_voices),
]


def evaluate(fp: dict, req: dict, os_name: Optional[str]):
    out = []
    for rule, mutate in RULES:
        ok, detail = rule(fp, req, os_name)
        red = None
        if ok is not None:
            f2, r2 = copy.deepcopy(fp), copy.deepcopy(req)
            if mutate is None:
                red = rule(f2, r2, _other(os_name))[0] is False
            else:
                mutate(f2, r2, os_name)
                red = rule(f2, r2, os_name)[0] is False
        out.append((rule.__name__, ok, detail, red))
    return out
```

<!-- file: e2e/oracle/docs.py -->
```python
"""Oracle A: expectations taken from public documentation, each with its quote.

`cite` fails if the quote is no longer in the file, so an expectation cannot
outlive the sentence it came from.
"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

CLAIMS = {
    "isolated_eval": ("README.md", 'websites can no longer "see" any JavaScript that Playwright would typically inject'),
    "trusted_input": ("README.md", "meaning they are handled the exact same way as if you were using the browser normally"),
    "webdriver": ("README.md", "Fixes `navigator.webdriver` detection"),
    "os_option": ("pythonlib/camoufox/utils.py", 'Can be "windows", "macos", "linux", or a list to randomly choose from.'),
    "locale": ("pythonlib/camoufox/utils.py", "The first listed locale will be used for the Intl API."),
    "geoip": ("pythonlib/camoufox/utils.py", "Calculate longitude, latitude, timezone, country, & locale based on the IP address."),
    "humanize": ("pythonlib/camoufox/utils.py", "Humanize the cursor movement."),
    "virtual": ("pythonlib/camoufox/utils.py", "passing headless='virtual' to Camoufox & AsyncCamoufox"),
    "webrtc": ("README.md", "WebRTC IP spoofing at the protocol level"),
    "unique_context": ("pythonlib/camoufox/sync_api.py", "Creates a new browser context with a unique fingerprint identity."),
}


def cite(key: str) -> str:
    path, quote = CLAIMS[key]
    text = (REPO / path).read_text(encoding="utf-8")
    assert quote in text, f"oracle A: {path} no longer says {quote!r}; re-derive this expectation"
    return f"{path}: {quote!r}"
```

<!-- file: e2e/oracle/test_oracle.py -->
```python
"""Offline checks of the oracles themselves: no browser needed."""

import copy

import pytest

from oracle import coherence, docs

WINDOWS_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0"
SNAP = {"ua": WINDOWS_UA, "platform": "Win32", "language": "en-US", "languages": ["en-US", "en"], "cores": 8, "tz": "Europe/Berlin"}
FP = {
    "main": SNAP,
    "intl": "en-US",
    "tz": {"tz": "Europe/Berlin", "offset": -120, "derived": -120},
    "screen": {"w": 1920, "h": 1080, "aw": 1920, "ah": 1040, "iw": 1280, "ih": 720, "ow": 1296, "oh": 800, "dpr": 1},
    "webdriver": False,
    "dedicated": dict(SNAP),
    "shared": dict(SNAP),
    "service": "error: TypeError",
    "fonts": {"floors": {"mono": 400.0, "serif": 350.0}, "valid": True,
              "rendered": {"windows": ["Segoe UI"], "macos": [], "linux": []}},
    "webgl": {"vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, GeForce Direct3D11 vs_5_0 ps_5_0)"},
    "voices": [{"name": "Microsoft David", "uri": "urn:moz-tts:sapi:Microsoft David"}],
    "canvas": 123,
}
REQ = {"headers": [("Host", "x"), ("User-Agent", WINDOWS_UA), ("Accept-Language", "en-US,en;q=0.5")]}


def test_plausible_windows_browser_passes_every_rule():
    for name, ok, detail, red in coherence.evaluate(copy.deepcopy(FP), copy.deepcopy(REQ), "windows"):
        assert ok is True, (name, detail)
        assert red is True, f"{name}: negative control did not go red (VACUOUS)"


@pytest.mark.parametrize("key", sorted(docs.CLAIMS))
def test_every_documented_claim_is_still_documented(key):
    docs.cite(key)


def test_foreign_fonts_are_caught():
    fp = copy.deepcopy(FP)
    fp["fonts"]["rendered"]["macos"] = ["Helvetica Neue"]
    assert coherence.fonts_no_foreign_os(fp, REQ, "windows")[0] is False


def test_rule_without_os_is_not_applicable():
    assert coherence.os_is_requested(FP, REQ, None)[0] is None
```

---

### Task 2: Local site, WebSocket, proxy, STUN, pages

**Files:**
- Create: `e2e/web/__init__.py`, `e2e/web/server.py`, `e2e/web/ws.py`, `e2e/web/proxy.py`, `e2e/web/stun.py`, `e2e/web/pages/*`, `e2e/web/test_web.py`

**Interfaces:**
- Produces: `Site()` with `.start()` and `.stop()`, `.url(path)` (`127.0.0.1:port1`), `.url2(path)` (`localhost:port2`), `.port1`, `.port2`, `.stun_port`, `.seen(path) -> list[dict]` (keys: `method`, `path`, `host`, `headers` as a list of tuples, `ip`, `body_sha`, `body`)
- Produces: `DOWNLOAD_SHA`
- Produces: `Proxy(kind: "http"|"socks5", auth=None|(user, password))` with `.playwright() -> dict`, `.hosts: list[str]`, `.stop()`
- Produces: `Stun()` with `.port`, `.seen: list[str]`, `.stop()`

- [ ] **Step 1: Write the failing test** `e2e/web/test_web.py` (below). It drives the site with `urllib` and raw sockets.
- [ ] **Step 2: Run** `cd e2e && python3 -m pytest web -q`. Expect ImportError.
- [ ] **Step 3: Write the server, ws, proxy, stun and pages** (below)
- [ ] **Step 4: Run** `cd e2e && python3 -m pytest web -q`. Expect all to pass.
- [ ] **Step 5: Commit** `feat(e2e): local site, proxies and STUN responder`

Add `web` to `testpaths` in `e2e/pytest.ini` as part of this task.

<!-- file: e2e/web/__init__.py -->
```python
```

<!-- file: e2e/web/server.py -->
```python
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
```

<!-- file: e2e/web/ws.py -->
```python
"""A minimal RFC 6455 echo endpoint, enough for a page to open, send and receive."""

import base64
import hashlib
import struct

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def is_upgrade(headers) -> bool:
    return (headers.get("Upgrade") or "").lower() == "websocket"


def serve_echo(handler) -> None:
    accept = base64.b64encode(hashlib.sha1((handler.headers["Sec-WebSocket-Key"] + GUID).encode()).digest()).decode()
    handler.send_response(101)
    handler.send_header("Upgrade", "websocket")
    handler.send_header("Connection", "Upgrade")
    handler.send_header("Sec-WebSocket-Accept", accept)
    handler.end_headers()
    handler.wfile.flush()
    r, w = handler.rfile, handler.wfile
    while True:
        head = r.read(2)
        if len(head) < 2:
            break
        op, n = head[0] & 0x0F, head[1] & 0x7F
        if n == 126:
            n = struct.unpack(">H", r.read(2))[0]
        elif n == 127:
            n = struct.unpack(">Q", r.read(8))[0]
        mask = r.read(4)  # client frames are always masked
        data = bytes(b ^ mask[i % 4] for i, b in enumerate(r.read(n)))
        if op == 8:
            w.write(b"\x88\x00")
            break
        if op in (1, 2):
            # ponytail: echo frames are short; add the 64-bit length form if a page ever sends >64 KiB
            size = bytes([n]) if n < 126 else b"\x7e" + struct.pack(">H", n)
            w.write(bytes([0x80 | op]) + size + data)
            w.flush()
    handler.close_connection = True
```

<!-- file: e2e/web/proxy.py -->
```python
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
```

<!-- file: e2e/web/stun.py -->
```python
"""A STUN binding responder (RFC 5389): enough for a browser to gather a
server-reflexive candidate, and a record that it asked."""

import socket
import struct
import threading

MAGIC = 0x2112A442


class Stun:
    def __init__(self, host: str = "0.0.0.0") -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((host, 0))
        self.port = self.sock.getsockname()[1]
        self.seen: list = []
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while True:
            try:
                data, (ip, port) = self.sock.recvfrom(2048)
            except OSError:
                return
            if len(data) < 20 or struct.unpack(">H", data[:2])[0] != 0x0001:
                continue
            self.seen.append(ip)
            xip = struct.unpack(">I", socket.inet_aton(ip))[0] ^ MAGIC
            attr = struct.pack(">HHBBHI", 0x0020, 8, 0, 1, port ^ (MAGIC >> 16), xip)
            self.sock.sendto(struct.pack(">HHI", 0x0101, len(attr), MAGIC) + data[8:20] + attr, (ip, port))

    def stop(self) -> None:
        self.sock.close()
```

<!-- file: e2e/web/test_web.py -->
```python
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
```

<!-- file: e2e/web/pages/index.html -->
```html
<!doctype html><meta charset="utf-8"><title>E2E home</title>
<p>Local test site. <a href="/login">Sign in</a> · <a href="/shop">Shop</a></p>
<button id="peek">What can this page see?</button><div id="out"></div>
<script>
// Reports, from the page's own world, whether a global set by automation is visible.
document.getElementById("peek").onclick = () => {
  const out = document.getElementById("out");
  out.textContent = JSON.stringify({probe: typeof window.__e2e_probe, attr: document.documentElement.dataset.fromEval || null});
  out.dataset.done = "1";
};
</script>
```

<!-- file: e2e/web/pages/login.html -->
```html
<!doctype html><meta charset="utf-8"><title>Sign in</title>
<form id="f" method="post" action="/login" novalidate>
  <label>User <input id="user" name="user" autocomplete="off"></label>
  <label>Password <input id="pass" name="pass" type="password"></label>
  <input type="hidden" name="trusted" id="trusted">
  <button id="go" type="submit">Sign in</button>
</form>
<p id="err"></p>
<script>
const events = [];
for (const t of ["keydown", "keyup", "mousedown", "mouseup", "click"]) addEventListener(t, e => events.push(e.isTrusted), true);
const err = document.getElementById("err");
if (location.search.includes("err=1")) err.textContent = "Wrong user or password";
document.getElementById("f").addEventListener("submit", e => {
  const user = document.getElementById("user").value, pass = document.getElementById("pass").value;
  if (!user || !pass) { e.preventDefault(); err.textContent = "Both fields are required"; return; }
  document.getElementById("trusted").value = JSON.stringify({n: events.length, all: events.every(Boolean)});
});
</script>
```

<!-- file: e2e/web/pages/account.html -->
```html
<!doctype html><meta charset="utf-8"><title>Account</title><h1 id="welcome">Welcome alice</h1>
```

<!-- file: e2e/web/pages/shop.html -->
```html
<!doctype html><meta charset="utf-8"><title>Shop</title>
<nav id="menu" style="padding:8px;background:#eee">Menu <a id="cart-link" href="/shop/cart" hidden>Cart</a></nav>
<main id="app"></main>
<script>
const cart = [];
let shown = 0;
const $ = id => document.getElementById(id);
$("menu").addEventListener("mouseenter", () => { $("cart-link").hidden = false; });
function more() {
  for (let i = 0; i < 10; i++, shown++) {
    const d = document.createElement("div");
    d.className = "item"; d.style.height = "120px";
    d.innerHTML = `Item ${shown} <button class="add" data-id="${shown}">Add</button>`;
    $("list").append(d);
  }
}
function render() {
  if (location.pathname === "/shop/cart") {
    $("app").innerHTML = `<h1>Cart</h1><ul id="cart">${cart.map(i => `<li>Item ${i}</li>`).join("")}</ul>`;
    return;
  }
  $("app").innerHTML = `<h1>Items</h1><div id="list"></div>`;
  shown = 0; more();
}
addEventListener("scroll", () => { if ($("list") && innerHeight + scrollY >= document.body.scrollHeight - 50) more(); });
document.addEventListener("click", e => {
  const add = e.target.closest(".add");
  if (add) { cart.push(+add.dataset.id); add.textContent = "Added"; }
  const link = e.target.closest("#cart-link");
  if (link) { e.preventDefault(); history.pushState({}, "", link.href); render(); }
});
addEventListener("popstate", render);
render();
</script>
```

<!-- file: e2e/web/pages/upload.html -->
```html
<!doctype html><meta charset="utf-8"><title>Upload</title>
<input type="file" id="file"><button id="send">Send</button><div id="out"></div>
<script>
document.getElementById("send").onclick = async () => {
  const fd = new FormData();
  fd.append("f", document.getElementById("file").files[0]);
  const r = await fetch("/upload", {method: "POST", body: fd});
  const out = document.getElementById("out");
  out.textContent = await r.text(); out.dataset.done = "1";
};
</script>
```

<!-- file: e2e/web/pages/download.html -->
```html
<!doctype html><meta charset="utf-8"><title>Download</title>
<a id="dl" href="/download/file.bin" download>Download the file</a>
```

<!-- file: e2e/web/pages/frames.html -->
```html
<!doctype html><meta charset="utf-8"><title>Frames</title>
<iframe id="child" src="{{O2}}/child.html" width="300" height="80"></iframe>
<button id="pop">Open popup</button><button id="dialogs">Dialogs</button><div id="out"></div>
<script>
const r = {};
const out = document.getElementById("out");
function done() {
  if (r.childPong && r.popup && r.dialogs) { out.textContent = JSON.stringify(r); out.dataset.done = "1"; }
}
addEventListener("message", e => {
  if (e.data.kind === "child") {
    r.child = {origin: e.origin, sees: e.data.origin};
    document.getElementById("child").contentWindow.postMessage("pong", e.origin);
  }
  if (e.data.kind === "child-pong") r.childPong = true;
  if (e.data.kind === "popup") r.popup = {origin: e.origin, hasOpener: e.data.hasOpener};
  done();
});
document.getElementById("pop").onclick = () => window.open("{{O2}}/popup.html", "_blank", "width=400,height=300");
document.getElementById("dialogs").onclick = () => {
  r.dialogs = {alert: alert("hello") === undefined, confirm: confirm("continue?"), prompt: prompt("name?", "default")};
  done();
};
</script>
```

<!-- file: e2e/web/pages/child.html -->
```html
<!doctype html><meta charset="utf-8"><title>Child</title><p>cross-origin child</p>
<script>
parent.postMessage({kind: "child", origin: location.origin}, "*");
addEventListener("message", e => { if (e.data === "pong") parent.postMessage({kind: "child-pong"}, "*"); });
</script>
```

<!-- file: e2e/web/pages/popup.html -->
```html
<!doctype html><meta charset="utf-8"><title>Popup</title>
<script>
opener.postMessage({kind: "popup", hasOpener: !!opener}, "*");
setTimeout(() => window.close(), 300);
</script>
```

<!-- file: e2e/web/pages/sw.js -->
```js
const snap = () => ({ua: navigator.userAgent, platform: navigator.platform, language: navigator.language,
  languages: [...navigator.languages], cores: navigator.hardwareConcurrency,
  tz: Intl.DateTimeFormat().resolvedOptions().timeZone});
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", e => {
  if (new URL(e.request.url).pathname === "/sw-probe") e.respondWith(new Response("from-sw"));
});
self.addEventListener("message", e => e.source.postMessage(snap()));
```

<!-- file: e2e/web/pages/fp-worker.js -->
```js
const snap = () => ({ua: navigator.userAgent, platform: navigator.platform, language: navigator.language,
  languages: [...navigator.languages], cores: navigator.hardwareConcurrency,
  tz: Intl.DateTimeFormat().resolvedOptions().timeZone});
self.onconnect = e => e.ports[0].postMessage(snap());  // SharedWorker
self.onmessage = () => postMessage(snap());            // dedicated Worker
```

<!-- file: e2e/web/pages/apps.html -->
```html
<!doctype html><meta charset="utf-8"><title>Apps</title>
<canvas id="c" width="64" height="64"></canvas><canvas id="blank" width="64" height="64"></canvas>
<canvas id="g" width="64" height="64"></canvas>
<video id="v" muted playsinline></video><audio id="a"></audio>
<button id="clip">Copy</button><div id="out"></div>
<script>
const $ = id => document.getElementById(id);
const r = {};
const within = (ms, p) => Promise.race([p, new Promise((_, no) => setTimeout(() => no(new Error("timeout")), ms))]);
async function t(name, fn) {
  try { r[name] = await within(8000, fn()); } catch (e) { r[name] = "error: " + ((e && e.name) || e); }
}
const sum = cv => cv.getContext("2d").getImageData(0, 0, cv.width, cv.height).data.reduce((a, b) => a + b, 0);
let autoDone = false, clipDone = false;
function finish() {
  if (autoDone && clipDone) { $("out").textContent = JSON.stringify(r); $("out").dataset.done = "1"; }
}
async function run() {
  await t("websocket", () => new Promise((ok, no) => {
    const w = new WebSocket(`ws://${location.host}/ws`);
    w.onopen = () => w.send("ping");
    w.onmessage = e => { ok(e.data === "ping"); w.close(); };
    w.onerror = () => no(new Error("ws error"));
  }));
  await t("indexeddb", () => new Promise((ok, no) => {
    const q = indexedDB.open("e2e", 1);
    q.onupgradeneeded = () => q.result.createObjectStore("s");
    q.onerror = () => no(q.error);
    q.onsuccess = () => {
      const tx = q.result.transaction("s", "readwrite");
      tx.objectStore("s").put("v", "k");
      tx.oncomplete = () => { const g = q.result.transaction("s").objectStore("s").get("k"); g.onsuccess = () => ok(g.result === "v"); };
    };
  }));
  await t("serviceworker", async () => {
    await navigator.serviceWorker.register("/sw.js", {scope: "/"});
    await navigator.serviceWorker.ready;
    if (!navigator.serviceWorker.controller)
      await new Promise(ok => navigator.serviceWorker.addEventListener("controllerchange", ok, {once: true}));
    return (await (await fetch("/sw-probe")).text()) === "from-sw";
  });
  await t("canvas", async () => {
    const x = $("c").getContext("2d");
    x.fillStyle = "#c00"; x.fillRect(8, 8, 48, 48); x.font = "20px serif"; x.fillText("Hi", 10, 30);
    return sum($("c")) !== sum($("blank"));
  });
  await t("webgl", async () => {
    const gl = $("g").getContext("webgl");
    if (!gl) return "no context";
    gl.clearColor(0, 0.5, 0, 1); gl.clear(gl.COLOR_BUFFER_BIT);
    const px = new Uint8Array(4); gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);
    return px[1] > 100 && px[3] === 255;
  });
  await t("audio", () => new Promise((ok, no) => {
    const a = $("a"); a.onloadedmetadata = () => ok(a.duration > 0.4); a.onerror = () => no(a.error); a.src = "/tone.wav";
  }));
  await t("video", async () => {
    const cv = $("c"), x = cv.getContext("2d");
    const tick = setInterval(() => { x.fillStyle = `hsl(${Date.now() % 360},80%,50%)`; x.fillRect(0, 0, 64, 64); }, 50);
    const rec = new MediaRecorder(cv.captureStream(20)); const chunks = [];
    rec.ondataavailable = e => chunks.push(e.data); rec.start();
    await new Promise(ok => setTimeout(ok, 800));
    const stopped = new Promise(ok => rec.onstop = ok); rec.stop(); await stopped; clearInterval(tick);
    const v = $("v");
    const meta = new Promise((ok, no) => { v.onloadedmetadata = ok; v.onerror = () => no(v.error); });
    v.src = URL.createObjectURL(new Blob(chunks, {type: rec.mimeType})); await meta;
    return v.videoWidth === 64;
  });
  await t("webaudio", async () => {
    const ac = new OfflineAudioContext(1, 4410, 44100); const o = ac.createOscillator();
    o.connect(ac.destination); o.start();
    return (await ac.startRendering()).getChannelData(0).some(s => s !== 0);
  });
  await t("geolocation", () => new Promise(ok =>
    navigator.geolocation.getCurrentPosition(() => ok("position"), e => ok("error " + e.code), {timeout: 3000})));
  autoDone = true; finish();
}
$("clip").onclick = () => t("clipboard", () => navigator.clipboard.writeText("e2e").then(() => true))
  .then(() => { clipDone = true; finish(); });
run();
</script>
```

<!-- file: e2e/web/pages/fp.html -->
```html
<!doctype html><meta charset="utf-8"><title>Fingerprint</title><div id="out"></div>
<script>
// Everything an ordinary page can read about the browser, computed by the page itself.
const snap = () => ({ua: navigator.userAgent, platform: navigator.platform, language: navigator.language,
  languages: [...navigator.languages], cores: navigator.hardwareConcurrency,
  tz: Intl.DateTimeFormat().resolvedOptions().timeZone});
function tzAgree() {
  const d = new Date(), tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const p = Object.fromEntries(new Intl.DateTimeFormat("en-US", {timeZone: tz, hourCycle: "h23", year: "numeric",
    month: "numeric", day: "numeric", hour: "numeric", minute: "numeric"}).formatToParts(d).map(x => [x.type, x.value]));
  const wall = Date.UTC(+p.year, p.month - 1, +p.day, +p.hour, +p.minute);
  const derived = Math.round((d.getTime() - d.getSeconds() * 1000 - d.getMilliseconds() - wall) / 60000);
  return {tz, offset: d.getTimezoneOffset(), derived};
}
function fonts() {
  // Real OSes' default families. Rendered = same width under two fallbacks whose widths differ.
  const MARKERS = {windows: ["Segoe UI", "Calibri", "Consolas", "Tahoma"], macos: ["Helvetica Neue", "Menlo", "Avenir", "Geneva"],
    linux: ["DejaVu Sans", "Liberation Sans", "Ubuntu", "Cantarell"]};
  const x = document.createElement("canvas").getContext("2d"), text = "mmmmmmmmmmlli1WQ@#";
  const w = f => { x.font = `32px ${f}`; return x.measureText(text).width; };
  const floors = {mono: w("monospace"), serif: w("serif")};
  const rendered = {};
  for (const [os, list] of Object.entries(MARKERS)) rendered[os] = list.filter(f => w(`"${f}", monospace`) === w(`"${f}", serif`));
  return {floors, valid: floors.mono !== floors.serif, rendered};
}
function webgl() {
  const gl = document.createElement("canvas").getContext("webgl");
  if (!gl) return null;
  const ext = gl.getExtension("WEBGL_debug_renderer_info");
  return {vendor: gl.getParameter(ext ? ext.UNMASKED_VENDOR_WEBGL : gl.VENDOR),
          renderer: gl.getParameter(ext ? ext.UNMASKED_RENDERER_WEBGL : gl.RENDERER)};
}
function canvasHash() {
  const c = document.createElement("canvas"); c.width = 220; c.height = 30;
  const x = c.getContext("2d");
  x.textBaseline = "top"; x.font = "16px Arial"; x.fillStyle = "#f60"; x.fillRect(100, 1, 62, 20);
  x.fillStyle = "#069"; x.fillText("Camoufox e2e, \u{1F603}", 2, 2);
  const s = c.toDataURL(); let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return h;
}
const voices = () => new Promise(ok => {
  const v = speechSynthesis.getVoices();
  if (v.length) return ok(v);
  speechSynthesis.onvoiceschanged = () => ok(speechSynthesis.getVoices());
  setTimeout(() => ok(speechSynthesis.getVoices()), 2000);
});
const reply = (target, send) => new Promise(ok => { target.onmessage = e => ok(e.data); send(); setTimeout(() => ok(null), 4000); });
(async () => {
  const r = {main: snap(), intl: Intl.DateTimeFormat().resolvedOptions().locale, tz: tzAgree(), webdriver: navigator.webdriver,
    screen: {w: screen.width, h: screen.height, aw: screen.availWidth, ah: screen.availHeight, iw: innerWidth, ih: innerHeight,
             ow: outerWidth, oh: outerHeight, dpr: devicePixelRatio},
    fonts: fonts(), webgl: webgl(), canvas: canvasHash(),
    voices: typeof speechSynthesis === "undefined" ? null : (await voices()).map(v => ({name: v.name, uri: v.voiceURI}))};
  const w = new Worker("/fp-worker.js");
  r.dedicated = await reply(w, () => w.postMessage(0));
  try { const s = new SharedWorker("/fp-worker.js"); r.shared = await reply(s.port, () => s.port.start()); }
  catch (e) { r.shared = "error: " + e.name; }
  try {
    await navigator.serviceWorker.register("/sw.js", {scope: "/"});
    const reg = await navigator.serviceWorker.ready;
    r.service = await reply(navigator.serviceWorker, () => reg.active.postMessage("snap"));
  } catch (e) { r.service = "error: " + e.name; }
  const out = document.getElementById("out");
  out.textContent = JSON.stringify(r); out.dataset.done = "1";
})();
</script>
```

<!-- file: e2e/web/pages/webrtc.html -->
```html
<!doctype html><meta charset="utf-8"><title>WebRTC</title><div id="out"></div>
<script>
(async () => {
  const stun = new URLSearchParams(location.search).get("stun");
  const pc = new RTCPeerConnection({iceServers: [{urls: `stun:${stun}`}]});
  const cands = [];
  let finished = false;
  function finish() {
    if (finished) return; finished = true;
    const out = document.getElementById("out");
    out.textContent = JSON.stringify({candidates: cands, sdp: pc.localDescription ? pc.localDescription.sdp : ""});
    out.dataset.done = "1";
  }
  pc.createDataChannel("d");
  pc.onicecandidate = e => { if (e.candidate) cands.push(e.candidate.candidate); else finish(); };
  await pc.setLocalDescription(await pc.createOffer());
  setTimeout(finish, 8000);
})();
</script>
```

---

### Task 3: Drivers (pkg, pw, ref, go) and conftest

**Files:**
- Create: `e2e/drivers/__init__.py`, `e2e/drivers/playwright_drivers.py`, `e2e/drivers/go.py`, `goapi/cmd/e2edriver/main.go`, `e2e/conftest.py`, `e2e/journeys/__init__.py`, `e2e/journeys/test_00_smoke.py`

**Interfaces:**
- Consumes: `Site`, `Proxy` and `Stun` from Task 2; `util` from Task 1.
- Produces: `drivers.make(name, binary) -> Driver`. `Driver.name` is a str.
  - `Driver.launch(os=None, headless=True, humanize=False, proxy=None, geoip=None, locale=None, webrtc_ip=None, prefs=None) -> Browser`
  - `Driver.close_all()`
  - `Browser.new_context() -> Ctx`, `Browser.close()`
  - `Ctx.new_page() -> Page`, `Ctx.cookies() -> list[dict(name, value, domain)]`, `Ctx.close()`
  - `Page.goto(url)`, `.eval(js)`, `.click(sel)`, `.hover(sel)`, `.type(sel, text)`, `.upload(sel, path)`, `.download(sel) -> bytes`, `.on_dialog(prompt: str)`
- Produces fixtures: `binary`, `site`, `http_proxy`, `socks_proxy`, `stun`, `drv`, `ref`.

- [ ] **Step 1: Write the failing smoke journey** `e2e/journeys/test_00_smoke.py` (below)
- [ ] **Step 2: Run** `cd e2e && python3 -m pytest journeys/test_00_smoke.py --binary $BIN -q`. Expect a fixture error.
- [ ] **Step 3: Write the drivers, the Go driver and conftest** (below)
- [ ] **Step 4: Run it again.** Expect three passes (`pkg`, `pw`, `go`), or a failure on `go` that is a real finding and gets recorded.
- [ ] **Step 5: Run** `cd goapi && go vet ./cmd/e2edriver`. Expect a clean result.
- [ ] **Step 6: Commit** `feat(e2e): one journey interface over the package, bare Playwright and goapi`

<!-- file: e2e/drivers/__init__.py -->
```python
"""One small interface over the three ways users drive Camoufox."""

from pathlib import Path


def make(name: str, binary: Path):
    if name == "pkg":
        from .playwright_drivers import PkgDriver
        return PkgDriver(binary)
    if name == "pw":
        from .playwright_drivers import PwDriver
        return PwDriver(binary)
    if name == "go":
        from .go import GoDriver
        return GoDriver(binary)
    raise ValueError(f"unknown driver {name!r}")
```

<!-- file: e2e/drivers/playwright_drivers.py -->
```python
"""The Playwright-based drivers: the camoufox package, bare Playwright, and the
reference Firefox that Playwright bundles (oracle B)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_PW = None


def playwright():
    """One sync Playwright per session: a second instance in the same thread fails."""
    global _PW
    if _PW is None:
        from playwright.sync_api import sync_playwright
        _PW = sync_playwright().start()
    return _PW


def stop_playwright() -> None:
    global _PW
    if _PW is not None:
        _PW.stop()
        _PW = None


class PwPage:
    def __init__(self, page) -> None:
        self.p = page

    def goto(self, url: str) -> None:
        self.p.goto(url, wait_until="load")

    def eval(self, js: str):
        return self.p.evaluate(js)

    def click(self, sel: str) -> None:
        self.p.click(sel)

    def hover(self, sel: str) -> None:
        self.p.hover(sel)

    def type(self, sel: str, text: str) -> None:
        self.p.locator(sel).press_sequentially(text)

    def upload(self, sel: str, path) -> None:
        self.p.set_input_files(sel, str(path))

    def download(self, sel: str) -> bytes:
        with self.p.expect_download() as d:
            self.p.click(sel)
        return Path(d.value.path()).read_bytes()

    def on_dialog(self, prompt: str) -> None:
        self.p.on("dialog", lambda d: d.accept(prompt) if d.type == "prompt" else d.accept())


class PwCtx:
    def __init__(self, ctx) -> None:
        self.c = ctx

    def new_page(self) -> PwPage:
        return PwPage(self.c.new_page())

    def cookies(self):
        return [{"name": c["name"], "value": c["value"], "domain": c["domain"]} for c in self.c.cookies()]

    def close(self) -> None:
        self.c.close()


class PwBrowser:
    def __init__(self, browser, new_context) -> None:
        self.b, self._new_context = browser, new_context

    def new_context(self) -> PwCtx:
        return PwCtx(self._new_context(self.b))

    def close(self) -> None:
        self.b.close()


class _Base:
    name = "?"

    def __init__(self, binary: Path) -> None:
        self.binary = binary
        self.browsers = []

    def close_all(self) -> None:
        for b in self.browsers:
            try:
                b.close()
            except Exception:
                pass
        self.browsers.clear()


class PkgDriver(_Base):
    """camoufox.sync_api: NewBrowser, then NewContext for each context, as documented."""

    name = "pkg"

    def launch(self, os=None, headless=True, humanize=False, proxy=None, geoip=None, locale=None,
               webrtc_ip=None, prefs=None) -> PwBrowser:
        from camoufox.sync_api import NewBrowser, NewContext

        kw = dict(executable_path=str(self.binary), headless=headless, os=os, humanize=humanize or None,
                  proxy=proxy, geoip=geoip, locale=locale, firefox_user_prefs=prefs,
                  config={"webrtc:ipv4": webrtc_ip} if webrtc_ip else None)
        browser = NewBrowser(playwright(), **{k: v for k, v in kw.items() if v is not None})
        b = PwBrowser(browser, lambda br: NewContext(br, os=os, webrtc_ip=webrtc_ip))
        self.browsers.append(b)
        return b


class PwDriver(_Base):
    """Bare Playwright: config from camoufox.utils.launch_options, launch by hand."""

    name = "pw"

    def launch(self, os=None, headless=True, humanize=False, proxy=None, geoip=None, locale=None,
               webrtc_ip=None, prefs=None) -> PwBrowser:
        from camoufox.utils import launch_options

        if headless == "virtual":
            pytest.skip("pw: no headless='virtual' (the Camoufox class owns the Xvfb)")
        kw = dict(executable_path=str(self.binary), headless=headless, os=os, humanize=humanize or None,
                  proxy=proxy, geoip=geoip, locale=locale, firefox_user_prefs=prefs,
                  config={"webrtc:ipv4": webrtc_ip} if webrtc_ip else None)
        opts = launch_options(**{k: v for k, v in kw.items() if v is not None})
        b = PwBrowser(playwright().firefox.launch(**opts), lambda br: br.new_context())
        self.browsers.append(b)
        return b


class RefDriver(_Base):
    """Playwright's own Firefox. Oracle B: compared on behaviour only, never on values."""

    name = "ref"

    def __init__(self) -> None:
        super().__init__(Path())
        self.version = None

    def launch(self, headless=True, **ignored) -> PwBrowser:
        try:
            browser = playwright().firefox.launch(headless=headless)
        except Exception as e:
            if "Executable doesn't exist" not in str(e):
                raise
            subprocess.run([sys.executable, "-m", "playwright", "install", "firefox"], check=True)
            browser = playwright().firefox.launch(headless=headless)
        if self.version is None:
            self.version = browser.version
            print(f"oracle-B: playwright-firefox {self.version}", flush=True)
        b = PwBrowser(browser, lambda br: br.new_context())
        self.browsers.append(b)
        return b
```

<!-- file: e2e/drivers/go.py -->
```python
"""goapi, driven through goapi/cmd/e2edriver over JSON lines."""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
EXE = REPO / ".ci-work" / ("e2edriver.exe" if os.name == "nt" else "e2edriver")
_built = False


def build() -> Path:
    global _built
    if not _built:
        if shutil.which("go") is None:
            pytest.skip("go: no Go toolchain on this machine")
        EXE.parent.mkdir(exist_ok=True)
        subprocess.run(["go", "build", "-o", str(EXE), "./cmd/e2edriver"], cwd=REPO / "goapi", check=True)
        _built = True
    return EXE


class GoDriver:
    name = "go"

    def __init__(self, binary: Path) -> None:
        self.binary = binary
        self.proc = None
        self.n = 0
        self.browsers = []

    def rpc(self, op: str, h: str = "", **args):
        if self.proc is None:
            self.proc = subprocess.Popen([str(build())], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        self.n += 1
        self.proc.stdin.write(json.dumps({"id": self.n, "op": op, "h": h, "args": args}) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("e2edriver exited")
        reply = json.loads(line)
        if reply.get("error"):
            raise RuntimeError(f"go {op}: {reply['error']}")
        return reply.get("result")

    def launch(self, os=None, headless=True, humanize=False, proxy=None, geoip=None, locale=None,
               webrtc_ip=None, prefs=None) -> "GoBrowser":
        for opt, value in (("humanize", humanize), ("geoip", geoip), ("locale", locale), ("webrtc_ip", webrtc_ip)):
            if value:
                pytest.skip(f"go: no {opt}")
        if headless == "virtual":
            pytest.skip("go: no headless='virtual'")
        h = self.rpc("launch", binary=str(self.binary), os=os or "", headless=headless, proxy=proxy, prefs=prefs or {})
        b = GoBrowser(self, h)
        self.browsers.append(b)
        return b

    def close_all(self) -> None:
        for b in self.browsers:
            try:
                b.close()
            except Exception:
                pass
        self.browsers.clear()
        if self.proc:
            self.proc.stdin.close()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None


class GoBrowser:
    def __init__(self, d: GoDriver, h: str) -> None:
        self.d, self.h = d, h

    def new_context(self) -> "GoCtx":
        return GoCtx(self.d, self.d.rpc("browser.new_context", self.h))

    def close(self) -> None:
        self.d.rpc("browser.close", self.h)


class GoCtx:
    def __init__(self, d: GoDriver, h: str) -> None:
        self.d, self.h = d, h

    def new_page(self) -> "GoPage":
        return GoPage(self.d, self.d.rpc("ctx.new_page", self.h), self.h)

    def cookies(self):
        return [{"name": c["name"], "value": c["value"], "domain": c["domain"]} for c in self.d.rpc("ctx.cookies", self.h) or []]

    def close(self) -> None:
        self.d.rpc("ctx.close", self.h)


class GoPage:
    def __init__(self, d: GoDriver, h: str, ctx: str) -> None:
        self.d, self.h, self.ctx = d, h, ctx

    def goto(self, url):
        self.d.rpc("page.goto", self.h, url=url)

    def eval(self, js):
        return self.d.rpc("page.eval", self.h, js=js)

    def click(self, sel):
        self.d.rpc("page.click", self.h, sel=sel)

    def hover(self, sel):
        self.d.rpc("page.hover", self.h, sel=sel)

    def type(self, sel, text):
        self.d.rpc("page.type", self.h, sel=sel, text=text)

    def upload(self, sel, path):
        self.d.rpc("page.upload", self.h, sel=sel, path=str(path))

    def download(self, sel) -> bytes:
        return base64.b64decode(self.d.rpc("page.download", self.h, sel=sel, ctx=self.ctx))

    def on_dialog(self, prompt):
        self.d.rpc("page.on_dialog", self.h, prompt=prompt)
```

<!-- file: goapi/cmd/e2edriver/main.go -->
```go
// Command e2edriver exposes goapi's public API over JSON lines on stdin and
// stdout, so the Python end-to-end suite (e2e/) can run its journeys through
// goapi as well as through the Python package. One request per line:
//
//	{"id":1,"op":"page.goto","h":"p3","args":{"url":"http://..."}}
//
// and one reply per line: {"id":1,"result":...} or {"id":1,"error":"..."}.
package main

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"sync"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
	"github.com/lang315/camoufox/goapi/pkg/proxy"
)

type request struct {
	ID   int             `json:"id"`
	Op   string          `json:"op"`
	H    string          `json:"h"`
	Args json.RawMessage `json:"args"`
}

type reply struct {
	ID     int    `json:"id"`
	Result any    `json:"result,omitempty"`
	Error  string `json:"error,omitempty"`
}

type args struct {
	Binary   string         `json:"binary"`
	OS       string         `json:"os"`
	Headless bool           `json:"headless"`
	Proxy    *proxy.Proxy   `json:"proxy"`
	Prefs    map[string]any `json:"prefs"`
	URL      string         `json:"url"`
	JS       string         `json:"js"`
	Sel      string         `json:"sel"`
	Text     string         `json:"text"`
	Path     string         `json:"path"`
	Ctx      string         `json:"ctx"`
	Prompt   string         `json:"prompt"`
}

type state struct {
	mu   sync.Mutex
	n    int
	objs map[string]any
}

func (s *state) put(prefix string, v any) string {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.n++
	h := fmt.Sprintf("%s%d", prefix, s.n)
	s.objs[h] = v
	return h
}

func (s *state) get(h string) any {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.objs[h]
}

func main() {
	st := &state{objs: map[string]any{}}
	in := bufio.NewScanner(os.Stdin)
	in.Buffer(make([]byte, 1<<20), 1<<26)
	out := json.NewEncoder(os.Stdout)
	for in.Scan() {
		var r request
		if err := json.Unmarshal(in.Bytes(), &r); err != nil {
			_ = out.Encode(reply{Error: err.Error()})
			continue
		}
		ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
		res, err := st.do(ctx, r)
		cancel()
		rep := reply{ID: r.ID, Result: res}
		if err != nil {
			rep.Error = err.Error()
		}
		_ = out.Encode(rep)
	}
}

func (s *state) page(h string) (*camoufox.Page, error) {
	p, ok := s.get(h).(*camoufox.Page)
	if !ok {
		return nil, fmt.Errorf("no page %q", h)
	}
	return p, nil
}

func (s *state) do(ctx context.Context, r request) (any, error) {
	var a args
	if len(r.Args) > 0 {
		if err := json.Unmarshal(r.Args, &a); err != nil {
			return nil, err
		}
	}
	switch r.Op {
	case "launch":
		opts := []camoufox.Option{camoufox.WithExecutablePath(a.Binary), camoufox.WithHeadless(a.Headless)}
		if a.OS != "" {
			opts = append(opts, camoufox.WithOS(a.OS))
		}
		if a.Proxy != nil {
			opts = append(opts, camoufox.WithProxy(*a.Proxy))
		}
		for k, v := range a.Prefs {
			opts = append(opts, camoufox.WithFirefoxUserPref(k, v))
		}
		// Launch ties the browser process to its context, so it must outlive this request.
		b, err := camoufox.Launch(context.Background(), opts...)
		if err != nil {
			return nil, err
		}
		return s.put("b", b), nil
	case "browser.close":
		return nil, s.get(r.H).(*camoufox.Browser).Close()
	case "browser.new_context":
		c, err := s.get(r.H).(*camoufox.Browser).NewContext(ctx)
		if err != nil {
			return nil, err
		}
		return s.put("c", c), nil
	case "ctx.new_page":
		p, err := s.get(r.H).(*camoufox.BrowserContext).NewPage(ctx)
		if err != nil {
			return nil, err
		}
		return s.put("p", p), nil
	case "ctx.cookies":
		return s.get(r.H).(*camoufox.BrowserContext).Cookies(ctx)
	case "ctx.close":
		return nil, s.get(r.H).(*camoufox.BrowserContext).Close(ctx)
	}

	p, err := s.page(r.H)
	if err != nil {
		return nil, err
	}
	switch r.Op {
	case "page.goto":
		return nil, p.Goto(ctx, a.URL)
	case "page.eval":
		return p.Evaluate(ctx, a.JS)
	case "page.click":
		return nil, p.Click(ctx, a.Sel)
	case "page.type":
		return nil, p.Type(ctx, a.Sel, a.Text)
	case "page.hover", "page.upload":
		el, err := p.QuerySelector(ctx, a.Sel)
		if err != nil {
			return nil, err
		}
		if el == nil {
			return nil, fmt.Errorf("no element %q", a.Sel)
		}
		if r.Op == "page.hover" {
			return nil, el.Hover(ctx)
		}
		return nil, el.SetInputFiles(ctx, []string{a.Path})
	case "page.download":
		bc := s.get(a.Ctx).(*camoufox.BrowserContext)
		dir, err := os.MkdirTemp("", "e2e-download")
		if err != nil {
			return nil, err
		}
		if err := bc.SetDownloadOptions(ctx, camoufox.DownloadOptions{Behavior: "saveToDisk", DownloadsDir: dir}); err != nil {
			return nil, err
		}
		got := make(chan *camoufox.Download, 1)
		// ponytail: the subscription is never removed; one per download call is fine for a test driver.
		bc.OnDownload(func(d *camoufox.Download) {
			select {
			case got <- d:
			default:
			}
		})
		if err := p.Click(ctx, a.Sel); err != nil {
			return nil, err
		}
		select {
		case d := <-got:
			if err := d.Wait(ctx); err != nil {
				return nil, err
			}
			return os.ReadFile(d.Path()) // []byte encodes as base64
		case <-ctx.Done():
			return nil, fmt.Errorf("no download started: %w", ctx.Err())
		}
	case "page.on_dialog":
		prompt := a.Prompt
		p.OnDialog(func(d *camoufox.Dialog) {
			// Answer off the event goroutine: Accept is itself a protocol call.
			go func() {
				text := ""
				if d.Type == "prompt" {
					text = prompt
				}
				_ = d.Accept(context.Background(), text)
			}()
		})
		return nil, nil
	}
	return nil, fmt.Errorf("unknown op %q", r.Op)
}
```

<!-- file: e2e/conftest.py -->
```python
"""Fixtures for the end-to-end user-journey suite.

Design: docs/superpowers/specs/2026-09-24-e2e-user-journeys-design.md
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import urllib.request
import zipfile
from pathlib import Path

import pytest

from util import build_id, find_binary

E2E = Path(__file__).resolve().parent
REPO = E2E.parent
WORK = REPO / ".ci-work" / "e2e"
RELEASE_REPO = "lang315/camoufox"
PLATFORM_ASSET = {("Darwin", "arm64"): "mac.arm64", ("Darwin", "x86_64"): "mac.x86_64",
                  ("Windows", "AMD64"): "win.x86_64", ("Linux", "x86_64"): "lin.x86_64",
                  ("Linux", "aarch64"): "lin.arm64"}


def pytest_addoption(parser):
    g = parser.getgroup("e2e")
    g.addoption("--binary", help="Camoufox executable to test")
    g.addoption("--zip", help="a release or build zip; unpacked and tested")
    g.addoption("--release", help=f"a {RELEASE_REPO} release tag; its zip for this platform is downloaded")
    g.addoption("--drivers", default="pkg,pw,go", help="comma-separated: pkg,pw,go")
    g.addoption("--soak-seconds", type=float, default=600)


def pytest_generate_tests(metafunc):
    if "drv" in metafunc.fixturenames:
        metafunc.parametrize("drv", metafunc.config.getoption("--drivers").split(","), indirect=True)


def _unpack(zp: Path) -> Path:
    dest = WORK / "unpacked" / zp.stem
    if not dest.exists():
        dest.mkdir(parents=True)
        if os.name == "nt":
            zipfile.ZipFile(zp).extractall(dest)
        else:  # keeps the executable bits zipfile would drop
            subprocess.run(["unzip", "-q", "-o", str(zp), "-d", str(dest)], check=True)
    return find_binary(dest)


def _fetch_release(tag: str) -> Path:
    plat = PLATFORM_ASSET[(platform.system(), platform.machine())]
    with urllib.request.urlopen(f"https://api.github.com/repos/{RELEASE_REPO}/releases/tags/{tag}", timeout=30) as r:
        rel = json.load(r)
    asset = next(a for a in rel["assets"] if a["name"].endswith(f"-{plat}.zip"))
    zp = WORK / "release" / tag / asset["name"]
    zp.parent.mkdir(parents=True, exist_ok=True)
    if not zp.exists():
        for attempt in range(3):
            try:
                urllib.request.urlretrieve(asset["browser_download_url"], zp)
                break
            except OSError:
                if attempt == 2:
                    raise
    digest = hashlib.sha256(zp.read_bytes()).hexdigest()
    if asset.get("digest"):
        assert asset["digest"] == f"sha256:{digest}", f"{asset['name']}: downloaded {digest}, release says {asset['digest']}"
    return zp


@pytest.fixture(scope="session")
def binary(pytestconfig) -> Path:
    zp = None
    if pytestconfig.getoption("--release"):
        zp = _fetch_release(pytestconfig.getoption("--release"))
    elif pytestconfig.getoption("--zip"):
        zp = Path(pytestconfig.getoption("--zip")).resolve()
    if zp:
        path = _unpack(zp)
    else:
        given = pytestconfig.getoption("--binary") or os.environ.get("CAMOUFOX_EXECUTABLE_PATH")
        if not given:
            pytest.exit("no browser: pass --binary, --zip or --release, or set CAMOUFOX_EXECUTABLE_PATH", 2)
        path = Path(given).resolve()
    if not path.exists():
        pytest.exit(f"browser not found: {path}", 2)
    line = f"e2e binary: {path}  BuildID={build_id(path)}  host={platform.system()} {platform.machine()}"
    if zp:
        line += f"  zip={zp.name} sha256={hashlib.sha256(zp.read_bytes()).hexdigest()}"
    pytestconfig.pluginmanager.get_plugin("terminalreporter").write_line(line)
    return path


@pytest.fixture(scope="session")
def stun():
    from web.stun import Stun
    s = Stun()
    yield s
    s.stop()


@pytest.fixture(scope="session")
def site(stun):
    from web.server import Site
    s = Site()
    s.stun_port = stun.port
    s.start()
    yield s
    s.stop()


@pytest.fixture(scope="session")
def http_proxy():
    from web.proxy import Proxy
    p = Proxy("http", auth=("e2e", "pw-http"))
    yield p
    p.stop()


@pytest.fixture(scope="session")
def socks_proxy():
    from web.proxy import Proxy
    p = Proxy("socks5", auth=("e2e", "pw-socks"))
    yield p
    p.stop()


@pytest.fixture
def drv(request, binary):
    from drivers import make
    d = make(request.param, binary)
    yield d
    d.close_all()


@pytest.fixture(scope="session")
def ref():
    from drivers.playwright_drivers import RefDriver
    d = RefDriver()
    yield d
    d.close_all()


def pytest_sessionfinish(session):
    from drivers.playwright_drivers import stop_playwright
    stop_playwright()
```

<!-- file: e2e/journeys/__init__.py -->
```python
```

<!-- file: e2e/journeys/test_00_smoke.py -->
```python
"""The smallest journey: launch, open a page, read it back. If this fails, the driver is the problem."""


def test_open_a_page(drv, site):
    b = drv.launch()
    page = b.new_context().new_page()
    page.goto(site.url("/login"))
    assert page.eval("document.title") == "Sign in"
```

---

### Task 4: Journeys 1 and 2 (install and launch, fingerprint coherence)

**Files:** Create `e2e/journeys/test_01_install_launch.py` and `e2e/journeys/test_02_fingerprint.py`.

**Interfaces:** Consumes the fixtures, `Checks`, `wait_out`, `wait_gone`, `coherence.evaluate` and `docs.cite`.

- [ ] **Step 1: Write both files** (below). A journey is a test against the browser, so "failing first" means running it and reading each red. Every red is either a finding, which goes in the PR body, or a test bug that gets fixed. A test bug is only called one once a control shows it.
- [ ] **Step 2: Run** `cd e2e && python3 -m pytest journeys/test_01_install_launch.py journeys/test_02_fingerprint.py --binary $BIN -v -s`
- [ ] **Step 3: Triage every red** into finding or test bug, with the evidence.
- [ ] **Step 4: Commit** `feat(e2e): install/launch and fingerprint-coherence journeys`

<!-- file: e2e/journeys/test_01_install_launch.py -->
```python
"""Journey 1: install the package the way a user does, launch in every display
mode, and leave nothing running after close."""

import os
import platform
import subprocess
import sys
import textwrap
import time
import venv
from pathlib import Path

import pytest

from oracle.docs import cite
from util import Checks, wait_gone

REPO = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("mode", [True, False, "virtual"], ids=["headless", "headful", "virtual"])
def test_launch_modes(drv, site, binary, mode):
    if mode == "virtual":
        print(cite("virtual"))
        if platform.system() != "Linux":
            pytest.skip("headless='virtual' is documented for Linux only")
    check = Checks()
    t0 = time.monotonic()
    b = drv.launch(headless=mode)
    page = b.new_context().new_page()
    page.goto(site.url("/login"))
    print(f"{drv.name} headless={mode!r}: launch + first page {time.monotonic() - t0:.1f}s")
    check(page.eval("document.title") == "Sign in", "page title read back")
    b.close()
    left = wait_gone(binary)
    check(not left, f"no browser process left 15 s after close (left: {left})")
    check.done()


@pytest.mark.timeout(900)
def test_fresh_venv_install(tmp_path, site, binary):
    venv.create(tmp_path / "venv", with_pip=True)
    py = tmp_path / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run([str(py), "-m", "pip", "install", "-q", str(REPO / "pythonlib")], check=True, timeout=600)
    script = textwrap.dedent(f"""
        from camoufox.sync_api import Camoufox
        with Camoufox(executable_path={str(binary)!r}, headless=True) as browser:
            page = browser.new_page()
            page.goto({site.url("/login")!r})
            print("TITLE=" + page.title())
    """)
    r = subprocess.run([str(py), "-c", script], capture_output=True, text=True, timeout=180)
    assert "TITLE=Sign in" in r.stdout, f"exit {r.returncode}\nstdout:\n{r.stdout}\nstderr:\n{r.stderr[-4000:]}"
```

<!-- file: e2e/journeys/test_02_fingerprint.py -->
```python
"""Journey 2: what an ordinary page reads agrees with itself and with what the
server received (oracle C), for each OS a user can ask for (oracle A)."""

import pytest

from oracle import coherence
from oracle.docs import cite
from util import Checks, wait_out


def measure(drv, site, **launch):
    b = drv.launch(**launch)
    page = b.new_context().new_page()
    page.goto(site.url("/fp"))
    fp = wait_out(page)
    req = site.seen("/fp")[-1]
    b.close()
    return fp, req


def report(check, fp, req, os_name):
    for name, ok, detail, red in coherence.evaluate(fp, req, os_name):
        if ok is None:
            print(f"n/a  {name}: {detail}")
            continue
        check(ok, f"{name}: {detail}")
        check(red, f"{name}: its negative control went red (else VACUOUS)")


@pytest.mark.parametrize("os_name", ["windows", "macos", "linux"])
def test_fingerprint_is_coherent(drv, site, os_name):
    print(cite("os_option"), cite("webdriver"))
    check = Checks()
    fp, req = measure(drv, site, os=os_name)
    report(check, fp, req, os_name)
    check.done()


def test_locale_option_reaches_navigator_and_intl(drv, site):
    print(cite("locale"))
    check = Checks()
    fp, req = measure(drv, site, os="windows", locale="de-DE")
    check(fp["main"]["language"] == "de-DE", f"navigator.language={fp['main']['language']!r}")
    check(fp["intl"].startswith("de"), f"Intl locale={fp['intl']!r}")
    report(check, fp, req, "windows")
    check.done()
```

---

### Task 5: Journeys 3 and 4 (network, automation)

**Files:** Create `e2e/journeys/test_03_network.py` and `e2e/journeys/test_04_automation.py`.

- [ ] **Step 1: Write both files** (below)
- [ ] **Step 2: Run** `cd e2e && python3 -m pytest journeys/test_03_network.py journeys/test_04_automation.py --binary $BIN -v -s`
- [ ] **Step 3: Triage every red** into finding or test bug, with the evidence.
- [ ] **Step 4: Commit** `feat(e2e): proxy, geoip, WebRTC and automation journeys`

<!-- file: e2e/journeys/test_03_network.py -->
```python
"""Journey 3: proxies, geoip and WebRTC, as a user configures them."""

import pytest

from oracle.docs import cite
from util import Checks, header, lan_ips, wait_out

GEOIP_IP = "8.8.8.8"
SPOOFED_WEBRTC_IP = "203.0.113.7"  # TEST-NET-3: cannot be anyone's real address


def via_proxy(drv, site, proxy):
    try:
        b = drv.launch(os="windows", proxy=proxy.playwright())
    except Exception as e:
        if "socks" in str(e).lower() and "auth" in str(e).lower():
            pytest.skip(f"{drv.name}: SOCKS5 authentication refused by the client: {e}")
        raise
    page = b.new_context().new_page()
    page.goto(f"http://e2e.test:{site.port1}/fp")  # .test resolves only inside the proxy
    fp = wait_out(page)
    b.close()
    return fp


@pytest.mark.parametrize("kind", ["http", "socks5"])
def test_proxy_with_auth(drv, site, http_proxy, socks_proxy, kind):
    proxy = http_proxy if kind == "http" else socks_proxy
    check = Checks()
    fp = via_proxy(drv, site, proxy)
    req = site.seen("/fp")[-1]
    check("e2e.test" in proxy.hosts, f"the {kind} proxy carried the page (hosts seen: {sorted(set(proxy.hosts))})")
    check(fp["main"]["ua"] == header(req, "User-Agent"), "UA through the proxy matches the header that arrived")
    check.done()


def test_geoip_sets_timezone_and_locale(drv, site):
    print(cite("geoip"))
    pytest.importorskip("geoip2", reason="camoufox[geoip] is not installed")
    from camoufox.geolocation import get_geolocation
    try:
        geo = get_geolocation(GEOIP_IP)
    except Exception as e:
        pytest.skip(f"geoip database unavailable: {e}")
    check = Checks()
    b = drv.launch(os="windows", geoip=GEOIP_IP)
    page = b.new_context().new_page()
    page.goto(site.url("/fp"))
    fp = wait_out(page)
    b.close()
    check(fp["tz"]["tz"] == geo.timezone, f"timezone {fp['tz']['tz']!r}; database says {geo.timezone!r}")
    if geo.locale.region:
        check(fp["main"]["language"].endswith(geo.locale.region),
              f"navigator.language {fp['main']['language']!r} is in region {geo.locale.region!r}")
    check.done()


def test_webrtc_does_not_reveal_lan_address(drv, site, stun):
    print(cite("webrtc"))
    lan = lan_ips()
    if not lan:
        pytest.skip("this host has no non-loopback IPv4 address to leak")
    check = Checks()
    b = drv.launch(os="windows", webrtc_ip=SPOOFED_WEBRTC_IP)
    page = b.new_context().new_page()
    page.goto(site.url(f"/webrtc?stun={sorted(lan)[0]}:{stun.port}"))
    got = wait_out(page, 20)
    b.close()
    text = " ".join(got["candidates"]) + got["sdp"]
    check(stun.seen, f"the STUN server was asked (non-vacuous); {len(got['candidates'])} candidates")
    check(not [ip for ip in lan if ip in text], f"no LAN address {sorted(lan)} in candidates or SDP")
    check(SPOOFED_WEBRTC_IP in text, f"the configured WebRTC IP appears: {got['candidates']}")
    check.done()
```

<!-- file: e2e/journeys/test_04_automation.py -->
```python
"""Journey 4: the things a scraper does all day: sign in, browse an SPA,
upload, download, cross-origin frames, popups and dialogs."""

import hashlib
import json
from urllib.parse import parse_qs

import pytest

from oracle.docs import cite
from util import Checks, wait_for, wait_out
from web.server import DOWNLOAD_SHA


def posts(site, path):
    return [r for r in site.seen(path) if r["method"] == "POST"]


@pytest.mark.parametrize("humanize", [False, True], ids=["plain", "humanize"])
def test_sign_in_and_shop(drv, site, humanize):
    print(cite("trusted_input"), cite("humanize") if humanize else "")
    check = Checks()
    b = drv.launch(humanize=humanize)
    ctx = b.new_context()
    page = ctx.new_page()

    page.goto(site.url("/login"))
    before = len(posts(site, "/login"))
    page.click("#go")
    check("required" in page.eval("document.getElementById('err').textContent"), "empty form stopped by validation")
    check(len(posts(site, "/login")) == before, "nothing was posted")

    page.type("#user", "alice")
    page.type("#pass", "s3cret")
    page.click("#go")
    wait_for(page, "location.pathname === '/account'")
    check(page.eval("document.getElementById('welcome').textContent") == "Welcome alice", "signed in")
    trusted = json.loads(parse_qs(posts(site, "/login")[-1]["body"].decode())["trusted"][0])
    check(trusted["n"] > 0 and trusted["all"], f"every input event the page saw was isTrusted ({trusted})")
    check(any(c["name"] == "session" for c in ctx.cookies()), "session cookie stored in the context")

    carts = len(site.seen("/shop/cart"))
    page.goto(site.url("/shop"))
    page.hover("#menu")
    check(page.eval("!document.getElementById('cart-link').hidden"), "hover opened the menu")
    page.eval("window.scrollTo(0, document.body.scrollHeight)")
    wait_for(page, "!!document.querySelector('.add[data-id=\"15\"]')")
    page.click('.add[data-id="15"]')
    page.click("#cart-link")
    wait_for(page, "location.pathname === '/shop/cart'")
    check("Item 15" in page.eval("document.getElementById('cart').textContent"), "the item is in the cart")
    check(len(site.seen("/shop/cart")) == carts, "the SPA route change made no request")
    b.close()
    check.done()


def test_upload_and_download(drv, site, tmp_path):
    check = Checks()
    f = tmp_path / "hello.txt"
    f.write_bytes(b"e2e upload " * 1000)
    b = drv.launch()
    page = b.new_context().new_page()
    page.goto(site.url("/upload"))
    page.upload("#file", f)
    page.click("#send")
    got = wait_out(page)
    check(got == [{"name": "hello.txt", "sha256": hashlib.sha256(f.read_bytes()).hexdigest()}], f"server received {got}")
    page.goto(site.url("/download"))
    data = page.download("#dl")
    check(hashlib.sha256(data).hexdigest() == DOWNLOAD_SHA, f"downloaded {len(data)} bytes with the served hash")
    b.close()
    check.done()


def frames(driver, site):
    b = driver.launch(headless=True)
    page = b.new_context().new_page()
    page.on_dialog("e2e")
    page.goto(site.url("/frames"))
    page.click("#pop")
    page.click("#dialogs")
    got = wait_out(page)
    b.close()
    return got


def test_frames_popups_and_dialogs_match_reference(drv, ref, site):
    check = Checks()
    got, want = frames(drv, site), frames(ref, site)
    print(f"camoufox: {got}\nreference: {want}")
    check(got == want, "same outcome as Playwright's Firefox (oracle B)")
    check(got["child"]["origin"] == site.url2("").rstrip("/"), "the child frame is cross-origin")
    check(got["dialogs"] == {"alert": True, "confirm": True, "prompt": "e2e"}, "dialogs answered as asked")
    check.done()


def test_evaluate_is_invisible_to_the_page(drv, site):
    print(cite("isolated_eval"))
    check = Checks()
    b = drv.launch()
    page = b.new_context().new_page()
    page.goto(site.url("/"))
    page.eval("window.__e2e_probe = 1; document.documentElement.dataset.fromEval = '1'")
    page.click("#peek")
    got = wait_out(page)
    check(got["attr"] == "1", "control: the evaluate ran in this document (it changed the DOM)")
    check(got["probe"] == "undefined", f"the page cannot see the evaluate's global (typeof = {got['probe']!r})")
    b.close()
    check.done()
```

---

### Task 6: Journeys 5, 6 and 8 (contexts, web APIs, lifecycle)

**Files:** Create `e2e/journeys/test_05_contexts.py`, `e2e/journeys/test_06_web_apis.py` and `e2e/journeys/test_08_lifecycle.py`.

- [ ] **Step 1: Write the three files** (below)
- [ ] **Step 2: Run** `cd e2e && python3 -m pytest journeys/test_05_contexts.py journeys/test_06_web_apis.py journeys/test_08_lifecycle.py --binary $BIN --soak-seconds 60 -v -s`
- [ ] **Step 3: Triage every red** into finding or test bug, with the evidence.
- [ ] **Step 4: Commit** `feat(e2e): context isolation, web APIs against the reference, lifecycle`

<!-- file: e2e/journeys/test_05_contexts.py -->
```python
"""Journey 5: contexts and browsers keep users apart."""

from oracle.docs import cite
from util import Checks, wait_for, wait_out


def sign_in(page, site):
    page.goto(site.url("/login"))
    page.type("#user", "alice")
    page.type("#pass", "s3cret")
    page.click("#go")
    wait_for(page, "location.pathname === '/account'")


def fp_of(page, site):
    page.goto(site.url("/fp"))
    return wait_out(page)


def identity(fp):
    return (fp["canvas"], fp["main"]["ua"], fp["screen"]["w"], fp["screen"]["h"], str(fp.get("webgl")))


def test_two_contexts_share_nothing(drv, site):
    check = Checks()
    b = drv.launch(os="windows")
    a, c = b.new_context(), b.new_context()
    pa, pc = a.new_page(), c.new_page()
    sign_in(pa, site)
    pa.eval("localStorage.setItem('owner', 'A')")
    pc.goto(site.url("/account"))
    check(pc.eval("location.pathname") == "/login", "the second context is signed out")
    check(pc.eval("localStorage.getItem('owner')") is None, "localStorage is not shared")
    check(not [k for k in c.cookies() if k["name"] == "session"], "no session cookie in the second context")
    if drv.name == "pkg":  # the only entry point with a documented per-context identity
        print(cite("unique_context"))
        fa, fc = fp_of(pa, site), fp_of(pc, site)
        check(identity(fa) != identity(fc), "the two contexts have different fingerprints")
        pa2 = a.new_page()
        check(identity(fp_of(pa2, site)) == identity(fa), "two pages of one context agree")
    b.close()
    check.done()


def test_two_browsers_at_once(drv, site):
    check = Checks()
    b1, b2 = drv.launch(), drv.launch()
    p1, p2 = b1.new_context().new_page(), b2.new_context().new_page()
    sign_in(p1, site)
    p2.goto(site.url("/account"))
    check(p2.eval("location.pathname") == "/login", "the second browser is signed out")
    f1, f2 = fp_of(p1, site), fp_of(p2, site)
    check(identity(f1) != identity(f2), f"two launches differ in fingerprint ({identity(f1)[:2]} vs {identity(f2)[:2]})")
    b1.close()
    b2.close()
    check.done()
```

<!-- file: e2e/journeys/test_06_web_apis.py -->
```python
"""Journey 6: ordinary web APIs still work: the same outcome as Playwright's own
Firefox (oracle B). Both run headful: headless Firefox has no GL context."""

import pytest

from util import Checks, wait_out


def run_apps(driver, site):
    b = driver.launch(headless=False)
    page = b.new_context().new_page()
    page.goto(site.url("/apps"))
    page.click("#clip")
    got = wait_out(page, 90)
    b.close()
    return got


@pytest.fixture(scope="module")
def reference(ref, site):
    return run_apps(ref, site)


def test_web_apis_behave_like_the_reference(drv, site, reference):
    check = Checks()
    got = run_apps(drv, site)
    for api in sorted(reference):
        check(got.get(api) == reference[api], f"{api}: camoufox={got.get(api)!r} reference={reference[api]!r}")
    # Absolute, with an in-page control: drawn canvas vs a blank one, cleared GL vs its clear colour.
    check(got["canvas"] is True, "canvas draws")
    check(got["webgl"] is True, "WebGL renders")
    check.done()
```

<!-- file: e2e/journeys/test_08_lifecycle.py -->
```python
"""Journey 8: long sessions, many contexts, and a browser that dies under you."""

import time

import psutil
import pytest

from util import browser_procs, rss_mb

pytestmark = pytest.mark.slow
PAGES = ["/login", "/shop", "/upload", "/download", "/fp"]


def test_fifty_contexts_in_a_row(drv, site):
    b = drv.launch()
    for i in range(50):
        c = b.new_context()
        p = c.new_page()
        p.goto(site.url("/login"))
        assert p.eval("document.title") == "Sign in", f"context {i}"
        c.close()
    b.close()


@pytest.mark.timeout(0)
def test_soak(drv, site, binary, pytestconfig):
    seconds = pytestconfig.getoption("--soak-seconds")
    b = drv.launch()
    p = b.new_context().new_page()
    t0, n, rss = time.monotonic(), 0, []
    while time.monotonic() - t0 < seconds:
        for path in PAGES:
            p.goto(site.url(path))
            n += 1
        if n % 50 == 0:
            rss.append(rss_mb(binary))
    assert p.eval("document.title"), "the page still answers at the end"
    print(f"soak {drv.name}: {n} navigations in {seconds:.0f}s; browser RSS MB over time {rss}")
    b.close()


def test_killed_browser_then_relaunch(drv, site, binary):
    b = drv.launch()
    p = b.new_context().new_page()
    p.goto(site.url("/login"))
    procs = browser_procs(binary)
    assert procs, "control: found the running browser's processes"
    for proc in procs:
        try:
            proc.kill()
        except psutil.Error:
            pass
    with pytest.raises(Exception):
        p.goto(site.url("/shop"))
    b2 = drv.launch()
    p2 = b2.new_context().new_page()
    p2.goto(site.url("/login"))
    assert p2.eval("document.title") == "Sign in", "a fresh launch works after the crash"
    b2.close()
```

---

### Task 7: Journey 7 (real sites, `live`)

**Files:** Create `e2e/live/__init__.py` and `e2e/live/test_live_sites.py`.

- [ ] **Step 1: Write the file** (below)
- [ ] **Step 2: Run** `cd e2e && python3 -m pytest live -m live --binary $BIN --drivers pkg -v -s`
- [ ] **Step 3: Record** the aggregate lines for the PR body. No per-vector detail goes in.
- [ ] **Step 4: Commit** `feat(e2e): live-site journey (dispatch only, aggregates only)`

<!-- file: e2e/live/__init__.py -->
```python
```

<!-- file: e2e/live/test_live_sites.py -->
```python
"""Journey 7: real public sites. Never on the PR gate (marker `live`).

Detector pages print an aggregate only: a grade, or a count and a total. This
repository is public, and per-vector detail stays out of it, the same rule
ci/run_sundial.py follows. A network failure is a SKIP, never a PASS or a FAIL.
"""

import re
import time

import pytest

from drivers import make

pytestmark = pytest.mark.live
NETWORK = ("NS_ERROR_UNKNOWN_HOST", "NS_ERROR_NET", "NS_ERROR_CONNECTION_REFUSED", "NS_ERROR_PROXY", "Timeout")


@pytest.fixture
def page(binary):
    d = make("pkg", binary)
    b = d.launch(headless=False)
    yield b.new_context().new_page()
    d.close_all()


def goto(page, url):
    try:
        page.goto(url)
    except Exception as e:
        if any(n in str(e) for n in NETWORK):
            pytest.skip(f"network: {str(e)[:200]}")
        raise


def text(page) -> str:
    return page.eval("document.body ? document.body.innerText : ''")


def poll(page, pattern, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        m = re.search(pattern, text(page), re.I)
        if m:
            return m
        time.sleep(1)
    return None


def test_sannysoft(page):
    goto(page, "https://bot.sannysoft.com/")
    time.sleep(5)
    c = page.eval("({passed: document.querySelectorAll('.passed').length, failed: document.querySelectorAll('.failed').length})")
    print(f"sannysoft: {c['passed']} passed / {c['passed'] + c['failed']} total")
    assert c["passed"] + c["failed"] > 0, "the page produced no results"


def test_creepjs(page):
    goto(page, "https://abrahamjuliot.github.io/creepjs/")
    m = poll(page, r"(\d+)% like headless", 30)
    print(f"creepjs: {m.group(0) if m else 'no headless score found'}")
    assert m, "no headless score on the page"


def test_browserscan(page):
    goto(page, "https://www.browserscan.net/")
    m = poll(page, r"authenticity[^0-9]{0,40}(\d+(?:\.\d+)?)\s*%", 40)
    print(f"browserscan: authenticity {m.group(1) + '%' if m else 'not found'}")
    assert m, "no authenticity score on the page"


def test_pixelscan(page):
    goto(page, "https://pixelscan.net/")
    m = poll(page, r"\b(inconsistent|consistent)\b", 40)
    print(f"pixelscan: {m.group(1) if m else 'no verdict found'}")
    assert m, "no verdict on the page"


def test_cloudflare_challenge(page):
    goto(page, "https://www.scrapingcourse.com/cloudflare-challenge")
    assert poll(page, r"You bypassed the Cloudflare challenge", 40), "the Cloudflare challenge was not passed"


def test_google_search_not_blocked(page):
    goto(page, "https://www.google.com/search?q=camoufox+browser")
    time.sleep(3)
    url, body = page.eval("location.href"), text(page)
    assert "/sorry/" not in url and "unusual traffic" not in body.lower(), f"blocked: {url}"


def test_youtube_loads(page):
    goto(page, "https://www.youtube.com/")
    assert "YouTube" in page.eval("document.title")
```

---

### Task 8: CI (PR gate job, dispatch workflow, runner)

**Files:**
- Create: `ci/run_e2e.py`, `.github/workflows/e2e.yml`
- Modify: `.github/workflows/tests.yml`. Add an `e2e` job after `native`; add it to `summary` needs, `required` and `gate` needs.
- Modify: `ci/README.md`. Add the `e2e` row to the tier diagram.

- [ ] **Step 1: Write `ci/run_e2e.py`** (below). Run `python3 -m ci.run_e2e --binary $BIN -- --drivers pkg -k smoke`. Expect `.ci-work/results/e2e.json` with status pass.
- [ ] **Step 2: Add the `tests.yml` job and the `e2e.yml` workflow** (below). Run `python3 -m pytest ci/tests -q` (the pipeline self-tests). Expect a pass.
- [ ] **Step 3: Commit** `ci(e2e): run the journeys on every PR, and on three OSes by dispatch`

<!-- file: ci/run_e2e.py -->
```python
#!/usr/bin/env python3
"""End-to-end user journeys (e2e/): the browser driven the way users drive it.

Run:
    python3 -m ci.run_e2e --binary path/to/camoufox-bin [-- extra pytest args]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from . import results
from ._pytest import built_binary, parse_junit, run_pytest
from ._util import REPO_ROOT, RESULTS_DIR, WORK_DIR


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    extra = argv[argv.index("--") + 1:] if "--" in argv else []
    argv = argv[: argv.index("--")] if "--" in argv else argv
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument("--timeout", type=int, default=5400)
    args = parser.parse_args(argv)

    result = results.GateResult(gate="e2e")
    binary = (args.binary or built_binary()).resolve()
    if not binary.exists():
        result.note(f"no browser at {binary}; a suite that did not run has not passed")
        result.finish(results.ERROR).save(args.results_dir)
        return 1
    result.metrics["binary"] = str(binary)

    junit = WORK_DIR / "junit-e2e.xml"
    proc = run_pytest(
        cwd=REPO_ROOT / "e2e",
        python=Path(sys.executable),
        args=["--binary", str(binary), *extra],
        junit=junit,
        timeout=args.timeout,
        per_test_timeout=900,
    )
    outcomes = parse_junit(junit)
    if not outcomes:
        result.note(f"pytest exited {proc.code} with no junit output; the suite did not run")
        result.finish(results.ERROR).save(args.results_dir)
        return 1
    for tid, outcome in outcomes.items():
        result.record(tid, outcome)
    tally = result.tally()
    result.artifacts.append(junit.name)
    result.metrics["exit_code"] = proc.code
    result.note(f"{tally.get('pass', 0)} passed, {tally.get('fail', 0)} failed, {tally.get('error', 0)} errored, "
                f"{tally.get('skip', 0)} skipped ({tally.get('total', 0)} collected)")
    status = results.PASS if tally.get("fail", 0) + tally.get("error", 0) == 0 else results.FAIL
    result.finish(status).save(args.results_dir)
    return 0 if status == results.PASS else 1


if __name__ == "__main__":
    sys.exit(main())
```

The `tests.yml` job, inserted after `native`:

```yaml
  e2e:
    name: End-to-end user journeys
    needs: [resolve, build, fetch-browser, patch-guards]
    if: always() && needs.patch-guards.result == 'success'
    runs-on: ubuntu-24.04
    timeout-minutes: 120
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ inputs.ref || github.ref }}
      - uses: ./.github/actions/prepare-browser
        with:
          python-version: ${{ env.PYTHON_VERSION }}
      - uses: actions/setup-go@v5
        with:
          go-version-file: goapi/go.mod
          cache-dependency-path: goapi/go.sum
      - run: pip install -e 'pythonlib[geoip]'
      # Oracle B: the journeys compare behaviour with Playwright's own Firefox.
      - run: python3 -m playwright install --with-deps firefox
      - name: Run
        # 200 s of soak per driver is the spec's ten minutes across the three.
        run: xvfb-run -a python3 -m ci.run_e2e --binary "$CAMOUFOX_BINARY" -- --soak-seconds 200
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: results-e2e
          path: .ci-work/results/
          include-hidden-files: true
          if-no-files-found: warn
```

Also add `e2e` to `summary.needs`, `e2e` to `required=` in the Summarize step, and `e2e` to `gate.needs`.

<!-- file: .github/workflows/e2e.yml -->
```yaml
# End-to-end user journeys on the three desktop OSes, against a build or a
# release. Dispatch only: macOS and Windows runners cost more minutes, and a
# Linux result is no evidence about either (CLAUDE.md lessons 3 and 8).
name: e2e (three OSes)

on:
  workflow_dispatch:
    inputs:
      release:
        description: "Fork release tag to test (e.g. v152.0.4-beta.31-fork.1)"
        required: false
      run_id:
        description: "Or: a build.yml run id holding CamoufoxBuilds-<target> artifacts"
        required: false
      live:
        description: "Also run the real-site journey"
        type: boolean
        default: false
      soak_seconds:
        description: "Soak length per driver"
        default: "200"

permissions:
  contents: read
  actions: read

jobs:
  e2e:
    name: e2e (${{ matrix.target }})
    strategy:
      fail-fast: false
      matrix:
        include:
          - { os: ubuntu-24.04, target: linux-x86_64 }
          - { os: macos-26, target: macos-arm64 }
          - { os: windows-2025, target: windows-x86_64 }
    runs-on: ${{ matrix.os }}
    timeout-minutes: 150
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - uses: actions/setup-go@v5
        with:
          go-version-file: goapi/go.mod
          cache-dependency-path: goapi/go.sum
      - name: Linux runtime libraries
        if: runner.os == 'Linux'
        run: |
          sudo apt-get update -qq
          sudo apt-get install -y --no-install-recommends xvfb libgtk-3-0 libasound2t64 libdbus-glib-1-2 \
            libx11-xcb1 libxcb-shm0 libxcomposite1 libxcursor1 libxdamage1 libxfixes3 libxi6 libxrandr2 libxtst6 libpci3
      - run: pip install -r ci/requirements.txt -e "pythonlib[geoip]"
      - run: python -m playwright install firefox
      - name: Which browser
        shell: bash
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          if [ -n "${{ inputs.run_id }}" ]; then
            gh run download "${{ inputs.run_id }}" --repo "${{ github.repository }}" \
              -n "CamoufoxBuilds-${{ matrix.target }}" -D .ci-work/artifact
            zip="$(ls .ci-work/artifact/*.zip | head -1)"
            echo "E2E_BROWSER=--zip $zip" >> "$GITHUB_ENV"
          elif [ -n "${{ inputs.release }}" ]; then
            echo "E2E_BROWSER=--release ${{ inputs.release }}" >> "$GITHUB_ENV"
          else
            echo "::error::pass release or run_id"; exit 1
          fi
          if [ "${{ inputs.live }}" = "true" ]; then echo "E2E_MARK=-m live or not live" >> "$GITHUB_ENV"; fi
      - name: Run
        shell: bash
        working-directory: e2e
        run: |
          run="python -m pytest $E2E_BROWSER --soak-seconds ${{ inputs.soak_seconds }} -v"
          if [ -n "$E2E_MARK" ]; then run="$run -m 'live or not live'"; fi
          if [ "$RUNNER_OS" = "Linux" ]; then eval "xvfb-run -a $run"; else eval "$run"; fi
```

---

### Task 9: Full run, PR, docs

- [ ] **Step 1: Full local run on macOS** against the release binary: `cd e2e && python3 -m pytest --binary $BIN -v -s 2>&1 | tee $SP/e2e-mac.txt`. Record pass/fail/skip counts and every finding.
- [ ] **Step 2: Open an issue** ("e2e: black-box user-journey suite") with `--repo lang315/camoufox`, and push the branch.
- [ ] **Step 3: Open the PR** with the evidence: the local tally, the triaged findings, and the CI run. Wait for the checks, and merge without `--auto`.
- [ ] **Step 4: Dispatch `e2e.yml`** with `release=v152.0.4-beta.31-fork.1` for the three-OS result, and record it on the issue.
