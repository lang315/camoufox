"""
Verify CSS `monospace` stays monospaced under a LAUNCH-level font list (#162).

font-list-spoofing.patch answers generics from an ordered table intersected
with the allowed families (CamouGenericCandidate). Before #162 that table served
only a context with a list of its own; under the launch-level `fonts` mask alone
a generic resolved through the host's font.name-list pref, which the mask
refuses, so `monospace` fell to a proportional face.

The raw binary is launched with CAMOU_CONFIG holding only a `fonts` list, with
no font.name-list.* prefs (the launchers' own #162 prefs would hide the browser
fix) and no FONTCONFIG_FILE, so generics start from the host's fontconfig
default monospace. The list refuses that family and allows a family from the
table's monospace row plus a sans-serif family.

Font universe: the host's fontconfig, not the shipped bundle (CLAUDE.md lesson
8). The list is built from it, so the question asked -- does the gate pick a
row family the mask allows over the host default it refuses -- does not depend
on which fonts the host has, only on it having one row family besides its
default. Linux only (fc-list/fc-match); DWrite and CoreText are measured by the
e2e dispatch with CAMOUFOX_NO_GENERIC_PREFS=1.

What PASS means:
    * `monospace` gives "iiiiiiiiii" and "mmmmmmmmmm" one width;
    * `sans-serif` gives them different widths. Without that the measurement
      cannot tell a monospaced face from a proportional one, so a miss is
      SETUP-INVALID.

    python browser/tests/playwright/patches/generic-monospace-launch-mask.py
"""

import asyncio
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from helpers import check, resolve_binary  # noqa: E402

# font-list-spoofing.patch's kCamouMonospaceRow, in its order.
MONO_ROW = ["Menlo", "Monaco", "Consolas", "Courier New", "Courier", "Cousine",
            "Liberation Mono", "DejaVu Sans Mono", "Noto Sans Mono"]
SANS = ["DejaVu Sans", "Liberation Sans", "Noto Sans", "Arimo"]
PROBE = """(() => { const x = document.createElement('canvas').getContext('2d');
  const w = (f, s) => { x.font = '32px ' + f; return x.measureText(s).width; };
  return {mono: [w('monospace', 'iiiiiiiiii'), w('monospace', 'mmmmmmmmmm')],
          sans: [w('sans-serif', 'iiiiiiiiii'), w('sans-serif', 'mmmmmmmmmm')]}; })()"""


def fc(tool: str, *args: str) -> str:
    return subprocess.run([f"fc-{tool}", *args], capture_output=True, text=True, check=True).stdout


async def main() -> int:
    if platform.system() != "Linux":
        print("SKIP: this guard reads the host font universe through fontconfig (Linux only)")
        return 0
    host_mono = fc("match", "-f", "%{family[0]}", "monospace").strip()
    installed = {f.strip() for f in fc("list", ":", "family").replace(",", "\n").splitlines()}
    row = next((f for f in MONO_ROW if f in installed and f != host_mono), None)
    sans = next((f for f in SANS if f in installed), None)
    print(f"host default monospace {host_mono!r}; allowed row family {row!r}; sans-serif {sans!r}")
    if not row or not sans:
        print("FAIL: SETUP-INVALID: no list can refuse the host monospace and allow a row family")
        return 1

    from playwright.async_api import async_playwright

    env = {k: v for k, v in os.environ.items() if k != "FONTCONFIG_FILE"}
    env["CAMOU_CONFIG_1"] = json.dumps({"fonts": [row, sans]})
    async with async_playwright() as p:
        browser = await p.firefox.launch(executable_path=str(resolve_binary()), headless=True, env=env)
        page = await browser.new_page()
        await page.goto("about:blank")
        r = await page.evaluate(PROBE)
        await browser.close()

    failures: list = []
    check(failures, "sans-serif i/m widths differ (else SETUP-INVALID)", r["sans"][0] != r["sans"][1], True)
    check(failures, f"monospace i/m widths equal ({r['mono']})", r["mono"][0] == r["mono"][1], True)
    if failures:
        print(f"FAIL: {failures}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
