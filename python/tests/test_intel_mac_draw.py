"""An Intel Mac identity draws a screen and core count some Intel Mac has (#463).

fpgen drew the macOS screen without regard to the CPU, and on an
Apple-silicon panel no Intel Mac GPU fits (coherence._intel_mac_misfit), so
launch_options(os="macos", cpu={"arch": "x86"}) failed about half the time
with "No recorded mac GPU fits a WxH screen".
"""

import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import orjson  # noqa: E402
import pytest  # noqa: E402

from camoufox import coherence, utils  # noqa: E402
from camoufox.fingerprints import Screen  # noqa: E402

DRAWS = 30


def fits_an_intel_mac(config):
    return coherence.gpu_fits_machine(
        config["webGl:renderer"], "mac", config["navigator.hardwareConcurrency"],
        config["screen.width"], config["screen.height"],
    )


@pytest.fixture
def stub_host():
    with mock.patch.object(utils, "_host_os_key", lambda: "lin"), mock.patch.object(
        utils, "has_display", lambda env: False
    ), mock.patch.object(utils, "installed_verstr", lambda: "159.0"), mock.patch.object(
        utils, "launch_path", lambda **kwargs: "/nonexistent/camoufox"
    ):
        yield


def config_of(options):
    env = options["env"]
    chunks = sorted((int(k.rsplit("_", 1)[1]), v) for k, v in env.items() if k.startswith("CAMOU_CONFIG_"))
    return orjson.loads("".join(chunk for _, chunk in chunks))


@pytest.mark.parametrize("cpu", [{"arch": "x86"}, {"manufacturer": "intel"}])
def test_an_intel_mac_launch_always_draws_an_intel_mac(stub_host, cpu):
    for _ in range(DRAWS):
        config = config_of(utils.launch_options(
            os="macos", cpu=cpu, canvas_noise=True, headless=True, i_know_what_im_doing=True,
        ))
        assert (config["cpu:arch"], config["cpu:manufacturer"]) == ("x86", "intel")
        assert fits_an_intel_mac(config)


def test_an_intel_mac_launch_on_an_apple_silicon_display_draws_an_intel_mac(stub_host):
    # The display bound and the Intel Mac screen predicate are both conditions
    # on fpgen's screen node; fpgen ignored the predicate beside the bound.
    display = Screen(max_width=1512, max_height=982)  # a MacBook Pro 14" display
    with mock.patch.object(utils, "has_display", lambda env: True), mock.patch.object(
        utils, "get_screen_cons", lambda headless: display
    ):
        for _ in range(DRAWS):
            config = config_of(utils.launch_options(
                os="macos", cpu={"arch": "x86"}, canvas_noise=True, headless=False, i_know_what_im_doing=True,
            ))
            assert fits_an_intel_mac(config)


def test_the_conditions_admit_only_what_some_intel_mac_has():
    conditions = coherence.intel_mac_conditions()
    screen, cores = conditions["screen"], conditions["navigator.hardwareConcurrency"]
    assert not screen({"width": 1512, "height": 982})  # MacBook Pro 14", Apple Silicon only
    assert screen({"width": 1440, "height": 900})
    assert not cores(11)
    assert cores(8) and cores(28)
