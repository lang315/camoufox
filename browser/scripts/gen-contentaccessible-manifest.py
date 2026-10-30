#!/usr/bin/env python3
"""
Record which files a stock Firefox release exposes to web content.

Packages flagged `contentaccessible=yes` in chrome.manifest can be loaded as
subresources by any page, from any origin (caps/nsScriptSecurityManager.cpp
checks the target's flag and not the source), so any file Camoufox adds, drops,
renames or changes there is page-detectable. Each file is recorded with its
SHA-256.

It also records the name of every chrome package and resource host the
manifests register, contentaccessible or not. Content processes receive all of
them, and a page can tell a registered name from an absent one:
new Worker("chrome://<name>/...") returns for the first and throws for the
second. hCaptcha probes chrome://juggler this way.

    python3 scripts/gen-contentaccessible-manifest.py /path/to/firefox

The directory holding application.ini and omni.ja: the Firefox directory on Linux,
Contents/Resources of Firefox.app on macOS, the unpacked installer's core/ on Windows.
Each OS ships its own files (hiddenWindowMac.xhtml, preprocessed markup), so it writes
scripts/data/contentaccessible-manifest.json for Linux and
contentaccessible-manifest-macos.json or -windows.json for the others, which
tests/playwright/patches/contentaccessible-parity.py diffs a build of that OS against.
Re-run it on a Firefox uplift, once per OS; the guard refuses to compare across versions.
"""

import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA = REPO_ROOT / "scripts" / "data"
JARS = ("browser/omni.ja", "omni.ja")


def manifest_path(os_name: str) -> Path:
    """The manifest of one OS's stock release; Linux's keeps the original name."""
    return DATA / ("contentaccessible-manifest.json" if os_name == "linux" else f"contentaccessible-manifest-{os_name}.json")


def stock_os(root: Path) -> str:
    """Which OS's release a Firefox directory is, from its layout."""
    if (root / "firefox.exe").exists():
        return "windows"
    return "macos" if root.name == "Resources" else "linux"


def zip_entries(jar: Path) -> dict:
    """Map member -> size of the files in a jar."""
    with zipfile.ZipFile(jar) as z:
        return {i.filename: i.file_size for i in z.infolist() if not i.is_dir()}


def packaged_bytes(name: str, data: bytes) -> bytes:
    """A file's bytes as the packager writes them into omni.ja: it strips the
    `#` comment lines of .ftl and .properties files (mozpack's
    MinifiedCommentStripped), which an unpackaged tree still carries."""
    if name.endswith((".ftl", ".properties")):
        data = b"".join(l for l in data.splitlines(keepends=True) if not l.startswith(b"#"))
    return data


def tree_hashes(base: Path, prefixes: list) -> dict:
    """Member -> SHA-256 for the files under `prefixes` in an extracted jar or
    an unpackaged dist/bin tree, which lays resources out at the same paths."""
    out = {}
    for prefix in prefixes:
        top = base / prefix
        if top.is_dir():
            for f in top.rglob("*"):
                if f.is_file():
                    out[f.relative_to(base).as_posix()] = hashlib.sha256(packaged_bytes(f.name, f.read_bytes())).hexdigest()
    return out


def jar_hashes(jar: Path, prefixes: list) -> dict:
    """Member -> SHA-256 for the files under `prefixes` in a jar."""
    with zipfile.ZipFile(jar) as z:
        return {
            n: hashlib.sha256(packaged_bytes(n, z.read(n))).hexdigest()
            for n in z.namelist() if not n.endswith("/") and any(n.startswith(p) for p in prefixes)
        }


def zip_read(jar: Path, member: str) -> str:
    with zipfile.ZipFile(jar) as z:
        return z.read(member).decode("utf8", "replace")


def resolve(target: str, base: str) -> tuple:
    """A manifest target -> (jar, prefix). Most are relative to the manifest, but
    `resource` entries may name a resource:// URI, which lands elsewhere."""
    if target.startswith("resource://gre/"):
        return "omni.ja", target[len("resource://gre/"):]
    if target.startswith("resource://devtools/"):
        return "browser/omni.ja", "chrome/devtools/modules/devtools/" + target[len("resource://devtools/"):]
    return None, base + target


def packages(root: Path) -> dict:
    """{jar|kind|name: [jar-relative prefix, ...]} for every contentaccessible package."""
    found = {}
    for jar in JARS:
        path = root / jar
        if not path.exists():
            continue
        for member in [m for m in zip_entries(path) if m.endswith("chrome.manifest")]:
            base = member.rsplit("/", 1)[0] + "/" if "/" in member else ""
            for line in zip_read(path, member).splitlines():
                if "contentaccessible=yes" not in line:
                    continue
                kind, name, target = line.split()[:3]
                other_jar, prefix = resolve(target, base)
                found.setdefault(f"{other_jar or jar}|{kind}|{name}", set()).add(prefix)
    return {k: sorted(v) for k, v in found.items()}


def registrations(root: Path) -> dict:
    """{kind: [name, ...]}: every chrome package (by content, locale or skin line)
    and every resource host the manifests register.

    Read from the jars of a packaged build, else from the loose manifests of an
    unpackaged dist/bin, which hold the same lines.
    """
    texts = []
    for jar in JARS:
        path = root / jar
        if path.exists():
            texts += [zip_read(path, m) for m in zip_entries(path) if m.endswith(".manifest")]
        else:
            base = root / "browser" if jar == "browser/omni.ja" else root
            texts += [f.read_text(errors="replace") for f in base.rglob("*.manifest")]
    found = {"content": set(), "locale": set(), "skin": set(), "resource": set()}
    for text in texts:
        for line in text.splitlines():
            words = line.split()
            if len(words) >= 2 and words[0] in found:
                found[words[0]].add(words[1])
    return {kind: sorted(names) for kind, names in found.items()}


def firefox_version(root: Path) -> str:
    ini = (root / "application.ini").read_text(errors="replace")
    match = re.search(r"^Version=(.+)$", ini, re.M)
    return match.group(1).strip() if match else "unknown"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    root = Path(sys.argv[1]).resolve()
    if root.is_file():
        root = root.parent
    if not (root / "application.ini").exists():
        print(f"FAIL: {root} is not a Firefox install (no application.ini)")
        return 1

    pkgs = packages(root)

    manifest = {"firefox_version": firefox_version(root), "packages": {}, "registered": registrations(root)}
    total = 0
    for key, prefixes in sorted(pkgs.items()):
        files = jar_hashes(root / key.split("|", 1)[0], prefixes)
        manifest["packages"][key] = {"prefixes": prefixes, "files": files}
        total += len(files)

    out = manifest_path(stock_os(root))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    print(f"Firefox {manifest['firefox_version']}: {len(pkgs)} packages, {total} files")
    print(f"wrote {out.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
