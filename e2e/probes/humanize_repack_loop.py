"""Diag for #472, never merged: the humanize loop on a repacked control build.

    python e2e/probes/humanize_repack_loop.py --zip ZIP [--runs N]

Two arms on the same build, each unpacked afresh:
  own:     omni.ja repacked with its own MouseDispatch.js, unchanged (negative control)
  c8dc35a7: omni.ja repacked with this checkout's MouseDispatch.js, #474's fix
Each prints the sha256 of MouseDispatch.js inside omni.ja before and after the
repack. This is a repacked control build, not a built package.
"""

import argparse
import hashlib
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from humanize_loop import loop  # noqa: E402
from other_names_stall import unpack  # noqa: E402

ENTRY = "modules/juggler/input/MouseDispatch.js"
CHECKOUT = ROOT / "browser/additions/juggler/input/MouseDispatch.js"
# sha256 of MouseDispatch.js at c8dc35a7 (git show c8dc35a7:browser/additions/juggler/input/MouseDispatch.js).
C8DC35A7 = "f6b39fbb77486cbf7174a2715a33ab286e8cb3d0e19402d475b18a814c0469b5"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def omni_of(binary: Path) -> Path:
    for omni in (binary.parent.parent / "Resources" / "omni.ja", binary.parent / "omni.ja"):
        if omni.exists():
            return omni
    raise FileNotFoundError(f"no omni.ja beside {binary}")


def repack(omni: Path, replacement: bytes | None) -> None:
    """Rewrite omni.ja entry by entry, in order, with ENTRY replaced (or its own bytes)."""
    tmp = omni.with_suffix(".repack")
    with zipfile.ZipFile(omni) as src, zipfile.ZipFile(tmp, "w") as dst:
        for info in src.infolist():
            data = src.read(info)
            if info.filename == ENTRY and replacement is not None:
                data = replacement
            dst.writestr(info, data)
    shutil.move(tmp, omni)


def main() -> int:
    a = argparse.ArgumentParser()
    a.add_argument("--zip", required=True)
    a.add_argument("--runs", type=int, default=0)
    args = a.parse_args()
    fix = CHECKOUT.read_bytes()
    print(f"checkout MouseDispatch.js sha256 {sha(fix)}; c8dc35a7's {C8DC35A7}", flush=True)
    if sha(fix) != C8DC35A7:
        print("FAIL: the checkout's MouseDispatch.js is not c8dc35a7's", flush=True)
        return 1
    for label, replacement in (("own", None), ("c8dc35a7", fix)):
        with tempfile.TemporaryDirectory(prefix=f"humanize-repack-{label}-") as tmp:
            binary = unpack(args.zip, Path(tmp))
            omni = omni_of(binary)
            with zipfile.ZipFile(omni) as z:
                before = sha(z.read(ENTRY))
            repack(omni, replacement)
            with zipfile.ZipFile(omni) as z:
                after = sha(z.read(ENTRY))
            print(f"ARM {label}: {omni} MouseDispatch.js sha256 before {before} after {after}", flush=True)
            loop(binary, label)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
