"""
Verify the system-ui font spoofing patch (system-ui-font-spoofing.patch).

The patch reads navigator.platform from MaskConfig and returns the appropriate
system font for GetSystemUIFontFamilies(): Helvetica for macOS, Segoe UI for
Windows. Without it, Linux spoofing macOS resolves system-ui to "Sans" via GTK.

Run from dvsa-bot to get the right venv:
    cd ~/20tech/drivingtest/dvsa-bot
    uv run python ~/20tech/oss/camoufox/tests/patches/2026-04-30-system-ui-font-override.py

What PASS means:
    Canvas measureText with unquoted "system-ui" produces the same width as
    the expected system font for the spoofed OS.

Caveat — CSS font syntax:
    "system-ui" UNQUOTED is a CSS generic keyword → ResolveGenericFontNames.
    "system-ui" QUOTED is a literal family name → FindAndAddFamiliesLocked.
    This test uses unquoted, which is what websites use and what the patch fixes.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from helpers import launch_camoufox


EXPECTED_FONT = {
    "macos": "Helvetica",
    "windows": "Segoe UI",
}

MEASURE_TEXT_JS = """(() => {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    const testStr = 'mmmmmmmmmmlli';

    ctx.font = '72px monospace';
    const baseW = ctx.measureText(testStr).width;

    const results = {};

    // Unquoted generics — these go through ResolveGenericFontNames
    for (const name of ['system-ui', 'sans-serif']) {
        ctx.font = '72px ' + name + ', monospace';
        results[name] = ctx.measureText(testStr).width;
    }

    // Named fonts — direct lookup via FindAndAddFamiliesLocked
    for (const name of ['Helvetica', 'Helvetica Neue', 'Segoe UI', 'Sans']) {
        ctx.font = '72px "' + name + '", monospace';
        results[name] = ctx.measureText(testStr).width;
    }

    return { widths: results, baseline: baseW };
})()"""


async def test_os(target_os: str) -> bool:
    expected_family = EXPECTED_FONT.get(target_os)
    if not expected_family:
        print(f"  SKIP: no expected system-ui font for {target_os}")
        return True

    async with launch_camoufox(os=target_os) as (page, config):
        platform = config.get("navigator.platform", "unknown")
        result = await page.evaluate(MEASURE_TEXT_JS)

    widths = result["widths"]
    baseline = result["baseline"]

    print(f"  navigator.platform: {platform}")
    print(f"  Expected system-ui: {expected_family}")
    print(f"  Baseline (mono):    {baseline}")
    for name, w in widths.items():
        tag = " (baseline)" if w == baseline else ""
        print(f"    {name:20s}  {w}{tag}")

    system_ui_w = widths["system-ui"]
    expected_w = widths.get(expected_family, None)

    if expected_w is None or expected_w == baseline:
        print(f"  SKIP: {expected_family} not available as a named font")
        return True

    if system_ui_w == expected_w:
        print(f"  PASS: system-ui resolves to {expected_family}")
        if widths["sans-serif"] == expected_w:
            # sans-serif lands on the same face, so this arm cannot tell the
            # system-ui hook from the generic sans-serif row answering both.
            # #131: the windows arm passed for exactly that reason while the
            # hook never ran. Only an arm where the two differ proves the hook.
            print("  NOTE: sans-serif resolves to the same face -- this arm "
                  "does not distinguish the system-ui hook from the sans row")
        return True

    if system_ui_w == baseline:
        print(f"  FAIL: system-ui fell through to monospace baseline")
        return False

    sans_w = widths.get("Sans", baseline)
    if system_ui_w == sans_w and sans_w != expected_w:
        print(f"  FAIL: system-ui resolves to Sans (Linux leak)")
        return False

    print(f"  FAIL: system-ui width {system_ui_w} doesn't match {expected_family} ({expected_w})")
    return False


# #138: a macOS context inside a Windows launch. The launch's fonts admit both
# OSes, so only the context's own list decides. The list holds "Helvetica Neue"
# on purpose: it heads the #92 sans row, so a system-ui step that asked the
# launch's platform (Win32 -> "Segoe UI", refused by this list) falls to the
# row and lands there instead of on "Helvetica".
MIXED_OS_CONTEXT_FONTS = ["Helvetica", "Helvetica Neue", "Menlo"]


async def test_mixed_os_context(max_attempts: int = 15) -> bool:
    from camoufox.async_api import AsyncCamoufox
    from camoufox.fingerprints import generate_context_fingerprint, get_random_preset

    for _ in range(max_attempts):
        launch_fp = generate_context_fingerprint(preset=get_random_preset(os="windows"))
        mac_fp = generate_context_fingerprint(
            preset=get_random_preset(os="macos"),
            config_overrides={"fonts": MIXED_OS_CONTEXT_FONTS},
        )
        launch_fonts = sorted(set(launch_fp["config"].get("fonts", [])) | set(MIXED_OS_CONTEXT_FONTS))
        try:
            async with AsyncCamoufox(
                fingerprint_preset=launch_fp["preset"],
                os="windows",
                fonts=launch_fonts,
                headless=True,
            ) as browser:
                bare = await (await browser.new_context()).new_page()
                launch_platform = await bare.evaluate("navigator.platform")
                context = await browser.new_context(**mac_fp["context_options"])
                await context.add_init_script(mac_fp["init_script"])
                page = await context.new_page()
                await page.goto("about:blank")
                platform = await page.evaluate("navigator.platform")
                result = await page.evaluate(MEASURE_TEXT_JS)
            break
        except ValueError as e:
            if "WebGL" in str(e):
                continue
            raise
    else:
        raise RuntimeError(f"Could not find a valid preset after {max_attempts} attempts")

    widths = result["widths"]
    baseline = result["baseline"]
    print(f"  launch navigator.platform:  {launch_platform}")
    print(f"  context navigator.platform: {platform}")
    for name, w in widths.items():
        tag = " (baseline)" if w == baseline else ""
        print(f"    {name:20s}  {w}{tag}")

    if launch_platform != "Win32" or platform != "MacIntel":
        print("  FAIL: the launch or the context did not take its platform -- "
              "this arm measures nothing")
        return False

    helvetica, neue = widths["Helvetica"], widths["Helvetica Neue"]
    if helvetica == baseline:
        print("  SKIP: Helvetica not available as a named font")
        return True
    if helvetica == neue:
        print("  NOTE: Helvetica and Helvetica Neue measure the same -- this arm "
              "cannot tell the context's platform from the sans row")

    if widths["system-ui"] == helvetica:
        print("  PASS: system-ui follows the context's platform (Helvetica)")
        return True
    if widths["system-ui"] == neue:
        print("  FAIL: system-ui fell to the sans row (Helvetica Neue) -- the "
              "launch's platform picked the family (#138)")
        return False
    print(f"  FAIL: system-ui width {widths['system-ui']} matches neither Helvetica "
          f"({helvetica}) nor Helvetica Neue ({neue})")
    return False


async def main() -> int:
    all_passed = True
    for target_os in ["macos", "windows"]:
        print(f"\n=== {target_os} ===")
        passed = await test_os(target_os)
        if not passed:
            all_passed = False

    print("\n=== macos context in a windows launch (#138) ===")
    if not await test_mixed_os_context():
        all_passed = False

    print()
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
