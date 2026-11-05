"""gen-contentaccessible-manifest.py reads an optimized jar (#415).

Mozilla's Windows and macOS installers ship omni.ja with the central directory at offset 4,
which zipfile cannot find. The Linux build's jar is a plain zip, so only the stock Windows and
macOS releases the manifests are recorded from hit it.
"""

import importlib.util
import struct
import zipfile

import pytest

from ci._util import REPO_ROOT


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location(
        "gen_contentaccessible_manifest", REPO_ROOT / "browser/scripts/gen-contentaccessible-manifest.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def optimized(path, files):
    """Write `files` as a zip laid out the way Mozilla optimizes a jar: 4 bytes, the central
    directory, the entries, the end record."""
    plain = path.with_suffix(".zip")
    with zipfile.ZipFile(plain, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    raw = plain.read_bytes()
    end = raw.rfind(b"PK\x05\x06")
    size, offset = struct.unpack_from("<LL", raw, end + 12)
    cd = bytearray(raw[offset:offset + size])
    shift = 4 + size
    pos = 0
    while pos < size:
        n, m, k = struct.unpack_from("<3H", cd, pos + 28)
        struct.pack_into("<L", cd, pos + 42, struct.unpack_from("<L", cd, pos + 42)[0] + shift)
        pos += 46 + n + m + k
    eocd = bytearray(raw[end:])
    struct.pack_into("<L", eocd, 16, 4)
    path.write_bytes(b"\0\0\0\0" + bytes(cd) + raw[:offset] + bytes(eocd))


def test_reads_an_optimized_jar(gen, tmp_path):
    jar = tmp_path / "omni.ja"
    optimized(jar, {"chrome/chrome.manifest": "content a a/\n", "a/b.js": "x"})
    with pytest.raises(zipfile.BadZipFile):
        zipfile.ZipFile(jar)
    assert gen.zip_entries(jar) == {"chrome/chrome.manifest": 13, "a/b.js": 1}
    assert gen.zip_read(jar, "a/b.js") == "x"
    assert gen.jar_hashes(jar, ["a/"]).keys() == {"a/b.js"}


def test_reads_a_plain_zip(gen, tmp_path):
    jar = tmp_path / "plain.ja"
    with zipfile.ZipFile(jar, "w") as z:
        z.writestr("a/b.js", "x")
    assert gen.zip_entries(jar) == {"a/b.js": 1}
