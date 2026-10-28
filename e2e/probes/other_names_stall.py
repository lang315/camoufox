"""#253 probe: how long does the first lookup of a legacy family name block?

    python3 e2e/probes/other_names_stall.py (--binary BIN | --zip ZIP) [--runs 5]

font-other-names-sync.patch (#247) reads the "other family names" on a masked
page's first lookup, so that lookup blocks while the names load. Each run
launches a fresh browser with an identity (`--os`, default `windows`) whose `fonts` are the three
DejaVu legacy names, then measures all three in one page three times in a row
and prints the milliseconds of each call. The first holds the stall; the second
and third are the steady cost. `--zip` unpacks a release or build zip, which is how
the e2e workflow runs it (`gh workflow run e2e.yml -f run_id=<build> -f probe=other_names_stall.py`).
A fast first call is not proof the names
resolved: without the patch a miss returns in a few ms. That question belongs to
patches/legacy-family-names-first-measure.py.
"""

import argparse
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from camoufox.sync_api import Camoufox

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from util import build_id, find_binary  # noqa: E402

NAMES = ["DejaVu Sans Condensed", "DejaVu Sans Light", "DejaVu Serif Condensed"]
JS = """(names) => {
  const c = document.createElement('canvas').getContext('2d');
  c.fontKerning = 'none';
  const t0 = performance.now();
  for (const n of names) { c.font = `72px "${n}", monospace`; c.measureText('HxmW0 .8Qgy'); }
  return performance.now() - t0;
}"""


def unpack(zp: str, dest: Path) -> Path:
    if os.name == "nt":
        zipfile.ZipFile(zp).extractall(dest)
    else:  # keeps the executable bits zipfile would drop
        subprocess.run(["unzip", "-q", "-o", zp, "-d", str(dest)], check=True)
    return find_binary(dest)


def main() -> int:
    a = argparse.ArgumentParser()
    src = a.add_mutually_exclusive_group(required=True)
    src.add_argument("--binary")
    src.add_argument("--zip")
    a.add_argument("--runs", type=int, default=5)
    a.add_argument("--os", default="windows", choices=["windows", "macos", "linux"],
                   help="identity OS; on a Windows host `windows` is the host's own and never takes the sync load")
    args = a.parse_args()
    with tempfile.TemporaryDirectory(prefix="stall-probe-") as tmp:
        binary = unpack(args.zip, Path(tmp)) if args.zip else Path(args.binary)
        print(f"binary: {binary}  BuildID={build_id(binary)}", flush=True)
        return measure(binary, args.runs, args.os)


def measure(binary: Path, runs: int, identity: str) -> int:
    firsts = []
    for i in range(runs):
        with Camoufox(executable_path=str(binary), os=identity, headless=True, fonts=NAMES, i_know_what_im_doing=True) as b:
            page = b.new_page()
            page.goto("about:blank")
            calls = [page.evaluate(JS, NAMES) for _ in range(3)]
        firsts.append(calls[0])
        print(f"run {i}: {[round(c, 1) for c in calls]} ms", flush=True)
    print(f"first call: min {min(firsts):.1f} ms, max {max(firsts):.1f} ms over {runs} fresh browsers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
