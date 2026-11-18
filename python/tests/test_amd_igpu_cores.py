"""An AMD iGPU is never paired with a core count only Intel CPUs report (#446).

fpgen records Radeon HD 3200 machines at 2, 6, 8, 12 and 16 cores on Windows
and 2, 8, 12 and 16 on Linux, never at 10, 14, 18, 22 or 28. The GPU draw did
not know that, and a preset's GPU survived a launch that replaced its cores with
the host's, so a 10-core host paired the two. Every test here pins the cores it
needs: none reads the machine running it, so none passes vacuously on a runner
with four cores and a software renderer.
"""

import pytest

from camoufox import coherence, cpu_affinity
from camoufox import fingerprints as fp
from camoufox.utils import get_target_os
from camoufox.webgl import sample_webgl_for_screen

from test_identity_salt import launch

AMD_IGPU = {
    "win": "ANGLE (AMD, Radeon HD 3200 Graphics Direct3D11 vs_5_0 ps_5_0), or similar",
    "lin": "Radeon HD 3200 Graphics, or similar",
}
INTEL_ONLY = sorted(coherence.INTEL_ONLY_CORE_COUNTS)
SEEDS = range(300)


def drawn_vendors(target_os, cores):
    return [
        coherence.gpu_cpu_vendor(sample_webgl_for_screen(target_os, 1920, 1080, seed, cores=cores)["webGl:renderer"], target_os)
        for seed in SEEDS
    ]


@pytest.mark.parametrize("target_os", ["win", "lin"])
def test_the_gpu_draw_never_pairs_an_amd_igpu_with_an_intel_only_count(target_os):
    # Before the fix seeds 2, 20, 22 (Windows) and 0, 6, 46 (Linux) drew the Radeon at every one of these counts.
    for cores in INTEL_ONLY:
        assert "amd" not in drawn_vendors(target_os, cores), cores


@pytest.mark.parametrize("target_os", ["win", "lin"])
def test_the_gpu_draw_still_offers_an_amd_igpu_at_a_count_both_vendors_ship(target_os):
    vendors = drawn_vendors(target_os, 12)
    assert "amd" in vendors and "intel" in vendors


@pytest.mark.parametrize("target_os", ["win", "lin"])
def test_a_machine_check_names_the_pair(target_os):
    assert not coherence.gpu_fits_machine(AMD_IGPU[target_os], target_os, 10)
    assert coherence.gpu_fits_machine(AMD_IGPU[target_os], target_os, 12)
    assert coherence.gpu_fits_machine("Intel(R) HD Graphics, or similar", target_os, 10)
    assert coherence.gpu_fits_machine("NVIDIA GeForce GTX 980", target_os, 10)


@pytest.mark.parametrize("target_os", ["win", "lin"])
def test_validate_reports_the_pair_before_a_cpu_is_chosen(target_os):
    # The shipped-data cleaner validates a preset as converted, which has no cpu:* keys.
    config = {"webGl:renderer": AMD_IGPU[target_os], "navigator.hardwareConcurrency": 14}
    assert [v.rule for v in coherence.validate(config, target_os)] == ["cpu-matches-hardware"]


@pytest.mark.parametrize("os_name", ["windows", "linux"])
def test_a_preset_amd_igpu_is_redrawn_when_the_host_has_an_intel_only_count(os_name, monkeypatch):
    # The launch replaces the preset's cores with the host's; the presets
    # carry 2 to 16 cores, so only the host can make the pair.
    monkeypatch.setattr(cpu_affinity, "supported", lambda: False)
    monkeypatch.setattr(fp, "host_cpu_count", lambda: 10)
    key = {"windows": "win", "linux": "lin"}[os_name]
    amd = [p for p in fp.load_presets("150")["presets"][os_name] if coherence.gpu_cpu_vendor(p["webgl"]["unmaskedRenderer"], key) == "amd"]
    assert amd
    for preset in amd:
        config = launch(os=os_name, fingerprint_preset=preset)
        assert config["navigator.hardwareConcurrency"] == 10
        assert coherence.gpu_cpu_vendor(config["webGl:renderer"], key) != "amd"
        assert coherence.validate(config, key) == []


@pytest.mark.parametrize("os_name", ["windows", "linux"])
def test_a_generated_identity_on_an_intel_only_host_is_coherent(os_name, monkeypatch):
    monkeypatch.setattr(cpu_affinity, "supported", lambda: False)
    monkeypatch.setattr(fp, "host_cpu_count", lambda: 14)
    for _ in range(40):
        config = launch(os=os_name, canvas_noise=True)
        assert config["navigator.hardwareConcurrency"] == 14
        assert coherence.validate(config, get_target_os(config)) == []


@pytest.mark.parametrize("os_name", ["windows", "linux"])
def test_a_context_identity_with_an_intel_only_count_is_coherent(os_name, monkeypatch):
    # fpgen draws the context's cores; the count is replaced after its draw, as
    # fpgen has no such machine for every OS and conditioning on one can fail.
    from_fpgen = fp.from_fpgen

    def intel_only(*args, **kwargs):
        config = from_fpgen(*args, **kwargs)
        config["navigator.hardwareConcurrency"] = 22
        return config

    monkeypatch.setattr(fp, "from_fpgen", intel_only)
    for _ in range(40):
        config = fp.generate_context_fingerprint(os=os_name)["config"]
        assert config["navigator.hardwareConcurrency"] == 22
        assert coherence.gpu_cpu_vendor(config["webGl:renderer"], get_target_os(config)) != "amd"


def refusal(monkeypatch, can_pin, **kwargs):
    monkeypatch.setattr(cpu_affinity, "supported", lambda: can_pin)
    monkeypatch.setattr(fp, "host_cpu_count", lambda: 10)
    with pytest.raises(ValueError, match=r"only an Intel CPU reports") as raised:
        launch(os="linux", canvas_noise=True, cpu={"manufacturer": "amd"}, **kwargs)
    return str(raised.value)


def test_a_refusal_on_a_host_that_cannot_pin_says_the_count_is_the_hosts(monkeypatch):
    message = refusal(monkeypatch, can_pin=False)

    assert "hardwareConcurrency 10" in message
    assert "this host's logical core count" in message
    assert "cannot pin" in message
    assert "pin_cpu_cores" not in message


def test_a_refusal_with_pinning_off_names_the_option_that_turns_it_on(monkeypatch):
    message = refusal(monkeypatch, can_pin=True)

    assert "this host's logical core count" in message
    assert "pin_cpu_cores=True" in message


def test_a_refusal_of_a_count_the_caller_set_says_so(monkeypatch):
    message = refusal(monkeypatch, can_pin=True, config={"navigator.hardwareConcurrency": 10})

    assert "You set that count" in message
    assert "host's" not in message
