"""The launchers install this fork's browser, and only this fork's, by default (#266).

`repos.yml` used to default to daijro/camoufox, so `camoufox fetch` and the
launchers installed a browser without this fork's patches. Three things have to
hold for the fork to be the default:

- the default repo names this fork alone, because `get_asset` tries the next
  repo whenever one yields no matching asset, and the fork ships no Linux
  package, so a fallback would install upstream's browser on Linux;
- two fork releases that carry identically named assets are told apart by the
  asset's sha256, in the fetcher and in the decision that a machine is up to
  date;
- an installed upstream browser and a fork browser of the same version do not
  share a folder.
"""

import json

import pytest

from camoufox import multiversion, pkgman
from camoufox.__main__ import CamoufoxUpdate
from camoufox.exceptions import MissingRelease
from camoufox.multiversion import find_installed_by_build, get_repo_name, remove_incompatible_data
from camoufox.pkgman import RepoConfig, Version

# conftest refuses the fetcher; these tests mock the GitHub API underneath it.
REAL_GET_ASSET = pkgman.CamoufoxFetcher.get_asset

FORK = "lang315/camoufox"
UPSTREAM = "daijro/camoufox"
FORK_2 = "2" * 64
FORK_1 = "1" * 64


def _asset(name, sha):
    return {
        "name": name,
        "browser_download_url": f"https://example.invalid/{sha[:8]}/{name}",
        "digest": f"sha256:{sha}",
        "created_at": "2026-10-22T09:03:52Z",
    }


def _fork_release(tag, sha):
    return {
        "tag_name": tag,
        "prerelease": False,
        "assets": [
            _asset("camoufox-158.0-beta.33-win.x86_64.zip", sha),
            _asset("camoufox-158.0-beta.33-mac.arm64.zip", sha),
        ],
    }


# Newest first, as the GitHub API lists them.
FORK_RELEASES = [
    _fork_release("v158.0-beta.33-fork.2", FORK_2),
    _fork_release("v158.0-beta.33-fork.1", FORK_1),
]
UPSTREAM_RELEASES = [
    {
        "tag_name": "v135.0-beta.25",
        "prerelease": False,
        "assets": [
            _asset(f"camoufox-135.0-beta.25-{os_arch}.zip", "9" * 64)
            for os_arch in ("lin.x86_64", "mac.arm64", "win.x86_64")
        ],
    }
]


@pytest.fixture
def releases(monkeypatch):
    """Serve each repo's releases, and record which repos the fetcher asked."""
    asked = []
    served = {FORK: FORK_RELEASES, UPSTREAM: UPSTREAM_RELEASES, "camoufox/camoufox": UPSTREAM_RELEASES}

    def get_releases(self, github_repo):
        asked.append(github_repo)
        return served[github_repo]

    monkeypatch.setattr(pkgman.CamoufoxFetcher, "_get_releases", get_releases)
    return asked


def _fetcher(os_name, arch):
    fetcher = pkgman.CamoufoxFetcher.__new__(pkgman.CamoufoxFetcher)
    fetcher.repo_config = RepoConfig.get_default()
    fetcher.github_repos = fetcher.repo_config.repos
    fetcher.github_repo = fetcher.github_repos[0]
    fetcher.is_prerelease = False
    fetcher.arch = arch
    fetcher.pattern = fetcher.repo_config.build_pattern(spoof_os=os_name, spoof_arch=arch)
    fetcher.installed_sha256 = None
    fetcher.installed_created_at = None
    fetcher.installed_interface = 1
    return fetcher


def test_the_default_browser_is_this_forks_releases_alone():
    default = RepoConfig.get_default()
    assert (default.name, default.repos) == ("lang315", [FORK])


def test_the_other_browser_sources_are_still_chosen_by_name():
    assert RepoConfig.find_by_name("Official").repos == [UPSTREAM, "camoufox/camoufox"]
    assert RepoConfig.find_by_name("lang315").repos == [FORK]


@pytest.mark.parametrize("os_name, arch", [("mac", "arm64"), ("win", "x86_64")])
def test_the_fetcher_takes_the_newest_fork_release(releases, os_name, arch):
    fetcher = _fetcher(os_name, arch)
    version, url = REAL_GET_ASSET(fetcher)

    assert (version.version, version.build) == ("158.0", "beta.33")
    assert FORK_2[:8] in url
    assert fetcher.installed_sha256 == FORK_2
    assert releases == [FORK]


def test_linux_has_no_fork_package_and_never_falls_back_to_upstream(releases):
    fetcher = _fetcher("lin", "x86_64")
    with pytest.raises(MissingRelease):
        REAL_GET_ASSET(fetcher)
    assert releases == [FORK]


def _update(current, selected):
    update = CamoufoxUpdate.__new__(CamoufoxUpdate)
    update._version_obj = Version(build="beta.33", version="158.0")
    update.current_verstr = "158.0-beta.33"
    update.current_sha256 = current
    update.installed_sha256 = selected
    return update


def test_a_fork_release_that_reuses_the_version_and_build_still_updates():
    """fork.1 and fork.2 are both 158.0-beta.33: only the asset differs."""
    assert _update(current=FORK_1, selected=FORK_2).is_updated_needed()


def test_the_same_asset_is_up_to_date():
    assert not _update(current=FORK_2, selected=FORK_2).is_updated_needed()


@pytest.mark.parametrize("current, selected", [(None, FORK_2), (FORK_1, None), (None, None)])
def test_an_unknown_asset_digest_leaves_the_version_comparison_alone(current, selected):
    assert not _update(current=current, selected=selected).is_updated_needed()


def test_a_new_version_updates_whatever_the_digests_are():
    update = _update(current=FORK_2, selected=FORK_2)
    update.current_verstr = "156.0.1-beta.32"
    assert update.is_updated_needed()


def _install(root, repo_name, folder, sha):
    path = root / "browsers" / repo_name / folder
    path.mkdir(parents=True)
    (path / "version.json").write_text(
        json.dumps({"version": "158.0", "build": "beta.33", "sha256": sha})
    )
    return path


@pytest.fixture
def cache(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    root.mkdir()
    (root / ".0.5_FLAG").write_text("")
    for module in (pkgman, multiversion):
        monkeypatch.setattr(module, "INSTALL_DIR", root)
    monkeypatch.setattr(multiversion, "BROWSERS_DIR", root / "browsers")
    monkeypatch.setattr(multiversion, "CONFIG_FILE", root / "config.json")
    monkeypatch.setattr(multiversion, "COMPAT_FLAG", root / ".0.5_FLAG")
    return root


def test_a_fork_install_and_an_upstream_install_of_one_version_do_not_collide(cache):
    assert get_repo_name(FORK) == "lang315"
    assert get_repo_name(UPSTREAM) == "official"

    official = _install(cache, "official", "158.0-beta.33-99999999", "9" * 64)
    fork = _install(cache, "lang315", f"158.0-beta.33-{FORK_2[:8]}", FORK_2)

    assert find_installed_by_build("beta.33", "official").path == official
    assert find_installed_by_build("beta.33", "lang315").path == fork
    assert official != fork


def test_switching_the_default_repo_keeps_an_installed_upstream_browser(cache):
    official = _install(cache, "official", "158.0-beta.33-99999999", "9" * 64)
    (cache / "config.json").write_text(json.dumps({"active_version": f"browsers/official/{official.name}"}))

    remove_incompatible_data()

    assert (official / "version.json").exists()
    assert multiversion.get_active_path() == official
