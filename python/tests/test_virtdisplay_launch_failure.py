"""
Tests for Xvfb (virtual display) cleanup on launch failure (#363).

`AsyncNewBrowser`/`NewBrowser` start a VirtualDisplay (Xvfb) via
`virtual_display.get()` *before* calling `launch_options()` /
`playwright.firefox.launch()`. If either of those raise, the function used to
exit before reaching `async_attach_vd()` / `sync_attach_vd()` -- the only
places that wire `virtual_display.kill()` into `browser.close()` -- leaking
the Xvfb process under `headless="virtual"`.

These tests fake out VirtualDisplay and the Playwright launch calls, so they
run without Linux/Xvfb or an installed Camoufox browser.

Run with:
    cd pythonlib && python -m pytest tests/test_virtdisplay_launch_failure.py -v
"""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, Mock

import pytest

# Make `import camoufox` resolve to the in-tree pythonlib without an install.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from camoufox import async_api, sync_api  # noqa: E402


class _FakeVirtualDisplay:
    """Stand-in for camoufox.virtdisplay.VirtualDisplay that needs no Xvfb/Linux."""

    instances = []

    def __init__(self, debug=False):
        self.debug = debug
        self.get = Mock(return_value=":99")
        self.kill = Mock()
        _FakeVirtualDisplay.instances.append(self)


@pytest.fixture
def fake_vd(monkeypatch):
    _FakeVirtualDisplay.instances = []
    monkeypatch.setattr(async_api, "VirtualDisplay", _FakeVirtualDisplay)
    monkeypatch.setattr(sync_api, "VirtualDisplay", _FakeVirtualDisplay)
    return _FakeVirtualDisplay


# --- async_api.AsyncNewBrowser ------------------------------------------------


def test_async_new_browser_kills_virtual_display_when_launch_raises(fake_vd):
    fake_playwright = Mock()
    fake_playwright.firefox.launch = AsyncMock(side_effect=RuntimeError("boom"))

    async def run():
        await async_api.AsyncNewBrowser(
            fake_playwright,
            headless="virtual",
            from_options={"executable_path": "/fake"},
        )

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(run())

    assert len(fake_vd.instances) == 1
    fake_vd.instances[0].kill.assert_called_once()


def test_async_new_browser_kills_virtual_display_when_launch_options_raises(fake_vd, monkeypatch):
    fake_playwright = Mock()
    fake_playwright.firefox.launch = AsyncMock()

    def _boom(**kwargs):
        raise ValueError("bad options")

    monkeypatch.setattr(async_api, "launch_options", _boom)

    async def run():
        await async_api.AsyncNewBrowser(fake_playwright, headless="virtual")

    with pytest.raises(ValueError, match="bad options"):
        asyncio.run(run())

    assert len(fake_vd.instances) == 1
    fake_vd.instances[0].kill.assert_called_once()
    fake_playwright.firefox.launch.assert_not_called()


def test_async_new_browser_kills_virtual_display_when_persistent_context_launch_raises(fake_vd):
    fake_playwright = Mock()
    fake_playwright.firefox.launch_persistent_context = AsyncMock(side_effect=RuntimeError("boom"))

    async def run():
        await async_api.AsyncNewBrowser(
            fake_playwright,
            headless="virtual",
            persistent_context=True,
            from_options={"executable_path": "/fake", "user_data_dir": "/fake-profile"},
        )

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(run())

    assert len(fake_vd.instances) == 1
    fake_vd.instances[0].kill.assert_called_once()


def test_async_new_browser_does_not_kill_virtual_display_on_success(fake_vd):
    fake_playwright = Mock()
    fake_playwright.firefox.launch = AsyncMock(return_value=Mock())

    async def run():
        await async_api.AsyncNewBrowser(
            fake_playwright,
            headless="virtual",
            from_options={"executable_path": "/fake"},
        )

    asyncio.run(run())

    assert len(fake_vd.instances) == 1
    fake_vd.instances[0].kill.assert_not_called()


# --- sync_api.NewBrowser -------------------------------------------------------


def test_sync_new_browser_kills_virtual_display_when_launch_raises(fake_vd):
    fake_playwright = Mock()
    fake_playwright.firefox.launch = Mock(side_effect=RuntimeError("boom"))

    with pytest.raises(RuntimeError, match="boom"):
        sync_api.NewBrowser(
            fake_playwright,
            headless="virtual",
            from_options={"executable_path": "/fake"},
        )

    assert len(fake_vd.instances) == 1
    fake_vd.instances[0].kill.assert_called_once()


def test_sync_new_browser_kills_virtual_display_when_launch_options_raises(fake_vd, monkeypatch):
    fake_playwright = Mock()
    fake_playwright.firefox.launch = Mock()

    def _boom(**kwargs):
        raise ValueError("bad options")

    monkeypatch.setattr(sync_api, "launch_options", _boom)

    with pytest.raises(ValueError, match="bad options"):
        sync_api.NewBrowser(fake_playwright, headless="virtual")

    assert len(fake_vd.instances) == 1
    fake_vd.instances[0].kill.assert_called_once()
    fake_playwright.firefox.launch.assert_not_called()


def test_sync_new_browser_does_not_kill_virtual_display_on_success(fake_vd):
    fake_playwright = Mock()
    fake_playwright.firefox.launch = Mock(return_value=Mock())

    sync_api.NewBrowser(
        fake_playwright,
        headless="virtual",
        from_options={"executable_path": "/fake"},
    )

    assert len(fake_vd.instances) == 1
    fake_vd.instances[0].kill.assert_not_called()
