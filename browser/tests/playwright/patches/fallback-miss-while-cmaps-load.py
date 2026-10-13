"""
Verify a fallback miss is not cached while the font cmaps are still loading (#165).

In a content process with async fallback on (stock's default), GlobalFontFallback
skips every family whose cmap is not loaded yet and asks the parent to load them.
Upstream then cached the miss in the process-wide mCodepointsWithNoFonts, so
every later lookup of that character in the process returned a hexbox, silently,
until the parent had loaded every cmap: 1 to 10 s after launch, measured on the
first context of a windows identity on a mac host. font-list-spoofing.patch
leaves such a miss uncached, so the next lookup scans again.

The raw binary is launched with no prefs (async fallback on), and its first page
measures a few rare characters twice, back to back. The question is asked of the
browser's own fallback lines (fontlist:4), not of pixels.

Linux only by default: there UseCmapsDuringSystemFallback sends every lookup
through the cmap scan. Elsewhere the platform fallback answers first unless a
font mask is active, so a run on macOS or Windows needs CAMOU_CONFIG_1 with a
`fonts` list in the environment.

What PASS means:
    * at least one character's first scan logged `cmap-skipped=N` (N > 0) and
      `resolved=none`. Without one, nothing was measured: SETUP-INVALID;
    * every such character was scanned again by its second measurement. Before
      the fix, the second lookup returned at SkipFontFallbackForChar and logged
      nothing.

    python browser/tests/playwright/patches/fallback-miss-while-cmaps-load.py
"""

import asyncio
import os
import platform
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from helpers import check, resolve_binary  # noqa: E402

# Assigned, so FindFontForChar does not skip them as unassigned, and rare enough
# that the first scan can miss them.
CHARS = [0x1E900, 0x16A40, 0x11400, 0x1F603, 0x4E2D]
PROBE = """(cps) => { const x = document.createElement('canvas').getContext('2d');
  x.font = '16px serif';
  for (const pass of [0, 1]) for (const cp of cps) x.measureText(String.fromCodePoint(cp)); }"""
LINE = re.compile(r"CAMOU-FL global-fallback ch=U\+([0-9A-F]+) .*cmap-skipped=(\d+) resolved=(.*)$")


async def main() -> int:
    if platform.system() != "Linux" and not os.environ.get("CAMOU_CONFIG_1"):
        print("SKIP: off Linux the platform fallback answers first without a font mask (CAMOU_CONFIG_1)")
        return 0
    from playwright.async_api import async_playwright

    # Not /tmp: the Linux content sandbox gives content processes their own view of
    # it, so their per-process logs would not land where this reads.
    work = Path(__file__).resolve().parents[4] / ".ci-work"
    work.mkdir(exist_ok=True)
    logdir = Path(tempfile.mkdtemp(prefix="fallback165-log-", dir=work))
    env = dict(os.environ, MOZ_LOG="fontlist:4,sync", MOZ_LOG_FILE=str(logdir / "cfx"))
    async with async_playwright() as p:
        browser = await p.firefox.launch(executable_path=str(resolve_binary()), headless=True, env=env)
        page = await browser.new_page()
        await page.goto("about:blank")
        await page.evaluate(PROBE, CHARS)
        await browser.close()

    scans: dict = {}
    for f in logdir.glob("cfx*"):
        for line in f.read_text(errors="replace").splitlines():
            m = LINE.search(line)
            if m:
                scans.setdefault(f.name, {}).setdefault(int(m.group(1), 16), []).append(
                    (int(m.group(2)), m.group(3).strip()))
    pending = [(proc, ch, len(s)) for proc, chars in scans.items() for ch, s in chars.items()
               if s[0][0] > 0 and s[0][1] == "none"]
    print(f"first scans that skipped loading cmaps and missed: "
          f"{[(proc, f'U+{ch:04X}', n) for proc, ch, n in pending]}")

    failures: list = []
    check(failures, "a first scan skipped loading cmaps and missed (else SETUP-INVALID)", bool(pending), True)
    for proc, ch, n in pending:
        check(failures, f"{proc} U+{ch:04X} scanned again by its second measurement", n >= 2, True)
    if failures:
        print(f"FAIL: {failures}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
