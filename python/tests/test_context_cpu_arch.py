"""A context claims the CPU architecture its browser computes as (#458).

general.cpu_identity is a launch pref, so every context of a browser renders
canvas, audio, Opus, wasm and NaNs as the launch's CPU. A context whose GPU
implies another architecture pairs, say, a Windows x86 identity with arm64 audio.
"""

import os
import re
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest  # noqa: E402

from camoufox import sync_api, utils  # noqa: E402
from camoufox.coherence import gpu_cpu  # noqa: E402

ARM, INTEL = 3, 1  # general.cpu_identity: utils.cpu_identity_pref
APPLE_GPU = {"unmaskedVendor": "Apple", "unmaskedRenderer": "Apple M1, or similar"}
DRAWS = 20


def launched_with(cpu_identity):
    browser = mock.MagicMock()
    browser.version = "159.0"
    utils.attach_cpu_identity(browser, {"firefox_user_prefs": {"general.cpu_identity": cpu_identity}})
    return browser


def context_arch(browser, target_os):
    script = browser.new_context.return_value.add_init_script.call_args.args[0]
    renderer = re.search(r'setWebGLRenderer\("([^"]+)"\)', script).group(1)
    return gpu_cpu(renderer, target_os)[0] or "x86"


@pytest.mark.parametrize("os_", ["windows", "linux"])
def test_an_arm_browser_refuses_a_context_no_recorded_arm_machine_runs(os_):
    with pytest.raises(ValueError, match=r"computes as an arm CPU"):
        sync_api.NewContext(launched_with(ARM), os=os_)


def test_an_arm_browser_gives_a_macos_context_an_apple_gpu():
    for _ in range(DRAWS):
        browser = launched_with(ARM)
        sync_api.NewContext(browser, os="macos")
        assert context_arch(browser, "mac") == "arm"


def test_an_x86_browser_never_gives_a_macos_context_an_apple_gpu():
    # fpgen draws the screen before the GPU, and an Apple-silicon panel fits no
    # Intel Mac GPU (#463), so the draw either claims an Intel Mac or refuses.
    for _ in range(DRAWS):
        browser = launched_with(INTEL)
        try:
            sync_api.NewContext(browser, os="macos")
        except ValueError as exc:
            assert "computes as an x86 CPU" in str(exc) and "no mac GPU fpgen recorded" in str(exc)
        else:
            assert context_arch(browser, "mac") == "x86"


def test_a_preset_claiming_another_cpu_raises():
    preset = {"navigator": {"platform": "MacIntel"}, "webgl": APPLE_GPU}
    with pytest.raises(ValueError, match=r"computes as an x86 CPU"):
        sync_api.NewContext(launched_with(INTEL), preset=preset)


def test_a_webgl_config_claiming_another_cpu_raises():
    from camoufox.fingerprints import generate_context_fingerprint

    with pytest.raises(ValueError, match=r"computes as an x86 CPU"):
        generate_context_fingerprint(
            os="macos", webgl_config=tuple(APPLE_GPU.values()), cpu_arch="x86"
        )


@pytest.mark.parametrize("prefs, arch", [
    ({"general.cpu_identity": 3}, "arm"),
    ({"general.cpu_identity": 1}, "x86"),
    ({"general.cpu_identity": 2}, "x86"),
    ({"general.cpu_identity": 0}, None),
    ({}, None),
])
def test_the_launch_arch_is_read_from_its_cpu_identity_pref(prefs, arch):
    browser = mock.MagicMock()
    utils.attach_cpu_identity(browser, {"firefox_user_prefs": prefs})
    assert utils.launch_cpu_arch(browser) == arch


def test_a_browser_the_launcher_did_not_start_is_not_constrained():
    browser = mock.MagicMock()
    browser.version = "159.0"
    assert utils.launch_cpu_arch(browser) is None
    sync_api.NewContext(browser, os="windows")
