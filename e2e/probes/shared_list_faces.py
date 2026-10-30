"""#345 probe: the parent's shared font list, face by face, for one browser build.

    python3 e2e/probes/shared_list_faces.py --zip ZIP [--runs N]   (E2E_MOZ_LOG = output dir)

Per identity OS: launch once to read every family name the shared list holds
(`(shared-fontlist) family N (name)`), launch again and measure each name on a canvas at every weight, upright and italic, twice, so
the parent initialises the family and every tied face is looked up, then write the parent's `added face` lines (family,
descriptor, index, weight, style, width) sorted into <out>/faces-<os>.txt. Two builds
that print identical files built identical shared lists for the names the identity
lets through. The content logs are grepped for `bundled-face-miss`, and for the stock
`CAMOU-FL facename` lines that show a content log was captured at all.
"""

import argparse
import gzip
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

from camoufox.sync_api import Camoufox

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from util import build_id  # noqa: E402
from other_names_stall import unpack  # noqa: E402

JS = """(names) => {
  const c = document.createElement('canvas').getContext('2d');
  for (const n of names) {
    for (const st of ['normal', 'italic']) for (const w of [100, 200, 300, 400, 500, 600, 700, 800, 900]) {
      c.font = `${st} ${w} 20px "${n}", monospace`; c.measureText('HxmW0 .8Qgy');
    }
  }
  return names.length;
}"""
FAMILY = re.compile(r"\(shared-fontlist\) family \d+ \((.*)\)$")
FACE = re.compile(r"\(shared-fontlist\) family \((.*?)\) added face \((.*?)\) index (\d+), weight (.*?), style (.*?), width (.*)$")


def launch(binary: Path, identity: str, log: Path, body):
    env = {**os.environ, "MOZ_LOG": "sync,fontlist:4", "MOZ_LOG_FILE": str(log)}
    with Camoufox(executable_path=str(binary), os=identity, headless=True, env=env, i_know_what_im_doing=True) as b:
        return body(b.new_page())


def logs(work: Path, stem: str):
    """Gecko appends `.moz_log` to MOZ_LOG_FILE and `.child-N` before it for each content process."""
    found = sorted(work.glob(f"{stem}*"))
    kids = [f for f in found if ".child-" in f.name]
    parent = [f for f in found if f not in kids]
    assert len(parent) == 1, f"expected one parent log for {stem}, found {[f.name for f in found]}"
    return parent[0], kids


def lines(path: Path):
    with open(path, encoding="utf-8", errors="replace") as f:
        for ln in f:
            yield ln.rstrip("\n")


def run(binary: Path, identity: str, out: Path) -> None:
    work = Path(tempfile.mkdtemp(prefix=f"faces-{identity}-"))
    launch(binary, identity, work / "names", lambda p: p.goto("about:blank"))
    names = sorted({m.group(1) for ln in lines(logs(work, "names")[0]) if (m := FAMILY.search(ln))})

    def sweep(page):
        page.goto("about:blank")
        for _ in range(2):  # a family the parent initialises on the first pass is measured on the second
            for i in range(0, len(names), 50):
                page.evaluate(JS, names[i:i + 50])

    launch(binary, identity, work / "sweep", sweep)
    parent, kids = logs(work, "sweep")
    faces = sorted(m.group(0)[len("(shared-fontlist) "):] for ln in lines(parent) if (m := FACE.search(ln)))
    (out / f"faces-{identity}.txt").write_text("\n".join(faces) + "\n", encoding="utf-8")
    miss = sum(1 for k in kids for ln in lines(k) if "CAMOU-FL bundled-face-miss" in ln)
    live = sum(1 for k in kids for ln in lines(k) if "CAMOU-FL facename" in ln)
    fams = {m.group(1) for ln in faces if (m := re.match(r"family \((.*?)\) added", ln))}
    print(f"{identity}: names={len(names)} families_with_faces={len(fams)} faces={len(faces)} "
          f"content_logs={len(kids)} bundled-face-miss={miss} facename_lines={live}", flush=True)
    for src in [parent, *kids]:
        with open(src, "rb") as i, gzip.open(out / f"{identity}-{src.name}.gz", "wb") as o:
            shutil.copyfileobj(i, o)
    shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    a = argparse.ArgumentParser()
    a.add_argument("--zip", required=True)
    a.add_argument("--runs", type=int, default=1)  # the workflow passes it to every probe
    args = a.parse_args()
    out = Path(os.environ.get("E2E_MOZ_LOG") or ".ci-work/mozlog")
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="faces-probe-") as tmp:
        binary = unpack(args.zip, Path(tmp))
        print(f"binary: {binary}  BuildID={build_id(binary)}", flush=True)
        for identity in ("windows", "linux", "macos"):
            run(binary, identity, out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
