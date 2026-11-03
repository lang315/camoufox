"""stock-gpu-parity's choice of a recorded device for the host it runs on (#338).

A hosted Windows runner renders with Microsoft Basic Render Driver, a software
renderer fpgen never recorded on Windows. The launcher lets a software renderer
claim any GPU, so the guard has to pick a device from the OS's recordings
rather than look the host's own GPU up.
"""

import importlib.util
from pathlib import Path

import pytest

from camoufox import webgl

SCRIPT = Path(__file__).resolve().parents[2] / "browser/tests/playwright/patches/stock-gpu-parity.py"
BASIC_RENDER = [
    "Google Inc. (Microsoft)",
    "ANGLE (Microsoft, Microsoft Basic Render Driver (0x0000008C) Direct3D11 vs_5_0 ps_5_0), or similar",
]


@pytest.fixture(scope="module")
def guard():
    spec = importlib.util.spec_from_file_location("stock_gpu_parity", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_basic_render_driver_is_not_a_recorded_windows_gpu():
    # The premise: if fpgen ever records it, the lookup works and this test is moot.
    assert tuple(BASIC_RENDER) not in webgl.firefox_gpus("win")


def test_an_unrecorded_software_renderer_gets_a_recorded_device(guard):
    device = guard.nearest_device("win", BASIC_RENDER, {})
    assert device["webGl:parameters"]


def test_a_recorded_gpu_keeps_to_its_own_devices(guard):
    gpu = sorted(webgl.firefox_gpus("win"))[0]
    own = webgl.recorded_devices("win", *gpu)
    assert guard.nearest_device("win", list(gpu), {}) in own
