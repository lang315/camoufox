"""Journey 9: a Linux claim draws the Linux faces, on every host (#325).

fontconfig answers a Linux identity's named lookups through browser/bundle/
fontconfig/linux/fonts.conf: Helvetica is Nimbus Sans, Arial is Arimo. Windows
and macOS have no fontconfig, and their flat package also holds the Apple and
Microsoft files under those names, so a Linux claim there used to draw
Helvetica.ttc for Helvetica. The browser applies the conf's answer itself
(FontAliasesLinux.hpp); this journey reads the face that drew each name from
`CAMOU-FL face` (docs/fonts-gating.md) and compares it with the Linux host's.

The expected table is the Linux host's reading, run by this same test on the
Linux leg, so that leg proves the table and the other two use it.

The generics follow the chains in FontAliasesLinux.hpp, the faces fontconfig
ranks for serif, sans-serif, monospace and cursive on a Latin page (#333). Each
is read from that header, never typed here: the face a generic must draw is the
first chain face the context's list admits. Two lists are run. The short one
holds no Noto face and no Z003, so every generic must fall to the conf's next
face and not to a hand-written row; the full one holds every chain face, so
each generic must draw the conf's first.

The lang groups fontconfig answers differently (ja, ko, zh-CN, zh-TW, zh-HK, ar) have
chains of their own in the same header (#389), keyed by the lang group of the page.
They are read from the header too. Each page language is set on the document, so the
browser derives the group from it, and the face is read from `CAMOU-FL generic-map`,
whose `step=chain:<group>` names the table that answered. Two lists are run: one that
holds the group's faces, and one that holds only the Latin chain faces and must take the
next admitted face of the same list, so the two cannot agree by accident.

The font lists admit at least one target of every row key (`helvetica`,
`times`, `courier new`), so the corner where no chain face resolves stays out
of the measurement. A name whose targets the list does not admit is keyed to
the default of that same list, read from the never-font, never to a face name:
the default depends on the list.

What this cannot see: codepoint fallback to host fonts is ungated, a custom
`fonts=` list can still admit a foreign name with no alias, and the lang groups
outside the table keep the Latin chain (#395).
"""

import glob
import os
import re
from pathlib import Path

import pytest

HEADER = Path(__file__).resolve().parents[2] / "browser" / "additions" / "camoucfg" / "FontAliasesLinux.hpp"

FONTS = [
    "Helvetica", "Arial", "Times", "Times New Roman", "Courier", "Courier New",
    "Calibri", "Avant Garde",
    "Nimbus Sans", "Nimbus Roman", "Nimbus Mono PS",
    "Liberation Sans", "Liberation Serif", "Liberation Mono",
    "Arimo", "Tinos", "Cousine",
    "DejaVu Sans", "DejaVu Serif", "DejaVu Sans Mono",
]
FULL_FONTS = FONTS + ["Noto Serif", "Noto Sans", "Noto Mono", "Z003"]
NAMES = ["Helvetica", "Arial", "Times", "Times New Roman", "Courier", "Courier New"]
NO_TARGET = ["Calibri", "Avant Garde"]
GENERICS = ["serif", "sans-serif", "monospace", "cursive"]
NEVER = "Zzz Not A Font"
# The family that drew each name on the Linux host, with FONTS above.
EXPECTED = {
    "Helvetica": "Nimbus Sans",
    "Arial": "Arimo",
    "Times": "Nimbus Roman",
    "Times New Roman": "Tinos",
    "Courier": "Nimbus Mono PS",
    "Courier New": "Cousine",
}
CHAIN_ARRAYS = {"serif": "Serif", "sans-serif": "SansSerif", "monospace": "Monospace", "cursive": "Cursive"}


def chain(generic):
    """The faces the generated header ranks for `generic`, in order."""
    text = HEADER.read_text(encoding="utf-8")
    body = re.search(rf"kCamouLinux{CHAIN_ARRAYS[generic]}Chain\[\] = \{{(.*?)\}};", text)
    assert body, f"{HEADER.name} has no {generic} chain"
    return re.findall(r'"([^"]+)"', body.group(1))


def first_admitted(generic, fonts):
    """The family a generic must draw: the first chain face (case-insensitive) the list admits."""
    admitted = {f.lower(): f for f in fonts}
    return next((admitted[f] for f in chain(generic) if f in admitted), None)


GENERIC_IDS = {1: "serif", 2: "sans-serif", 3: "monospace", 4: "cursive"}
# The page language set on the document -> the table row the browser must pick (langGroups.properties).
LANG_PAGES = {
    "ja": "ja", "ja-JP": "ja", "ko": "ko", "zh-CN": "zh-cn", "zh-TW": "zh-tw", "zh-HK": "zh-hk",
    "ar": "ar", "fa": "ar",
}


def lang_chains():
    """tag -> generic -> faces, from the header's kCamouLinuxLangChains."""
    text = HEADER.read_text(encoding="utf-8")
    arrays = {n: re.findall(r'"([^"]+)"', body) for n, body in
              re.findall(r"static const char\* const (kCamouLinuxChain\d+)\[\] = \{(.*?)\};", text)}
    rows = re.findall(r'\{"([a-z-]+)", (kCamouLinuxChain\d+), (kCamouLinuxChain\d+), '
                      r'(kCamouLinuxChain\d+), (kCamouLinuxChain\d+)\},', text)
    assert rows, f"{HEADER.name} has no lang chains"
    return {tag: dict(zip(GENERICS, (arrays[n] for n in names))) for tag, *names in rows}


MEASURE = """(fams) => { const c = document.createElement('canvas').getContext('2d');
  for (const f of fams) { c.font = '48px ' + f; c.measureText('Hamburgefonstiv QRgy@&1'); } }"""


def faces(logdir):
    """request -> family of the face that drew its first range, from the `CAMOU-FL face` lines."""
    out = {}
    for path in glob.glob(str(logdir / "cfx*")):
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.search(r"CAMOU-FL face ctx=(\d+) families=(.*?) \[\d+:\d+ u\+\w+\] (.*?)(?= \[\d+:\d+ u\+\w+\]|$)", line)
            if m and m.group(1) != "0":
                out.setdefault(m.group(2).strip('"'), m.group(3).rsplit(" / ", 1)[-1].strip())
    return out


LANG_MEASURE = """(fams) => { const c = document.querySelector('canvas').getContext('2d');
  for (const f of fams) { c.font = '48px ' + f; c.measureText('Hamburgefonstiv QRgy@&1'); } }"""


def launch_and_log(binary, fonts, requests, langs=()):
    """Launch a Linux claim with `fonts`, measure each request, and return the directory of its MOZ_LOG files.

    Each of `langs` is then a document of that language with a canvas in it, measured the same way.
    """
    from camoufox.fingerprints import get_random_preset
    from camoufox.sync_api import NewBrowser
    from drivers.playwright_drivers import playwright

    logdir = Path(__file__).resolve().parents[2] / ".ci-work" / f"linux-claim-fonts-{os.getpid()}-{len(fonts)}"
    logdir.mkdir(parents=True)
    env = {"MOZ_LOG": "fontlist:4,sync,append", "MOZ_LOG_FILE": str(logdir / "cfx%PID")}
    for _ in range(15):
        try:
            browser = NewBrowser(playwright(), os="linux", fonts=fonts, canvas_noise=True, headless=True,
                                 executable_path=str(binary), fingerprint_preset=get_random_preset(os="linux"),
                                 i_know_what_im_doing=True, env=env)
        except ValueError as e:  # a preset whose GPU the host cannot claim
            if "WebGL" not in str(e):
                raise
            continue
        try:
            page = browser.new_context().new_page()
            page.goto("about:blank")
            assert page.evaluate("navigator.platform").startswith("Linux")
            page.evaluate(MEASURE, requests)
            for lang in langs:
                page.set_content(f'<html lang="{lang}"><body><canvas></canvas></body></html>')
                page.evaluate(LANG_MEASURE, GENERICS)
        finally:
            browser.close()
        return logdir
    raise RuntimeError("no Linux preset launched")


@pytest.mark.parametrize("fonts", [FONTS, FULL_FONTS], ids=["short-list", "full-list"])
def test_a_linux_claim_draws_the_linux_faces(binary, fonts):
    logdir = launch_and_log(binary, fonts, [f'"{n}"' for n in NAMES + NO_TARGET + [NEVER]] + GENERICS)

    drawn = faces(logdir)
    failures = []
    expected = {**EXPECTED, **{g: first_admitted(g, fonts) for g in GENERICS}}
    for request, family in expected.items():
        print(f"CAMOU-FL alias {request!r} drew {drawn.get(request)!r}, want {family!r}")
        if drawn.get(request) != family:
            failures.append(f"{request}: drew {drawn.get(request)!r}, the Linux host draws {family!r}")
    default = drawn.get(NEVER)
    for request in NO_TARGET:
        print(f"CAMOU-FL control {request!r} drew {drawn.get(request)!r}, list default {default!r}")
        if not default or drawn.get(request) != default:
            failures.append(f"{request}: admitted with no admitted target drew {drawn.get(request)!r}, "
                            f"want the list's default {default!r}")
    assert not failures, "\n".join(failures)


def test_a_list_with_no_chain_face_falls_to_the_rows(binary):
    """The known limit of the chains (#333): a list that refuses every face of a chain gets the old rows.

    No drawn Linux list does (300 of 300 admit every chain face), so this pins the behaviour for a
    custom `fonts=` list instead of leaving it accidental. Liberation Sans is on no chain, only on
    the sans-serif row, so serif and monospace answer from the second row (`step=rows`) and no
    generic answers from a chain.
    """
    logdir = launch_and_log(binary, ["Liberation Sans"], GENERICS)
    steps = {}
    for path in glob.glob(str(logdir / "cfx*")):
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.search(r"CAMOU-FL generic-map ctx=(\d+) generic=(\d+) step=(\S+) key=(.*)$", line)
            if m and m.group(1) != "0":
                steps.setdefault(int(m.group(2)), set()).add((m.group(3), m.group(4)))
    print(f"CAMOU-FL generic-map steps {steps}")
    drawn = faces(logdir)
    assert all(step != "chain" for pairs in steps.values() for step, _ in pairs), steps
    assert steps.get(1) == {("rows", "liberation sans")}, f"serif: {steps.get(1)}"
    assert steps.get(3) == {("rows", "liberation sans")}, f"monospace: {steps.get(3)}"
    assert {drawn.get(g) for g in GENERICS} == {"Liberation Sans"}, drawn


def generic_steps(logdir):
    """(generic, step) -> keys of the `CAMOU-FL generic-map` lines of a launch's contexts."""
    out = {}
    for path in glob.glob(str(logdir / "cfx*")):
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.search(r"CAMOU-FL generic-map ctx=(\d+) generic=(\d+) step=(\S+) key=(.*)$", line)
            if m and m.group(1) != "0" and int(m.group(2)) in GENERIC_IDS:
                out.setdefault((GENERIC_IDS[int(m.group(2))], m.group(3)), set()).add(m.group(4))
    return out


def lang_expected(tag, generic, fonts):
    admitted = {f.lower() for f in fonts}
    return next((f for f in lang_chains()[tag][generic] if f in admitted), None)


@pytest.mark.parametrize("with_group_faces", [True, False], ids=["group-faces-listed", "latin-faces-only"])
def test_a_linux_claim_draws_the_conf_chain_of_the_pages_lang_group(binary, with_group_faces):
    chains = lang_chains()
    group_faces = sorted({f for by_generic in chains.values() for faces_ in by_generic.values() for f in faces_})
    fonts = FULL_FONTS + (group_faces if with_group_faces else [])
    logdir = launch_and_log(binary, fonts, GENERICS, langs=list(LANG_PAGES))

    steps = generic_steps(logdir)
    failures = []
    for page_lang, tag in LANG_PAGES.items():
        for generic in GENERICS:
            want = lang_expected(tag, generic, fonts)
            got = steps.get((generic, f"chain:{tag}"), set())
            print(f"CAMOU-FL lang {page_lang!r} -> {tag} {generic}: got {sorted(got)}, want {want!r}")
            if got != {want}:
                failures.append(f"{page_lang} {generic}: step chain:{tag} gave {sorted(got)}, the header wants {want!r}")
    assert not failures, "\n".join(failures)


def test_the_two_font_lists_do_not_agree_on_the_lang_chains():
    """The control for the test above: the listed and the Latin-only list must expect different faces somewhere,
    or the second could not tell a table walk from a fall-through."""
    chains = lang_chains()
    group_faces = sorted({f for by_generic in chains.values() for faces_ in by_generic.values() for f in faces_})
    listed, latin = FULL_FONTS + group_faces, FULL_FONTS
    differing = [(t, g) for t in chains for g in GENERICS if lang_expected(t, g, listed) != lang_expected(t, g, latin)]
    assert differing, "every lang chain starts with a Latin face, so the control proves nothing"
    assert ("ja", "serif") in differing, differing
