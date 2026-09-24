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
    def __init__(self, browser, identity_context=None) -> None:
        self.b, self._identity_context = browser, identity_context

    def new_context(self) -> PwCtx:
        return PwCtx(self.b.new_context())

    def new_identity_context(self) -> PwCtx:
        """camoufox.sync_api.NewContext: a context with its own fingerprint (pkg only)."""
        if self._identity_context is None:
            pytest.skip("no per-context identity API on this entry point")
        return PwCtx(self._identity_context(self.b))

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
    """camoufox.sync_api.NewBrowser; plain contexts are what `Camoufox()` +
    `browser.new_page()` gives, and new_identity_context() is NewContext."""

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
        b = PwBrowser(playwright().firefox.launch(**opts))
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
        b = PwBrowser(browser)
        self.browsers.append(b)
        return b
