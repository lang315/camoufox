"""The bare-Playwright driver attaches the driver humanizer only when asked.

`launch_options(humanize=...)` merely validates the setting, so a `pw-humanize`
leg that stops at the launch tests raw input.
"""

import pytest

from drivers import playwright_drivers as pd


class _Playwright:
    class firefox:
        @staticmethod
        def launch(**opts):
            return "raw-browser"


@pytest.fixture
def attached(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(pd, "playwright", lambda: _Playwright)
    monkeypatch.setattr("camoufox.utils.launch_options", lambda **kw: {"firefox_user_prefs": {}, "config": kw})
    monkeypatch.setattr("camoufox.utils.launch_os", lambda opts: "macos")
    monkeypatch.setattr("camoufox.host_rendering.has_canvas_placeholder", lambda prefs: False)

    def attach(browser, humanize, os):
        calls.append((browser, humanize, os))
        return "humanized-browser"

    monkeypatch.setattr("camoufox.humanize.attach", attach)
    return calls, pd.PwDriver(tmp_path)


def test_the_humanize_leg_attaches_the_humanizer_with_the_identity_os(attached):
    calls, driver = attached
    b = driver.launch(humanize=True)
    assert calls == [("raw-browser", True, "macos")]
    assert b.b == "humanized-browser"


def test_the_plain_leg_attaches_nothing(attached):
    calls, driver = attached
    assert driver.launch().b == "raw-browser"
    assert calls == []
