"""The fork's seeded canvas noise runs only where the RFP placeholder does not cover the canvas.

On the host's OS a launch claims the host's GPU and leaves the canvas uncovered,
so the fork's per-launch and per-context `canvas:seed` (canvas-spoofing.patch)
keeps two contexts on one host from rendering the same canvas. On another OS
plan_rendering turns the RFP placeholder on, and no seed may reach the browser:
CanvasSeedManager::GetSeed returns 0 without a launch-level `canvas:seed` or a
`setCanvasSeed` call, which leaves the patch inert.
"""

import asyncio
import re
from unittest import mock

import orjson
import pytest

from camoufox import utils
from camoufox.async_api import AsyncNewBrowser, AsyncNewContext
from camoufox.fingerprints import OS_NAMES
from camoufox.sync_api import NewBrowser, NewContext

HOST = OS_NAMES[utils._host_os_key()]
OTHER = next(name for name in OS_NAMES.values() if name != HOST)
SEED_CALL = re.compile(r"setCanvasSeed\((\d+)\)")


class FakeContext:
    def __init__(self):
        self.scripts = []

    def add_init_script(self, script):
        self.scripts.append(script)


class FakeBrowser:
    version = "156.0.1"

    def __init__(self, options):
        self.options = options
        self.contexts = []

    def new_context(self, **kwargs):
        self.contexts.append(FakeContext())
        return self.contexts[-1]

    def new_page(self, **kwargs):
        raise AssertionError("not used")


class FakePlaywright:
    def __init__(self):
        self.firefox = self

    def launch(self, **options):
        return FakeBrowser(options)


class AsyncFakeContext(FakeContext):
    async def add_init_script(self, script):
        self.scripts.append(script)


class AsyncFakeBrowser(FakeBrowser):
    async def new_context(self, **kwargs):
        self.contexts.append(AsyncFakeContext())
        return self.contexts[-1]


class AsyncFakePlaywright(FakePlaywright):
    async def launch(self, **options):
        return AsyncFakeBrowser(options)


@pytest.fixture(autouse=True)
def no_display():
    with mock.patch.object(utils, "get_screen_cons", lambda headless: None), mock.patch.object(
        utils, "has_display", lambda env: False
    ):
        yield


def launch(os):
    return NewBrowser(FakePlaywright(), os=os, headless=True, i_know_what_im_doing=True)


def launch_config(browser):
    env = browser.options["env"]
    chunks = sorted((int(k.rsplit("_", 1)[1]), v) for k, v in env.items() if k.startswith("CAMOU_CONFIG_"))
    return orjson.loads("".join(v for _, v in chunks))


def context_seeds(browser):
    return [SEED_CALL.findall(script) for context in browser.contexts for script in context.scripts]


def test_an_uncovered_launch_seeds_the_launch_and_every_context():
    browser = launch(HOST)
    assert 1 <= launch_config(browser)["canvas:seed"] <= 0xFFFFFFFF
    NewContext(browser)
    NewContext(browser)
    (first,), (second,) = context_seeds(browser)
    assert first != second


def test_a_covered_launch_sends_no_launch_seed():
    assert "canvas:seed" not in launch_config(launch(OTHER))


def test_a_covered_launch_seeds_no_context():
    browser = launch(OTHER)
    NewContext(browser)
    NewContext(browser, os=OTHER)
    assert context_seeds(browser) == [[], []]


def test_another_os_on_an_uncovered_browser_raises():
    with pytest.raises(ValueError, match="canvas_noise=True"):
        NewContext(launch(HOST), os=OTHER)


def test_the_async_api_follows_the_same_rule():
    async def contexts(os):
        browser = await AsyncNewBrowser(AsyncFakePlaywright(), os=os, headless=True, i_know_what_im_doing=True)
        await AsyncNewContext(browser)
        return context_seeds(browser)

    [[seed]] = asyncio.run(contexts(HOST))
    assert int(seed) >= 1
    assert asyncio.run(contexts(OTHER)) == [[]]
