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

The font list is fixed and admits at least one target of every row key
(`helvetica`, `times`, `courier new`), so the generic table answers every
generic and the corner where no row key resolves (#333) stays out of the
measurement. A name whose targets the list does not admit is keyed to the
default of that same list, read from the never-font, never to a face name:
the default depends on the list.

What this cannot see: codepoint fallback to host fonts is ungated, a custom
`fonts=` list can still admit a foreign name with no alias, and the generics
only follow the aliases (their realism is #333).
"""

import glob
import os
import re
from pathlib import Path

FONTS = [
    "Helvetica", "Arial", "Times", "Times New Roman", "Courier", "Courier New",
    "Calibri", "Avant Garde",
    "Nimbus Sans", "Nimbus Roman", "Nimbus Mono PS",
    "Liberation Sans", "Liberation Serif", "Liberation Mono",
    "Arimo", "Tinos", "Cousine",
    "DejaVu Sans", "DejaVu Serif", "DejaVu Sans Mono",
]
NAMES = ["Helvetica", "Arial", "Times", "Times New Roman", "Courier", "Courier New"]
NO_TARGET = ["Calibri", "Avant Garde"]
GENERICS = ["serif", "sans-serif", "monospace", "cursive"]
NEVER = "Zzz Not A Font"
# The family that drew each request on the Linux host, with FONTS above.
EXPECTED = {
    "Helvetica": "Nimbus Sans",
    "Arial": "Arimo",
    "Times": "Nimbus Roman",
    "Times New Roman": "Tinos",
    "Courier": "Nimbus Mono PS",
    "Courier New": "Cousine",
    "serif": "Nimbus Roman",
    "sans-serif": "Nimbus Sans",
    "monospace": "Cousine",
    "cursive": "Nimbus Sans",
}
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


def test_a_linux_claim_draws_the_linux_faces(binary):
    from camoufox.fingerprints import get_random_preset
    from camoufox.sync_api import NewBrowser
    from drivers.playwright_drivers import playwright

    logdir = Path(__file__).resolve().parents[2] / ".ci-work" / f"linux-claim-fonts-{os.getpid()}"
    logdir.mkdir(parents=True)
    env = {"MOZ_LOG": "fontlist:4,sync,append", "MOZ_LOG_FILE": str(logdir / "cfx%PID")}
    for _ in range(15):
        try:
            browser = NewBrowser(playwright(), os="linux", fonts=FONTS, canvas_noise=True, headless=True,
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
            page.evaluate(MEASURE, [f'"{n}"' for n in NAMES + NO_TARGET + [NEVER]] + GENERICS)
        finally:
            browser.close()
        break
    else:
        raise RuntimeError("no Linux preset launched")

    drawn = faces(logdir)
    failures = []
    for request, family in EXPECTED.items():
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
