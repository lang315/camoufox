"""audio-matches-stock.py expects the stock audio of the CPU the launch claims, not the host's (#456).

An aarch64 build claiming an x86 CPU renders x86-64 audio (cpu-vendor-estimates.patch),
so on an arm64 host the guard must still expect x86-64 values for an x86 claim.
"""

import importlib.util
import platform
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "browser/tests/playwright/patches/audio-matches-stock.py"


@pytest.fixture(scope="module")
def guard():
    spec = importlib.util.spec_from_file_location("audio_matches_stock", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("host", ["arm64", "aarch64", "x86_64", "AMD64"])
@pytest.mark.parametrize("claim, key", [("x86", "x86_64"), ("arm", "arm64")])
def test_the_claimed_cpu_picks_the_expected_values_on_any_host(guard, monkeypatch, host, claim, key):
    monkeypatch.setattr(platform, "machine", lambda: host)
    assert guard.expected_arch({"cpu:arch": claim, "cpu:manufacturer": "intel"}) == key


def test_a_launch_claiming_no_cpu_has_no_expected_values(guard):
    assert guard.expected_arch({}) is None


def test_launch_config_joins_the_chunks_in_numeric_order(guard):
    env = {"CAMOU_CONFIG_10": '"}', "CAMOU_CONFIG_2": '"cpu:arch": ', "CAMOU_CONFIG_1": "{",
           **{f"CAMOU_CONFIG_{i}": "" for i in range(3, 9)}, "CAMOU_CONFIG_9": '"x86', "HOME": "/x"}
    assert guard.launch_config({"env": env}) == {"cpu:arch": "x86"}
