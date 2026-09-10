#!/usr/bin/env python3
r"""#87: run the #44 font guard's probes against a Windows Camoufox binary on a
native Windows host.

The smoke workflow is Linux-only -- `.github/workflows/smoke.yml` runs on
ubuntu-24.04 and declares no other runner -- and `build-tester/run_tests.sh` has
no Windows branch, so the question #87 asks cannot be answered by extending
either. This is a standalone Playwright script, run by hand on a Windows host
against a Windows artifact.

The question: after the lookup-time allowlist flip, are host-installed Windows
fonts outside the launch list still unreachable by content? Before the flip
`ApplyWhitelist()` physically deleted them from the platform font list; now they
survive in the list and are filtered at lookup time by
`MaskedFontListAppliesTo` / `MaskedFontListBlocks` and, per context, by
`CamouIsFontAllowed`. A Linux CI job cannot see this: `bundle/fontconfig/linux/
fonts.conf` excludes host fonts there, so the host-leak question is vacuous on
the runner (CLAUDE.md, "Verifying spoofing claims" lesson 3).

Three launches, one measurement each:

  | launch                                  | host family outside the list | meaning          |
  |-----------------------------------------|------------------------------|------------------|
  | bare (no `fonts` key, no `setFontList`) | reachable                    | POSITIVE CONTROL |
  | `CAMOU_CONFIG` with a `fonts` key       | not reachable                | the measurement  |
  | bare + per-context `setFontList`        | not reachable                | the measurement  |

The bare launch is a control, not a third expectation.
`gfxPlatformFontList::MaskedFontListAppliesTo` returns false when there is no
allowlist, so host fonts ARE reachable without a `fonts` key -- and that is what
proves this probe can see host fonts at all. If the bare launch cannot reach the
chosen family, the two refusals below are not evidence of anything and the run
is reported `invalid`, never `pass` and never `fail`.

Usage:
  python probe_windows_fonts.py --executable-path "C:\path\to\camoufox.exe" \
      --bundle-dir "C:\path\to\extracted\fonts" [--out result.json] [--headful]

--bundle-dir is required for a real run; there is no fallback to a repo checkout.
  python probe_windows_fonts.py --self-test     # no browser, no fontTools

Exit status: 0 only when every verdict is `pass`; 1 otherwise, including
`invalid`.
"""

import argparse
import json
import math
import os
import platform
import sys
import urllib.parse
from pathlib import Path

# Advance widths are floats coming back through JSON. Two families that resolve
# to the same face measure bit-identically in practice; this tolerance only
# absorbs float round-tripping.
EPS = 0.01

# Bounds the length of the data: URL that carries the probe list into the page.
# Only the tail of the alphabetical candidate list is dropped, so the family
# actually chosen (first alphabetically that resolves) is never affected; the
# leak survey below is what gets truncated, and the JSON records that it was.
MAX_PROBE_FAMILIES = 400

# The DOM node the page hands its results over through, copied from
# build-tester/scripts/runner.py:83-112. It has to be a node and not a JS
# global: page.evaluate() runs in juggler's isolated world and cannot see
# globals the page wrote, but the DOM is shared between worlds.
RESULTS_NODE = "__camoufoxResults__"
READ_RESULTS = (
    "() => { const n = document.getElementById(%r); return n ? n.textContent : null; }"
    % RESULTS_NODE
)
READ_DATA_FL = '() => document.documentElement.getAttribute("data-fl")'

# Two DIFFERENT impossible families. Both must fall back to the same face, so
# both must measure the same width. If they ever differ, "width differs from the
# absent reference" has stopped meaning "this family resolved" and every verdict
# in the run is void (CLAUDE.md lesson 4: a reference is only a control if
# something establishes the two sides are comparable).
ABSENT_1 = "__CamouAbsentRef__0001"
ABSENT_2 = "__NoSuchFamily__12345"

# Families Windows classifies as FontVisibility::Base -- gfxDWriteFontList.cpp:1179
# checks kBaseFonts, defined in StandardFonts-win10.inc, and all five appear
# there. They seed the launch list; see build_launch_list for why.
WINDOWS_BASE_SEED = ["Arial", "Calibri", "Consolas", "Courier New", "Georgia"]

# The version camoufox-152 needs. Recorded in every result and warned about when
# it differs; see the note where it is checked for why this does not refuse.
PLAYWRIGHT_PIN = "1.55.0"

# Measured at 48px with an explicit monospace fallback, exactly as the smoke
# arms do, so a family that does NOT resolve reads as the monospace baseline
# rather than as zero.
PAGE_JS = r"""
(function () {
  var out = {}, err = null;
  try {
    var c = document.createElement('canvas').getContext('2d');
    var S = 'mmmmmmmmmmlliWWWWWWW@#$%%^&*()_+';
    var w = function (f) {
      c.font = '48px "' + f + '", monospace';
      return c.measureText(S).width;
    };
    out['__absent1__'] = w(%(absent1)s);
    out['__absent2__'] = w(%(absent2)s);
    var fams = %(families)s;
    for (var i = 0; i < fams.length; i++) out[fams[i]] = w(fams[i]);
    // U+FFFD exercises codepoint fallback (SystemFindFontForChar /
    // GlobalFontFallback), which the family-name probes do not touch at all.
    // Reported, never scored: under a masked launch there is no reference
    // guaranteed to differ from it, so a verdict here could not be trusted.
    c.font = '48px "__NoSuchFamilyAtAll6__"';
    out['__fffd__'] = c.measureText('\uFFFD').width;
    c.font = '48px monospace';
    out['__monospace__'] = c.measureText(S).width;
  } catch (e) {
    err = String(e);
  }
  var n = document.createElement('script');
  n.type = 'application/json';
  n.id = '%(node)s';
  // Tag non-finite numbers instead of letting JSON.stringify flatten them to
  // null, which is indistinguishable from "never measured". runner.py's
  // _revive() is the consumer half of this.
  n.textContent = JSON.stringify({ results: out, error: err }, function (k, v) {
    return (typeof v === 'number' && !isFinite(v))
      ? { __nonfinite__: String(v) } : v;
  });
  document.documentElement.appendChild(n);
})();
"""

# Runs at document-start in juggler's isolated world. It marks the document
# through a DOM attribute, never a window global, for the same reason the
# results come back through a node.
#
# `applied: true` proves the setFontList call ran on the document that was then
# measured. It does NOT prove the gate armed: if the context id fell to 0 on the
# way down (CLAUDE.md lesson 5, the four-hop GetDocument chain), CamouIsFontAllowed
# allows every family and this arm reads `fail`. That is fail-closed -- a
# disarmed gate is itself the defect #87 is about -- but do not read
# `applied: true` as ruling it out.
INIT_JS = (
    '(() => {'
    ' const saw = (typeof window.setFontList === "function");'
    ' let applied = false, err = null;'
    ' if (saw) { try { window.setFontList(%s); applied = true; }'
    '            catch (e) { err = String(e); } }'
    ' const mark = () => { try { document.documentElement.setAttribute('
    '   "data-fl", JSON.stringify({saw, applied, err})); } catch (e) {} };'
    ' mark(); document.addEventListener("DOMContentLoaded", mark);'
    '})()'
)


# --------------------------------------------------------------------------
# Font enumeration
# --------------------------------------------------------------------------

def _names_from_file(path):
    """Family names (nameID 1 and 16) out of one font file. Empty on any error:
    C:\\Windows\\Fonts holds .fon and other formats fontTools cannot open."""
    from fontTools.ttLib import TTCollection, TTFont  # lazy: --self-test needs neither

    ext = path.suffix.lower()
    if ext not in (".ttf", ".otf", ".ttc", ".otc"):
        return set()
    try:
        faces = (
            list(TTCollection(str(path)).fonts)
            if ext in (".ttc", ".otc")
            else [TTFont(str(path), fontNumber=0, lazy=True)]
        )
    except Exception:
        return set()
    out = set()
    for face in faces:
        try:
            records = list(face["name"].names)
        except Exception:
            continue
        # Per RECORD, not per face. Macintosh-platform records generally sort
        # before Windows ones, so a single bad toUnicode() in a face-wide try
        # would cost every later nameID 1/16 record and with it the family name.
        for rec in records:
            try:
                if rec.nameID in (1, 16):
                    s = rec.toUnicode()
                    # A quote or backslash cannot go in the CSS font
                    # shorthand this probe builds; a comma would split the
                    # per-context list, since setFontList takes a comma-delimited
                    # DOMString (font-list-spoofing.patch:236) while the `fonts`
                    # JSON list does not -- the two masked launches would then be
                    # asking different questions. Real family names carry none.
                    if s and not set('"\\,') & set(s):
                        out.add(s.strip())
            except Exception:
                continue
    return out


def bundle_families(dirs):
    """Every family name the Windows *artifact* carries.

    NOT `bundle/fonts/windows`. `Makefile:190` is
    `package-windows: ... --fonts macos linux` -- the packager bundles every OS
    except the target's own, because the host supplies its own (CLAUDE.md
    lesson 1). A Windows build therefore ships the macOS and Linux families and
    ships no Windows ones. Subtracting the wrong directory would leave bundled
    macOS/Linux names in the candidate pool, and a "reachable" reading there
    would be the bundled copy rather than anything the host installed.

    `scripts/package.py:91-97` flattens the per-OS subdirectories for non-Linux
    targets, so the artifact's font directory is flat; the walk is recursive so
    the same code reads either shape.

    Returns {casefolded name: first-seen original spelling}.
    """
    out = {}
    for d in dirs:
        for p in sorted(Path(d).rglob("*")):
            if p.is_file():
                for name in _names_from_file(p):
                    out.setdefault(name.casefold(), name)
    return out


def host_families(root=r"C:\Windows\Fonts"):
    """Family names installed on the host.

    Only the machine-wide directory. Per-user installs under
    %LOCALAPPDATA%\\Microsoft\\Windows\\Fonts are deliberately not enumerated,
    and are named in the NOT-verified section rather than silently skipped.

    Returns {casefolded name: (original spelling, source file)}.
    """
    out = {}
    base = Path(root)
    if not base.is_dir():
        return out
    for p in sorted(base.iterdir()):
        if p.is_file():
            for name in _names_from_file(p):
                out.setdefault(name.casefold(), (name, str(p)))
    return out


# --------------------------------------------------------------------------
# Pure logic -- everything below is exercised by --self-test
# --------------------------------------------------------------------------

def _revive(value):
    """Undo the tagging the page applied to values JSON cannot carry.

    Copied from build-tester/scripts/runner.py:89-99. The probe adopted the
    results-node pattern but originally not this half of it, so a NaN or
    Infinity width arrived as an untagged `null` -- indistinguishable from
    "never measured" and, once subtracted, a TypeError.
    """
    if isinstance(value, list):
        return [_revive(item) for item in value]
    if isinstance(value, dict):
        if "__undefined__" in value:
            return None
        nonfinite = value.get("__nonfinite__")
        if nonfinite is not None:
            return float(nonfinite)
        return {key: _revive(item) for key, item in value.items()}
    return value


def resolved(widths, family, absent_key="__absent1__"):
    """Did `family` resolve to a real face, rather than falling back?

    The reference is a family that CANNOT exist, measured in the same document,
    same thread, same world and same launch as the value under test, so the two
    sides are comparable by construction (CLAUDE.md lesson 4). The one way this
    reads wrong is a real face whose advance width happens to equal the fallback
    face's; `choose_host_family` rules that out for the family it picks, because
    it only picks families that already differ under the bare launch.

    Returns True (resolved), False (fell back), or None meaning NOT MEASURED --
    the key is absent, or the width came back null (JSON.stringify turns NaN and
    Infinity into null), or it revived to a non-finite float. None must never be
    scored: `abs(inf - 80.0) > EPS` is True and every NaN comparison is False,
    so an unmeasured family would otherwise read as a confident fail or a
    confident pass from a measurement that never happened.
    """
    a, b = widths.get(family), widths.get(absent_key)
    if a is None or b is None:
        return None
    if not (math.isfinite(a) and math.isfinite(b)):
        return None
    return abs(a - b) > EPS


def choose_host_family(candidates, bare_widths):
    """Pick the host-only family to headline, deterministically.

    `candidates` is host minus bundle minus the launch list, already sorted.
    A candidate is usable only if it resolved under the BARE launch: a family
    that measures the fallback width there is either not really installed or
    happens to share the fallback face's width, and in both cases its refusal
    under a masked launch would be indistinguishable from a working gate.
    Filtering on the bare launch is what makes the later comparison a control.

    Returns (family, reason). `family` is None when nothing qualifies.
    """
    survivors = [f for f in candidates if resolved(bare_widths, f)]
    if not survivors:
        return None, (
            "CONTROL FAILED: no host-only family resolved under the bare launch: "
            "of %d candidates, "
            "every one measured the absent-family fallback width. Either none are "
            "really installed, or the probe cannot see host fonts at all."
            % len(candidates)
        )
    return survivors[0], (
        "first alphabetically of the %d host-only families (out of %d probed) that "
        "resolved under the bare launch, where no launch-level mask applies"
        % (len(survivors), len(candidates))
    )


def _v(launch, probe, status, reason):
    return {"launch": launch, "probe": probe, "status": status, "reason": reason}


def judge(results):
    """Score a completed result object.

    Returns (verdicts, overall). `overall` is "invalid" if any verdict is
    invalid, else "fail" if any is fail, else "pass". A measurement whose own
    control failed is emitted as "unscored" and never as pass or fail -- a run
    that measured nothing must not print a conclusion.
    """
    verdicts = []
    host = results.get("host_family")
    runs = [(k, results.get(k) or {}) for k in ("bare", "launch_list", "per_context")]

    # 1. Is width comparison meaningful at all in each launch?
    void = set()
    for name, run in runs:
        w = run.get("widths") or {}
        a1, a2 = w.get("__absent1__"), w.get("__absent2__")
        # The page script is one try block and the absent references are measured
        # FIRST, so a throw at family i leaves i+1..N unmeasured while both
        # references survive. Without this the void check below cannot fire and
        # the partial run scores normally.
        page_error = run.get("page_error")
        if page_error:
            void.add(name)
            verdicts.append(_v(name, "page-script", "invalid",
                               "the page script threw: %s. Whatever it measured before "
                               "that is a partial run, so nothing in this launch can be "
                               "scored." % page_error))
        if a1 is None or a2 is None:
            void.add(name)
            verdicts.append(_v(name, "absent-reference", "invalid",
                               "no absent-family reference was measured, so nothing in "
                               "this launch can be scored."))
        elif not (math.isfinite(a1) and math.isfinite(a2)):
            void.add(name)
            verdicts.append(_v(name, "absent-reference", "invalid",
                               "an absent-family reference is not finite (%s, %s), so "
                               "no width in this launch can be compared." % (a1, a2)))
        elif abs(a1 - a2) > EPS:
            void.add(name)
            verdicts.append(_v(name, "absent-reference", "invalid",
                               "two different impossible families measured %s and %s. "
                               "Width no longer distinguishes a hit from a miss, so "
                               "every reading in this launch is void." % (a1, a2)))

    # 2. Positive control: can the probe see host fonts at all?
    bare_w = (results.get("bare") or {}).get("widths") or {}
    if not host:
        verdicts.append(_v("bare", "host-family-selection", "invalid",
                           results.get("host_family_reason")
                           or "no host-only family could be chosen."))
        control_ok = False
    elif "bare" in void:
        control_ok = False
    else:
        control_ok = bool(resolved(bare_w, host))
        if not control_ok:
            verdicts.append(_v("bare", host, "invalid",
                               "CONTROL FAILED: %r is not reachable even under a bare "
                               "launch, where MaskedFontListAppliesTo returns false "
                               "because there is no allowlist. The probe cannot see "
                               "host fonts, so the refusals below are not evidence."
                               % host))
        else:
            verdicts.append(_v("bare", host, "pass",
                               "positive control holds: %r resolves under a bare "
                               "launch (%s vs absent %s), so the probe can see host "
                               "fonts." % (host, bare_w.get(host),
                                           bare_w.get("__absent1__"))))

    # 3. Per-launch control: did the font stack survive the mask at all?
    #    Without this, "the host family was refused" is indistinguishable from
    #    "no font resolved because the bundled fonts never loaded on Windows".
    #    At least ONE listed family must resolve, not all: any single one of
    #    them could BE the fallback face and would read as unresolved wrongly
    #    (CLAUDE.md lesson 4).
    in_list = results.get("in_list_probes") or []
    stack_ok = {}
    for name in ("launch_list", "per_context"):
        w = (results.get(name) or {}).get("widths") or {}
        if name in void:
            stack_ok[name] = False
            continue
        hits = [f for f in in_list if resolved(w, f)]
        stack_ok[name] = bool(hits)
        if not hits:
            verdicts.append(_v(name, "in-list-control", "invalid",
                               "CONTROL FAILED: none of the %d families that ARE on "
                               "the list resolved. The font stack is not working in "
                               "this launch, so a refusal proves nothing about the "
                               "gate." % len(in_list)))
        else:
            verdicts.append(_v(name, "in-list-control", "pass",
                               "%d of %d listed families resolved, so the font stack "
                               "is live in this launch." % (len(hits), len(in_list))))

    # 4. The per-context arm additionally needs proof that setFontList ran on
    #    the document that was measured. A context with no list is allowed
    #    everything, and its result would say nothing.
    fl_raw = (results.get("per_context") or {}).get("data_fl")
    fl = {}
    try:
        fl = json.loads(fl_raw) if fl_raw else {}
    except (TypeError, ValueError):
        fl = {}
    setter_ok = bool(fl.get("applied"))
    if not setter_ok:
        verdicts.append(_v("per_context", "setFontList", "invalid",
                           "SETUP INVALID: data-fl is %r, so setFontList did not run "
                           "on the document that was measured." % (fl_raw,)))
    else:
        verdicts.append(_v("per_context", "setFontList", "pass",
                           "data-fl reports the per-context list was applied to the "
                           "measured document."))

    # 5. The measurements themselves.
    #
    # The survey below runs over the candidates the BARE launch proved reachable,
    # not over every name fontTools could read. A family Firefox never loaded
    # would measure the fallback width under a mask whatever the gate did, so
    # counting it as "collapsed" would inflate a pass with families that were
    # never a measurement (CLAUDE.md lesson 4).
    candidates = [f for f in (results.get("candidates") or [])
                  if resolved(bare_w, f)] if "bare" not in void else []
    results["survey_base"] = len(candidates)
    for name, needs in (("launch_list", stack_ok.get("launch_list")),
                        ("per_context", stack_ok.get("per_context") and setter_ok)):
        w = (results.get(name) or {}).get("widths") or {}
        if not host or not control_ok or not needs or name in void:
            verdicts.append(_v(name, host or "?", "unscored",
                               "not scored: a control for this launch failed, so the "
                               "reading carries no information."))
            continue
        # `resolved` returns None for a family that was never measured. That is
        # SETUP INVALID, not a refusal: a width the page never produced is not
        # evidence that the gate withheld the font.
        r = resolved(w, host)
        if r is None:
            verdicts.append(_v(name, host, "invalid",
                               "SETUP INVALID: %r has no usable width in this launch "
                               "(%r). The measurement never happened, so this is not "
                               "evidence that the family was refused."
                               % (host, w.get(host, "<key absent>"))))
        elif r:
            verdicts.append(_v(name, host, "fail",
                               "#87: %r is a host-installed family outside the list and "
                               "content still resolved it (%s vs absent %s)."
                               % (host, w.get(host), w.get("__absent1__"))))
        else:
            verdicts.append(_v(name, host, "pass",
                               "%r is outside the list and content could not resolve it "
                               "(%s == absent %s)."
                               % (host, w.get(host), w.get("__absent1__"))))
        # The same question asked of every host-only family, not just the
        # headline one. A partial leak is the shape a single-family probe would
        # miss. Unmeasured families are counted separately: folding them into
        # "collapsed" is what turned a thrown page script into a green pass.
        scored = {f: resolved(w, f) for f in candidates}
        leaked = [f for f, x in scored.items() if x is True]
        unmeasured = [f for f, x in scored.items() if x is None]
        results.setdefault("leaked", {})[name] = leaked
        results.setdefault("unmeasured", {})[name] = unmeasured
        if unmeasured:
            verdicts.append(_v(name, "host-only-survey", "invalid",
                               "SETUP INVALID: %d of %d host-only families have no usable "
                               "width in this launch, e.g. %s. The survey cannot say they "
                               "collapsed when they were never measured."
                               % (len(unmeasured), len(candidates), unmeasured[:5])))
        elif leaked and not (len(leaked) == 1 and leaked[0] == host):
            verdicts.append(_v(name, "host-only-survey", "fail",
                               "#87: %d of the %d host-only families that WERE reachable "
                               "in the bare launch still resolved, e.g. %s."
                               % (len(leaked), len(candidates), leaked[:5])))
        elif not leaked:
            verdicts.append(_v(name, "host-only-survey", "pass",
                               "all %d host-only families that WERE reachable in the bare "
                               "launch collapsed to the absent-family width."
                               % len(candidates)))

    # 6. Sharpener: families the artifact DOES bundle but that are NOT on the
    #    launch list must be refused too. Both refused is the pass shape; these
    #    resolving while the host family is refused would mean the launch-level
    #    filter is not filtering at all.
    unlisted = results.get("bundled_unlisted_probes") or []
    if unlisted and "launch_list" not in void:
        w = (results.get("launch_list") or {}).get("widths") or {}
        still = [f for f in unlisted if resolved(w, f)]
        if not stack_ok.get("launch_list"):
            # "all refused" is what a dead font stack looks like too, so this
            # says nothing once the in-list control has failed.
            verdicts.append(_v("launch_list", "bundled-unlisted", "unscored",
                               "not scored: the in-list control for this launch failed."))
        elif len(still) == len(unlisted):
            verdicts.append(_v("launch_list", "bundled-unlisted", "fail",
                               "all %d bundled families that are NOT on the launch list "
                               "still resolved, so the launch-level filter is not "
                               "filtering." % len(unlisted)))
        else:
            verdicts.append(_v("launch_list", "bundled-unlisted", "pass",
                               "%d of %d bundled-but-unlisted families were refused."
                               % (len(unlisted) - len(still), len(unlisted))))

    if any(v["status"] == "invalid" for v in verdicts):
        overall = "invalid"
    elif any(v["status"] == "fail" for v in verdicts):
        overall = "fail"
    else:
        overall = "pass"
    return verdicts, overall


def spread(seq, n):
    """n items spread evenly across seq, so a sample of a sorted font list is
    not five near-identical neighbours (all 'Noto Sans <script>', say)."""
    if not seq or n <= 0:
        return []
    if len(seq) <= n:
        return list(seq)
    step = len(seq) / float(n)
    return [seq[int(i * step)] for i in range(n)]


def build_launch_list(bundled, host, size):
    """The `fonts` list both masked launches use.

    Seeded with Windows base families, then filled from what the artifact
    bundles. Returns (launch_list, seeds_used, seeds_missing).

    Two things this fixes, both of which would have made the in-list control
    read wrong rather than read false (CLAUDE.md lesson 4):

    * The seeds are HOST families that are ON the list. That is what makes the
      measurement a per-family discriminator rather than a statement about
      bundled fonts loading at all: in one masked launch, a listed host family
      must resolve while an unlisted host family must not. Adding them to the
      list also removes them from the candidate pool by construction, since
      candidates are host minus bundle minus list.
    * They are `FontVisibility::Base` on Windows -- `gfxDWriteFontList.cpp:1179`
      checks `kBaseFonts`, defined in `StandardFonts-win10.inc` -- so
      `font.visibility.level` cannot hide them. A bundled macOS or Linux family
      is `User` there (the same function's fallthrough), so if the whole list
      were bundled families, "no listed family resolved" could mean the
      visibility pref rather than a broken allowlist.

    Dot-prefixed names are dropped. `gfxMacPlatformFontList.mm:185` maps a
    leading '.' to `FontVisibility::Hidden`; the Windows equivalent has no such
    rule, so their behaviour differs by platform for reasons unrelated to the
    gate under test, which makes them a poor control either way. 46 of them ship
    in `bundle/fonts/macos` and they sort to the front alphabetically, so an
    unfiltered list is made entirely of them.
    """
    seeds_used = [s for s in WINDOWS_BASE_SEED if s.casefold() in host]
    seeds_missing = [s for s in WINDOWS_BASE_SEED if s.casefold() not in host]
    rest = [f for f in sorted(bundled.values(), key=lambda s: (s.casefold(), s))
            if not f.startswith(".")
            and f.casefold() not in {s.casefold() for s in seeds_used}]
    return seeds_used + rest[:max(0, size - len(seeds_used))], seeds_used, seeds_missing


# --------------------------------------------------------------------------
# Browser
# --------------------------------------------------------------------------

def build_url(families):
    """The measurement runs in the PAGE world, as an inline <script> in the
    document, not through page.evaluate() -- evaluate runs in juggler's
    isolated world, and the page world is the one a fingerprinter occupies.
    Results come back through the DOM node instead.
    """
    js = PAGE_JS % {
        "absent1": json.dumps(ABSENT_1),
        "absent2": json.dumps(ABSENT_2),
        "families": json.dumps(list(families)),
        "node": RESULTS_NODE,
    }
    html = "<!doctype html><meta charset=utf-8><title>probe</title><script>%s</script>" % js
    return "data:text/html;charset=utf-8," + urllib.parse.quote(html, safe="")


def measure(exe, families, camou_config, per_context_list, headful, timeout=60000):
    """One launch, one context, one page -- the strongest isolation available.

    headless is the default. These are advance-width measurements, which need no
    GL context, and there is no xvfb on Windows and no desktop on an SSH
    session. (The headless caveat in build-tester/scripts/runner.py:35-51 is
    about WebGL checks failing open; nothing here touches WebGL.)
    """
    from importlib.metadata import PackageNotFoundError, version as _pkg_version
    from playwright.sync_api import sync_playwright  # lazy: --self-test needs no playwright

    try:
        pw_version = _pkg_version("playwright")
    except PackageNotFoundError:
        pw_version = "unknown"

    url = build_url(families)
    with sync_playwright() as pw:
        browser = pw.firefox.launch(
            executable_path=exe,
            headless=not headful,
            env={**os.environ, "CAMOU_CONFIG": json.dumps(camou_config)},
        )
        try:
            ctx = browser.new_context()
            page = ctx.new_page()
            # add_init_script AFTER new_page, deliberately. new_page lands on
            # about:blank first, and playwright runs init scripts on every
            # navigation, so a script registered earlier would spend its
            # one-shot setFontList on about:blank and the measured document
            # would have no list at all (CLAUDE.md lesson 4, last bullet).
            if per_context_list is not None:
                ctx.add_init_script(INIT_JS % json.dumps(",".join(per_context_list)))
            page.goto(url, timeout=timeout)
            page.wait_for_selector("#" + RESULTS_NODE, state="attached", timeout=timeout)
            raw = page.evaluate(READ_RESULTS)
            # Read data-fl after goto returns: documentElement is null when the
            # init script first fires, so the value that counts is the one the
            # DOMContentLoaded re-mark wrote.
            data_fl = page.evaluate(READ_DATA_FL)
        finally:
            browser.close()
    payload = _revive(json.loads(raw)) if raw else {}
    return {
        # Recorded, not assumed: camoufox-152 needs playwright 1.55.0 exactly and
        # a newer one reports a clean-looking 0/0 (CLAUDE.md lesson 6).
        "playwright": pw_version,
        "widths": payload.get("results") or {},
        "page_error": payload.get("error"),
        "data_fl": data_fl,
        "url_len": len(url),
    }


# --------------------------------------------------------------------------
# Self-test
# --------------------------------------------------------------------------

def _canned(host_w=120.0, list_w=None, ctx_w=None, absent=80.0,
            data_fl='{"saw":true,"applied":true,"err":null}', absent2=None):
    """A minimal result object shaped exactly like a real run's."""
    def run(host, extra=None):
        w = {"__absent1__": absent, "__absent2__": absent if absent2 is None else absent2,
             "Host One": host, "Listed A": absent + 40, "Listed B": absent + 41,
             "Unlisted X": absent, "__fffd__": 9.0, "__monospace__": absent}
        w.update(extra or {})
        return {"widths": w, "data_fl": None, "page_error": None}
    return {
        "host_family": "Host One",
        "host_family_reason": "canned",
        "candidates": ["Host One"],
        "in_list_probes": ["Listed A", "Listed B"],
        "bundled_unlisted_probes": ["Unlisted X"],
        "bare": run(host_w),
        "launch_list": run(absent if list_w is None else list_w),
        "per_context": dict(run(absent if ctx_w is None else ctx_w), data_fl=data_fl),
    }


def self_test():
    """Exercise the selection rule and every verdict shape on canned inputs.
    Needs neither playwright nor fontTools nor a browser."""
    fails = []

    def check(label, cond):
        print("  %-56s %s" % (label, "ok" if cond else "FAILED"))
        if not cond:
            fails.append(label)

    print("selection:")
    bare = {"__absent1__": 80.0, "Alpha": 80.0, "Beta": 120.0, "Gamma": 130.0}
    f, why = choose_host_family(["Alpha", "Beta", "Gamma"], bare)
    check("skips a candidate whose width == absent, takes next", f == "Beta")
    check("reason names the survivor count", "2 host-only" in why)
    f, why = choose_host_family(["Alpha"], bare)
    check("returns None when nothing resolves", f is None)
    check("None comes with a reason", "no host-only family resolved" in why)
    check("and carries the CONTROL FAILED prefix the operator greps for",
          why.startswith("CONTROL FAILED:"))
    check("first alphabetically among survivors",
          choose_host_family(["Gamma", "Beta"], bare)[0] == "Gamma")
    hostf = {"arial": ("Arial", "a"), "noto sans": ("Noto Sans", "b"),
             "segoe ui": ("Segoe UI", "c")}
    bundle = {"noto sans": "Noto Sans"}
    launch = {"arial"}
    cands = sorted(n for k, (n, _) in hostf.items() if k not in bundle and k not in launch)
    check("candidates exclude bundle and launch list", cands == ["Segoe UI"])

    print("verdicts:")
    v, o = judge(_canned())
    check("clean run is pass", o == "pass")
    check("clean run scores the host family in both masked launches",
          len([x for x in v if x["probe"] == "Host One" and x["status"] == "pass"]) == 3)
    _, o = judge(_canned(host_w=80.0))
    check("bare control failure is invalid, not fail", o == "invalid")
    v, _ = judge(_canned(host_w=80.0))
    check("and the masked launches go unscored",
          all(x["status"] == "unscored"
              for x in v if x["probe"] == "Host One" and x["launch"] != "bare"))
    bad = _canned()
    for r in ("launch_list", "per_context"):
        bad[r]["widths"]["Listed A"] = bad[r]["widths"]["Listed B"] = 80.0
    v, o = judge(bad)
    check("in-list control failure is invalid", o == "invalid")
    check("in-list failure is reported per launch",
          len([x for x in v if x["probe"] == "in-list-control"
               and x["status"] == "invalid"]) == 2)
    _, o = judge(_canned(list_w=120.0))
    check("launch-list leak is fail", o == "fail")
    _, o = judge(_canned(ctx_w=120.0))
    check("per-context leak is fail", o == "fail")
    _, o = judge(_canned(data_fl=None))
    check("missing data-fl is invalid", o == "invalid")
    _, o = judge(_canned(data_fl='{"saw":true,"applied":false,"err":"boom"}'))
    check("applied:false is invalid", o == "invalid")
    _, o = judge(_canned(absent2=95.0))
    check("mismatched absent references void the run", o == "invalid")
    leak = _canned()
    leak["candidates"] = ["Host One", "Host Two"]
    leak["bare"]["widths"]["Host Two"] = 130.0
    leak["launch_list"]["widths"]["Host Two"] = 140.0   # leaks here
    leak["per_context"]["widths"]["Host Two"] = 80.0    # refused here, so only one arm fails
    v, o = judge(leak)
    check("survey catches a leak the headline family misses", o == "fail")
    check("survey names the count",
          any("1 of the 2 host-only families" in x["reason"] for x in v))
    unreach = _canned()
    unreach["candidates"] = ["Host One", "Never Loaded"]
    unreach["launch_list"]["widths"]["Never Loaded"] = 80.0
    v, o = judge(unreach)
    check("survey ignores a family the bare launch never reached", o == "pass")
    check("and says so in the count",
          any("all 1 host-only families" in x["reason"] for x in v))
    unl = _canned()
    unl["launch_list"]["widths"]["Unlisted X"] = 140.0
    _, o = judge(unl)
    check("bundled-but-unlisted family resolving is fail", o == "fail")
    dead = _canned()
    for r in ("launch_list", "per_context"):
        for f in ("Listed A", "Listed B", "Unlisted X"):
            dead[r]["widths"][f] = 80.0
    v, o = judge(dead)
    check("a dead font stack is invalid, never a green pass", o == "invalid")
    check("and bundled-unlisted goes unscored rather than green",
          all(x["status"] == "unscored"
              for x in v if x["probe"] == "bundled-unlisted"))

    # The two shapes the first version of this self-test could not reach: a
    # width that is missing, and a width that is null. Both used to score `pass`
    # or raise, from a measurement that never happened.
    print("unmeasured widths:")
    miss = _canned()
    for r in ("launch_list", "per_context"):
        del miss[r]["widths"]["Host One"]
    v, o = judge(miss)
    check("a missing width is invalid, never a pass", o == "invalid")
    check("and the family verdict says setup invalid",
          all(x["status"] == "invalid" for x in v
              if x["probe"] == "Host One" and x["launch"] != "bare"))
    nul = _canned()
    for r in ("launch_list", "per_context"):
        nul[r]["widths"]["Host One"] = None
    try:
        v, o = judge(nul)
    except Exception as exc:
        v, o = [], "RAISED %s" % type(exc).__name__
    check("a null width is invalid, not a crash", o == "invalid")
    nonfin = _canned()
    nonfin["launch_list"]["widths"]["Host One"] = float("inf")
    v, o = judge(nonfin)
    check("a non-finite width is invalid, not a confident fail", o == "invalid")
    thrown = _canned()
    for r in ("launch_list", "per_context"):
        del thrown[r]["widths"]["Host One"]
        thrown[r]["page_error"] = "TypeError: boom"
    v, o = judge(thrown)
    check("a thrown page script voids its launch even with both refs intact",
          o == "invalid")
    check("and that launch's measurement is never pass or fail",
          all(x["status"] in ("invalid", "unscored") for x in v
              if x["launch"] in ("launch_list", "per_context")
              and x["probe"] in ("Host One", "host-only-survey")))
    surv = _canned()
    surv["candidates"] = ["Host One", "Host Two"]
    surv["bare"]["widths"]["Host Two"] = 130.0   # reachable in bare, never measured under a mask
    v, o = judge(surv)
    check("survey flags a bare-reachable family the mask never measured",
          o == "invalid")
    check("and never scores that survey as a pass",
          not any(x["status"] == "pass" for x in v
                  if x["probe"] == "host-only-survey"))
    nohost = _canned()
    nohost["host_family"] = None
    v, o = judge(nohost)
    check("no selectable host family is invalid", o == "invalid")
    check("_revive turns a tagged non-finite into a float",
          _revive({"w": {"__nonfinite__": "Infinity"}})["w"] == float("inf"))
    check("_revive turns tagged undefined into None",
          _revive({"w": {"__undefined__": True}})["w"] is None)
    check("_revive leaves an ordinary width alone", _revive({"w": 12.5})["w"] == 12.5)

    print("launch list:")
    b = {".aqua kana": ".Aqua Kana", ".al bayan pua": ".Al Bayan PUA",
         "andale mono": "Andale Mono", "noto sans": "Noto Sans", "zapfino": "Zapfino"}
    h = {"arial": ("Arial", "a"), "georgia": ("Georgia", "g"),
         "andale mono": ("Andale Mono", "am"), "candara": ("Candara", "c")}
    ll, used, missing = build_launch_list(b, h, 10)
    check("drops dot-prefixed bundled families",
          not any(f.startswith(".") for f in ll))
    check("seeds installed on the host come first", ll[:2] == ["Arial", "Georgia"])
    check("seeds not installed are reported", set(missing) == {"Calibri", "Consolas",
                                                               "Courier New"})
    check("seeds used are the installed ones", used == ["Arial", "Georgia"])
    check("bundled families fill the rest", "Noto Sans" in ll and "Zapfino" in ll)
    check("size cap counts the seeds", len(build_launch_list(b, h, 3)[0]) == 3)
    cands = sorted(n for k, (n, _) in h.items()
                   if k not in b and k not in {f.casefold() for f in ll})
    check("seeding removes seeds from the candidate pool", cands == ["Candara"])

    print("helpers:")
    check("spread samples evenly", spread(list(range(10)), 3) == [0, 3, 6])
    check("spread returns all when short", spread([1, 2], 5) == [1, 2])
    url = build_url(["Arial", "Segoe UI"])
    check("data: URL is well formed", url.startswith("data:text/html;charset=utf-8,"))
    check("family names reach the page JSON",
          "Segoe%20UI" in url or "Segoe+UI" in url or "Segoe" in url)
    check("results node id is the runner.py one",
          RESULTS_NODE in urllib.parse.unquote(url))
    check("init script carries a comma-joined list",
          '"Arial,Segoe UI"' in (INIT_JS % json.dumps(",".join(["Arial", "Segoe UI"]))))

    # The bundle reader against the repo, when fontTools is present. This is the
    # one check that touches real data, and it is what would catch the
    # bundle/fonts/windows mistake: a Windows artifact ships macos+linux.
    print("bundle reader (repo, optional):")
    repo = Path(__file__).resolve().parents[2]
    dirs = [repo / "bundle" / "fonts" / "macos", repo / "bundle" / "fonts" / "linux"]
    if all(d.is_dir() for d in dirs):
        try:
            fams = bundle_families(dirs)
            check("reads >100 families from bundle/fonts/{macos,linux}", len(fams) > 100)
            check("keys are casefolded", all(k == k.casefold() for k in fams))
        except ImportError:
            print("  fontTools not installed -- skipped")
    else:
        print("  bundle dirs not present -- skipped")

    if fails:
        print("\nSELF-TEST FAILED: %s" % ", ".join(fails))
        return 1
    print("\nSELF-TEST PASSED")
    return 0


# --------------------------------------------------------------------------

NOT_VERIFIED = """
NOT verified by this run:
  * The macOS host. Makefile:178 is `package-macos: ... --fonts windows linux`,
    so a macOS build bundles every OS except its own and the macOS host-font
    question stays unmeasured. Nothing here says anything about it.
  * Per-user font installs under %LOCALAPPDATA%\\Microsoft\\Windows\\Fonts.
    Only the machine-wide C:\\Windows\\Fonts directory is enumerated.
  * Any family not installed on this particular machine, and any family whose
    name fontTools could not read (.fon and friends are skipped).
  * The local() / LookupLocalFont path. This probe measures family-name lookup
    through the CSS font shorthand only.
  * U+FFFD codepoint fallback is measured and printed but NOT scored: under a
    masked launch there is no reference guaranteed to differ from it, so a
    verdict there would not be a control (CLAUDE.md lesson 4).
  * Headless. Advance-width measurement needs no GL context, so this is not the
    headless-WebGL trap from issue #75, but it is still not a headful run.
  * The `pass` direction of the two masked arms is not fully controlled. The host
    family is compared against the absent-family reference IN THAT MASKED LAUNCH,
    but what qualified it was that it differed from the BARE launch's fallback
    face. Under a mask the `monospace` fallback resolves within the allowed list,
    plausibly to Courier New or Consolas, so it is a different face and nothing
    guarantees the two sides differ (CLAUDE.md lesson 4, a cross-launch
    reference). What makes a systemic false green implausible is the host-only
    survey: every one of the bare-reachable families would have to coincide with
    the masked fallback width at once. A single-family pass does not carry that
    weight on its own.
"""


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="#87 native-Windows font probe.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=NOT_VERIFIED)
    ap.add_argument("--executable-path", help="path to camoufox.exe (required for a real run)")
    ap.add_argument("--bundle-dir", action="append", default=[],
                    help="the artifact's font directory. Repeatable. This is what the "
                         "binary bundles; a Windows build bundles the macOS and Linux "
                         "families (Makefile:190), never the Windows ones.")
    ap.add_argument("--repo-root", default=None,
                    help="explicit alternative to --bundle-dir: reads "
                         "<root>/bundle/fonts/macos and .../linux. Not a default; "
                         "a real run must name one or the other.")
    ap.add_argument("--out", "--json", dest="out", default=None,
                    help="write the JSON result object here")
    ap.add_argument("--headful", action="store_true",
                    help="show a window; headless is the default and is fine here")
    ap.add_argument("--launch-list-size", type=int, default=40)
    ap.add_argument("--self-test", "--dry-run", dest="self_test", action="store_true",
                    help="exercise the selection rule and every verdict shape on canned "
                         "inputs; launches no browser and imports no playwright")
    args = ap.parse_args(argv)

    # Family names out of C:\\Windows\\Fonts include localized nameID 1 records,
    # and the bundle alone carries 77 non-ASCII families. Windows gives stdout
    # the console code page, so printing one raises UnicodeEncodeError and costs
    # the run. Same idiom as service-tester/run_tests.py:30-32, but not
    # win32-guarded: any piped run under a non-UTF-8 locale hits it, and the
    # brief's Step 4 pipes through tee.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    if args.self_test:
        return self_test()
    if not args.executable_path:
        ap.error("--executable-path is required for a real run (or pass --self-test)")

    # No silent fallback to this checkout's bundle directories. The authoritative
    # answer to "what does this binary bundle" is the artifact's own font
    # directory; a repo checkout is a proxy that can drift from the binary under
    # test, and getting this set wrong silently changes the candidate pool
    # (Makefile:190 -- a Windows artifact bundles macOS and Linux, never Windows).
    if args.bundle_dir:
        bundle_dirs = [Path(d) for d in args.bundle_dir]
    elif args.repo_root:
        root = Path(args.repo_root)
        bundle_dirs = [root / "bundle" / "fonts" / "macos",
                       root / "bundle" / "fonts" / "linux"]
    else:
        ap.error("--bundle-dir is required for a real run: point it at the extracted "
                 "artifact's own fonts directory. Pass --repo-root instead only if you "
                 "deliberately want this checkout's bundle/fonts/{macos,linux}.")
    missing = [str(d) for d in bundle_dirs if not d.is_dir()]
    if missing:
        print("FATAL: bundle directory not found: %s" % ", ".join(missing))
        print("Pass --bundle-dir pointing at the extracted artifact's fonts directory.")
        return 1

    bundled = bundle_families(bundle_dirs)
    if not bundled:
        print("FATAL: no family names read from %s. Without the bundle list every host "
              "family looks host-only, and a 'reachable' reading could be the bundled "
              "copy rather than the host's." % ", ".join(str(d) for d in bundle_dirs))
        return 1
    host = host_families()
    if not host:
        print(r"FATAL: no families read from C:\Windows\Fonts. This script must run on "
              "the native Windows interpreter, not under WSL.")
        return 1

    launch_list, seeds_used, seeds_missing = build_launch_list(
        bundled, host, args.launch_list_size)
    launch_keys = {f.casefold() for f in launch_list}
    if not seeds_used:
        print("WARNING: none of the Windows base families %s is installed here, so the "
              "in-list control falls back to bundled families whose resolution also "
              "depends on font.visibility.level." % (WINDOWS_BASE_SEED,))

    candidates = sorted((orig for key, (orig, _p) in host.items()
                         if key not in bundled and key not in launch_keys
                         and not orig.startswith(".")),
                        key=lambda s: (s.casefold(), s))
    if not candidates:
        print(r"FATAL: every family in C:\Windows\Fonts is also bundled or listed -- no "
              "host-only family exists to probe, so this run cannot answer #87.")
        return 1
    probed = candidates[:MAX_PROBE_FAMILIES]

    # Seeds first: they are the strongest members of the in-list control, and
    # `spread` fills the rest out of the bundled part of the list.
    bundled_listed = [f for f in launch_list if f.casefold() not in
                      {s.casefold() for s in seeds_used}]
    in_list_probes = seeds_used + spread(bundled_listed, 3)
    unlisted = [f for f in sorted(bundled.values(), key=lambda s: (s.casefold(), s))
                if f.casefold() not in launch_keys and not f.startswith(".")]
    bundled_unlisted_probes = spread(unlisted, 5)
    families = probed + [f for f in in_list_probes + bundled_unlisted_probes
                         if f not in probed]

    results = {
        "candidates": probed,
        "candidates_total": len(candidates),
        "launch_list_families": launch_list,
        "in_list_probes": in_list_probes,
        "bundled_unlisted_probes": bundled_unlisted_probes,
        "bundle_family_count": len(bundled),
        "host_family_count": len(host),
        "env": {
            "executable": args.executable_path,
            "bundle_dirs": [str(d) for d in bundle_dirs],
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "os": platform.platform(),
            "headful": args.headful,
            "truncated_candidates": len(candidates) > len(probed),
        },
    }

    print("bundle families: %d (from %s)"
          % (len(bundled), ", ".join(str(d) for d in bundle_dirs)))
    print(r"host families:   %d (C:\Windows\Fonts)" % len(host))
    print("host-only:       %d, probing %d" % (len(candidates), len(probed)))
    print("launch list:     %d families, e.g. %s" % (len(launch_list), launch_list[:3]))

    # All three launches carry CAMOU_CONFIG, so the only thing that differs
    # between `bare` and `launch_list` is the `fonts` key itself.
    results["bare"] = measure(args.executable_path, families, {}, None, args.headful)
    results["launch_list"] = measure(args.executable_path, families,
                                     {"fonts": launch_list}, None, args.headful)
    results["per_context"] = measure(args.executable_path, families, {},
                                     launch_list, args.headful)

    def write_out():
        """Durable before anything that can fail. Three browser launches on a
        remote host are expensive, so the raw widths go to disk as soon as they
        exist -- ahead of judging and ahead of any print of a family name."""
        if args.out:
            Path(args.out).write_text(json.dumps(results, indent=2), encoding="utf-8")

    write_out()

    # camoufox-152 needs playwright 1.55.0; build-tester reports a clean-looking
    # 0/0 on a newer one. That is a fact about the build-tester harness, which
    # this script does not use, so this warns rather than refuses -- but an
    # unexpected version is the first thing to suspect if the numbers look odd.
    pw_seen = results["bare"].get("playwright")
    results["env"]["playwright"] = pw_seen
    if pw_seen != PLAYWRIGHT_PIN:
        print("WARNING: playwright %s, not the %s this repo pins for camoufox-152."
              % (pw_seen, PLAYWRIGHT_PIN))

    host_family, reason = choose_host_family(probed, results["bare"]["widths"])
    results["host_family"] = host_family
    results["host_family_reason"] = reason
    results["host_family_file"] = (host.get(host_family.casefold(), (None, None))[1]
                                   if host_family else None)

    verdicts, overall = judge(results)
    results["verdicts"] = verdicts
    results["overall"] = overall
    results["passed"] = overall == "pass"
    write_out()

    print("\nhost-only family under test: %r" % host_family)
    print("  chosen: %s" % reason)
    print("  file:   %s" % results["host_family_file"])
    for name in ("bare", "launch_list", "per_context"):
        w = results[name]["widths"]
        shown = {k: w.get(k) for k in ["__absent1__", "__absent2__", "__monospace__",
                                       "__fffd__"] + ([host_family] if host_family else [])
                 + in_list_probes + bundled_unlisted_probes}
        print("\n[%s] data_fl=%r page_error=%r"
              % (name, results[name]["data_fl"], results[name]["page_error"]))
        for k, val in shown.items():
            print("    %-32s %s" % (k, val))
    print("\n[U+FFFD, informational only] bare=%s launch_list=%s per_context=%s"
          % tuple(results[n]["widths"].get("__fffd__") for n in
                  ("bare", "launch_list", "per_context")))

    if args.out:
        print("\nwrote %s" % args.out)

    print("\n=== verdicts ===")
    for v in verdicts:
        print("  [%-8s] %-12s %-28s %s"
              % (v["status"], v["launch"], v["probe"], v["reason"]))
    print("\noverall: %s" % overall.upper())
    if overall == "invalid":
        print("This run measured nothing usable. Do not report a pass or a fail from it.")
    print(NOT_VERIFIED)
    return 0 if overall == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
