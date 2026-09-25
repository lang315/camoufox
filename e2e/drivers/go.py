"""goapi, driven through goapi/cmd/e2edriver over JSON lines."""

from __future__ import annotations

import base64
import json
import os
import queue
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
EXE = REPO / ".ci-work" / ("e2edriver.exe" if os.name == "nt" else "e2edriver")
# Longer than e2edriver's own 90 s per-request context, so a reply that does come
# always arrives first. A driver that answers nothing by then is wedged.
RPC_TIMEOUT_S = 120
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

    def _start(self) -> None:
        self.proc = subprocess.Popen([str(build())], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
        self.replies: "queue.Queue[str]" = queue.Queue()
        out = self.proc.stdout

        def pump():  # a reader thread, so a wedged driver times out instead of hanging the run
            for line in out:
                self.replies.put(line)
            self.replies.put("")

        threading.Thread(target=pump, daemon=True).start()

    def rpc(self, op: str, h: str = "", **args):
        if self.proc is None:
            self._start()
        self.n += 1
        try:
            self.proc.stdin.write(json.dumps({"id": self.n, "op": op, "h": h, "args": args}) + "\n")
            self.proc.stdin.flush()
            line = self.replies.get(timeout=RPC_TIMEOUT_S)
        except (queue.Empty, OSError) as e:
            self.proc.kill()
            self.proc = None
            raise RuntimeError(f"go {op}: e2edriver gave no reply in {RPC_TIMEOUT_S}s ({type(e).__name__}); killed it") from e
        if not line:
            self.proc = None
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

    def new_identity_context(self):
        pytest.skip("go: no per-context identity API")

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
