"""#253 probe: how long does the first lookup of a legacy family name block?

    python3 e2e/probes/other_names_stall.py --binary BIN [--runs 5]

font-other-names-sync.patch (#247) reads the "other family names" on a masked
page's first lookup, so that lookup blocks while the names load. Each run
launches a fresh browser with a Windows identity whose `fonts` are the three
DejaVu legacy names, then measures all three in one page three times in a row
and prints the milliseconds of each call. The first holds the stall; the second
and third are the steady cost. A fast first call is not proof the names
resolved: without the patch a miss returns in a few ms. That question belongs to
patches/legacy-family-names-first-measure.py.
"""

import argparse

from camoufox.sync_api import Camoufox

NAMES = ["DejaVu Sans Condensed", "DejaVu Sans Light", "DejaVu Serif Condensed"]
JS = """(names) => {
  const c = document.createElement('canvas').getContext('2d');
  c.fontKerning = 'none';
  const t0 = performance.now();
  for (const n of names) { c.font = `72px "${n}", monospace`; c.measureText('HxmW0 .8Qgy'); }
  return performance.now() - t0;
}"""


def main() -> int:
    a = argparse.ArgumentParser()
    a.add_argument("--binary", required=True)
    a.add_argument("--runs", type=int, default=5)
    args = a.parse_args()
    firsts = []
    for i in range(args.runs):
        with Camoufox(executable_path=args.binary, os="windows", headless=True, fonts=NAMES, i_know_what_im_doing=True) as b:
            page = b.new_page()
            page.goto("about:blank")
            calls = [page.evaluate(JS, NAMES) for _ in range(3)]
        firsts.append(calls[0])
        print(f"run {i}: {[round(c, 1) for c in calls]} ms", flush=True)
    print(f"first call: min {min(firsts):.1f} ms, max {max(firsts):.1f} ms over {args.runs} fresh browsers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
