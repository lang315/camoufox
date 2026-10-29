"""build-tester takes its Linux fontconfig from the launcher's generator (#329).

The browser activates only Firefox's own bundled files, so a raw launch with no
FONTCONFIG_FILE measures the host's fonts. These two checks pin that the runner
cannot reach that state silently: it raises when the bundle has no conf, and the
conf it writes names group directories, never the fonts/ parent.
"""

import json
import re
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "browser" / "tests" / "build-tester" / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "python" / "src"))

import runner  # noqa: E402


@pytest.fixture
def linux_host(monkeypatch, tmp_path):
    monkeypatch.setattr(runner.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    return tmp_path


def test_a_bundle_without_the_conf_fails_loudly(linux_host):
    (linux_host / "bin").mkdir()
    with pytest.raises(FileNotFoundError):
        runner.launcher_fontconfig(str(linux_host / "bin" / "camoufox-bin"), "linux")


def test_the_conf_names_the_group_directories_and_never_the_parent(linux_host):
    bin_dir = linux_host / "bin"
    shutil.copytree(REPO_ROOT / "browser" / "bundle" / "fontconfig" / "linux", bin_dir / "fontconfig" / "linux")
    read_by = ["L", "LM", "LW", "LMW"]
    for group in read_by + ["M", "W"]:
        (bin_dir / "fonts" / group).mkdir(parents=True)
    (bin_dir / "fonts" / "groups.json").write_text(json.dumps({"readBy": {"lin": read_by}}), encoding="utf-8")

    env = runner.launcher_fontconfig(str(bin_dir / "camoufox-bin"), "linux")

    conf = Path(env["FONTCONFIG_FILE"]).read_text(encoding="utf-8")
    named = re.findall(r"<dir>(.*?)</dir>", conf)
    assert sorted(Path(d).name for d in named if Path(d).parent == bin_dir / "fonts") == sorted(read_by)
    assert str(bin_dir / "fonts") not in named
