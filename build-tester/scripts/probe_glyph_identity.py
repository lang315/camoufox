#!/usr/bin/env python3
"""Detect a character being drawn with a DIFFERENT character's glyph.

The failure this exists for was reported on a macOS host against a Vietnamese
page: `dụng` drew as `d≈ng`, `trợ` as `tr√`, `người` as `ng"∂i`, while `ã à ô è
ì ý` were untouched. That is not a missing font and not a missing glyph. Gecko
draws a missing glyph as a hexbox carrying the codepoint's own digits
(`gfxFontMissingGlyphs.cpp`), and the report contains no hexbox, so every one of
those codepoints WAS matched to a face whose charmap claims it -- and the
outline that came back belonged to another character.

Reading the report's substitutions back through the font files on that host
identifies the pair exactly: the charmap came from the bundled Segoe UI family
and the outlines from the host's Helvetica. U+1EE5 resolves to glyph id 869,
which is `uni1EE5` in Segoe UI and `approxequal` in Helvetica; U+1EDD -> 861 ->
`partialdiff`; U+1EE3 -> 867 -> `radical`. Latin-1 survives because the two
files agree on glyph ids up to about 255 (`atilde` is 109 in both) and diverge
above it, which is why only Vietnamese broke.

THE INVARIANT THIS PROBE MEASURES
---------------------------------
Naming the pair needs the font files. Detecting the class does not, and needs no
reference font, no golden image and no eyeballs: within ONE font at ONE size,
two different characters must not rasterise to the same bitmap. Under this
defect they do -- if U+1EE5 is drawn with approxequal's outline, and U+2248 in
that same font is also approxequal, the two rasterise identically.

So: draw each Vietnamese codepoint and each decoy codepoint separately into a
canvas, hash the pixels, and report any Vietnamese/decoy collision. A collision
between two genuinely distinct glyphs does not otherwise happen.

WHAT THE PROBE PROVES ABOUT ITSELF BEFORE ITS OUTPUT COUNTS
-----------------------------------------------------------
A clean result is worth nothing from an instrument that cannot go red, and this
repo has paid for that lesson more than once (CLAUDE.md, "Verifying spoofing
claims", lessons 3 and 4). Three checks run in the same page, on the same canvas,
in the same launch as the measurement:

  self_equal     hash(U+1EE5) must equal hash(U+1EE5) drawn twice. If it does
                 not, per-draw perturbation (the `fonts:spacing_seed` noise) is
                 defeating pixel comparison and no collision reading from this
                 run means anything.
  self_distinct  hash(U+1EE5) must differ from hash('o'). If it does not, the
                 hash is not discriminating.
  ink            the reference draw must put ink on the canvas at all.

If any of those fails the run reports `invalid` -- never `pass`, never `fail`.
`--prove-red` additionally puts 'o' in BOTH the test set and the decoy set, so
every family must report a collision; a `--prove-red` run that comes back clean
means the comparison is not wired to anything and the probe is broken.

Blanks are recorded, not compared: a codepoint that rasterises to nothing
collides with every other blank for an uninteresting reason. A non-empty
`blanks` list is still reported, because "the page has no glyph for this
codepoint at all" is the other half of the reported symptom.

Findings are collected and triaged at the end. Nothing asserts mid-run: an
assert here would erase every later family's reading, which is the defect this
repo already fixed once in its own guard (`a9f1682`, and the corollary to
lesson 9 in CLAUDE.md).

Usage:
  python probe_glyph_identity.py                      # windows, macos, linux
  python probe_glyph_identity.py --os macos --reps 3
  python probe_glyph_identity.py --prove-red --os macos
  python probe_glyph_identity.py --self-test          # no browser
  python probe_glyph_identity.py --out result.json
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

# Vietnamese: the whole Latin Extended Additional range the report exercised,
# plus the Extended-A/B characters (đ ư ơ) that sit below it.
VIETNAMESE = (
    "ạảãăằẳẵặâấầẩẫậđèẻẽếềểễệìỉĩịòỏõồổỗộơớờởỡợùủũụưứừửữựỳỷỹỵ"
)
# Latin-1 characters that rendered CORRECTLY in the report. If these ever
# collide the defect is not the one described above and the reading needs a
# different explanation.
LATIN1_CONTROL = "ãàôèìýéúíóâêîôû"
# What a wrong glyph id lands on in practice: the symbol block of a text face.
DECOYS = "≈∂√°ǒ”“µ∞±≤≥÷∑∏π∫ΩΔ†‡•…‰¢£¥§¶ªº¿¡¬ƒ«»–—oaeuiy"
# Two generics, two host families, two bundled-only families, and the stack
# facebook.com serves to a Windows UA -- the one in the report.
FAMILIES = [
    "system-ui",
    "sans-serif",
    "serif",
    "Helvetica",
    "'Helvetica Neue'",
    "Arial",
    "'Segoe UI'",
    "'Segoe UI Historic','Segoe UI',Helvetica,Arial,sans-serif",
]

_JS = r"""
(args) => {
  const {test, decoy, fams} = args;
  const hash = (d) => { let h = 2166136261 >>> 0;
    for (let i = 0; i < d.length; i++) { h ^= d[i]; h = Math.imul(h, 16777619) >>> 0; }
    return h >>> 0; };
  const cv = document.createElement('canvas');
  cv.width = 96; cv.height = 96;
  const cx = cv.getContext('2d', {willReadFrequently: true});
  const draw = (ch, fam) => {
    cx.clearRect(0, 0, 96, 96);
    cx.fillStyle = '#000';
    cx.font = '64px ' + fam;
    cx.textBaseline = 'alphabetic';
    cx.fillText(ch, 8, 74);
    const d = cx.getImageData(0, 0, 96, 96).data;
    let ink = 0;
    for (let i = 3; i < d.length; i += 4) if (d[i] > 8) ink++;
    return {h: hash(d), ink: ink};
  };
  const out = {selftest: {}, families: {}};
  const a = draw('ụ', 'Helvetica');
  const b = draw('ụ', 'Helvetica');
  const c = draw('o', 'Helvetica');
  out.selftest = {self_equal: a.h === b.h, self_distinct: a.h !== c.h, ink: a.ink};
  for (const fam of fams) {
    const seen = {};
    for (const ch of decoy) {
      const r = draw(ch, fam);
      if (r.ink && seen[r.h] === undefined) seen[r.h] = ch;
    }
    const collisions = [], blanks = [];
    for (const ch of test) {
      const r = draw(ch, fam);
      if (!r.ink) { blanks.push(ch); continue; }
      if (seen[r.h] !== undefined) collisions.push([ch, seen[r.h]]);
    }
    out.families[fam] = {collisions: collisions, blanks: blanks.join('')};
  }
  return out;
};
"""


def triage(result):
    """Turn one run's raw readings into (verdict, tripwires).

    Split out from the browser so `--self-test` can exercise it directly: the
    decision of what counts as red is the part worth testing without a launch.
    """
    st = result.get("selftest") or {}
    if not (st.get("self_equal") and st.get("self_distinct") and st.get("ink", 0) > 0):
        return "invalid", [("instrument", st)]
    tripwires = []
    for family, row in result.get("families", {}).items():
        if row.get("collisions"):
            tripwires.append((family, {"collisions": row["collisions"]}))
        if row.get("blanks"):
            tripwires.append((family, {"blanks": row["blanks"]}))
    return ("fail" if tripwires else "pass"), tripwires


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def provenance(executable_path=None):
    """Name the binary these readings came from.

    A reading is not a measurement until you know which binary produced it
    (CLAUDE.md lesson 9), and this probe launches through pythonlib rather than
    a path the caller passed, so the resolver is the only thing that knows.
    """
    out = {}
    if executable_path:
        # An explicitly named binary is the whole provenance: pythonlib's
        # resolver did not choose it and cannot describe it.
        binary = Path(executable_path)
        out["binary"] = str(binary)
        for name in ("XUL", "libxul.so", "xul.dll"):
            payload = binary.parent / name
            if payload.is_file():
                out["payload"] = name
                out["payload_sha256"] = _sha256(payload)
                break
        else:
            out["payload"] = "not found beside the binary"
        return out
    try:
        from camoufox import pkgman

        out["version"] = pkgman.installed_verstr()
        resources = Path(pkgman.get_path(""))
        out["resources"] = str(resources)
        for name in ("XUL", "libxul.so", "xul.dll"):
            payload = resources.parent / "MacOS" / name
            if not payload.is_file():
                payload = resources / name
            if payload.is_file():
                out["payload"] = name
                out["payload_sha256"] = _sha256(payload)
                break
        else:
            out["payload"] = "not found -- provenance is the version string only"
    except Exception as exc:  # pragma: no cover - environment dependent
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def run_once(target_os, prove_red=False, headless=False, executable_path=None):
    from camoufox.sync_api import Camoufox

    test = VIETNAMESE + LATIN1_CONTROL + ("o" if prove_red else "")
    extra = {"executable_path": executable_path} if executable_path else {}
    with Camoufox(headless=headless, os=target_os, locale="vi-VN", **extra) as browser:
        page = browser.new_page()
        page.goto("data:text/html,<meta charset=utf-8><body>glyph identity probe")
        raw = page.evaluate(_JS, {"test": test, "decoy": DECOYS, "fams": FAMILIES})
    verdict, tripwires = triage(raw)
    return {
        "os": target_os,
        "prove_red": prove_red,
        "verdict": verdict,
        "selftest": raw["selftest"],
        "tripwires": [{"family": f, **d} for f, d in tripwires],
        "families_measured": list(raw["families"]),
        "codepoints_measured": len(test),
    }


def self_test():
    """Exercise `triage` with no browser: it must call red red and green green."""
    good = {"selftest": {"self_equal": True, "self_distinct": True, "ink": 500},
            "families": {"Arial": {"collisions": [], "blanks": ""}}}
    assert triage(good) == ("pass", []), triage(good)

    red = {"selftest": {"self_equal": True, "self_distinct": True, "ink": 500},
           "families": {"Arial": {"collisions": [["ụ", "≈"]], "blanks": ""}}}
    verdict, trips = triage(red)
    assert verdict == "fail" and trips[0][1]["collisions"] == [["ụ", "≈"]], trips

    blank = {"selftest": {"self_equal": True, "self_distinct": True, "ink": 500},
             "families": {"Arial": {"collisions": [], "blanks": "ậạ"}}}
    assert triage(blank)[0] == "fail", triage(blank)

    # A run whose instrument did not prove itself is neither pass nor fail.
    for broken in ({"self_equal": False, "self_distinct": True, "ink": 500},
                   {"self_equal": True, "self_distinct": False, "ink": 500},
                   {"self_equal": True, "self_distinct": True, "ink": 0}):
        out = {"selftest": broken,
               "families": {"Arial": {"collisions": [], "blanks": ""}}}
        assert triage(out)[0] == "invalid", broken
    print("self-test: 6/6 OK (pass, collision, blank, and three invalid shapes)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--os", dest="targets", action="append",
                    choices=["windows", "macos", "linux"],
                    help="spoofed OS to measure (repeatable; default: all three)")
    ap.add_argument("--reps", type=int, default=1,
                    help="runs per OS; the font subset is randomised per launch")
    ap.add_argument("--prove-red", action="store_true",
                    help="put 'o' in both sets, so every family MUST collide")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--executable-path",
                    help="binary to measure; without it pythonlib picks its own "
                         "download, which is the UPSTREAM build and carries none "
                         "of this fork's font work")
    ap.add_argument("--out", help="write the full result as JSON")
    ap.add_argument("--self-test", action="store_true",
                    help="exercise the triage logic; launches no browser")
    args = ap.parse_args()

    if args.self_test:
        self_test()
        return 0

    targets = args.targets or ["windows", "macos", "linux"]
    runs = []
    for target in targets:
        for _ in range(args.reps):
            run = run_once(target, prove_red=args.prove_red,
                           headless=args.headless,
                           executable_path=args.executable_path)
            runs.append(run)
            print(f"[{target}] {run['verdict']} selftest={json.dumps(run['selftest'])}")
            for trip in run["tripwires"]:
                print("    tripwire:", json.dumps(trip, ensure_ascii=False))

    result = {"provenance": provenance(args.executable_path), "host": sys.platform,
              "vietnamese_codepoints": len(VIETNAMESE),
              "latin1_control": LATIN1_CONTROL, "decoys": len(DECOYS),
              "families": FAMILIES, "runs": runs}
    if args.out:
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print("wrote", args.out)

    invalid = [r for r in runs if r["verdict"] == "invalid"]
    failed = [r for r in runs if r["verdict"] == "fail"]
    print(f"\n{len(runs)} runs: {len(failed)} fail, {len(invalid)} invalid, "
          f"{len(runs) - len(failed) - len(invalid)} pass")
    if args.prove_red:
        # Under --prove-red a clean run is the broken outcome, not the good one.
        if failed and not invalid and len(failed) == len(runs):
            print("prove-red: OK -- every run went red, the comparison is live")
            return 0
        print("prove-red: BROKEN -- a run did not go red; readings are worthless")
        return 2
    if invalid:
        return 2
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
