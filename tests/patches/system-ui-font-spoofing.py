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
import os
import re
import shutil
import sys
import tempfile
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


# #138: a macOS context inside a Windows launch. system-ui must resolve from the
# CONTEXT's navigator.platform ("MacIntel" -> Helvetica), not the launch's
# ("Win32" -> Segoe UI, which the context's list refuses, so the step would fall
# to the #92 sans row).
#
# Font universe this arm runs in (CLAUDE.md lesson 8): a Windows launch on a
# Linux host. utils._generate_fontconfig hands fontconfig bundle/fontconfig/
# windows/fonts.conf and ONLY the groups `readBy.win` lists (LMW+LW+MW+W), so the
# macOS-only faces (Helvetica, Helvetica Neue, Menlo) are not on the search path,
# and that conf rewrites the name Helvetica to Arial (a GDI FontSubstitutes
# entry) before the font gate sees it. A context whose OS differs from the
# launch's therefore cannot render its own OS's exclusive faces, and a width can
# no longer tell the context's platform from the launch's: the family system-ui
# should land on does not render, and the fallbacks that do render are the
# same whichever platform was asked. So the arm is scored on the log line the
# step writes (docs/fonts-gating.md, "system-ui"), and widths only decide
# whether the arm can be read at all.
#
# "Arial" is in the list because the rewrite makes it the family the gate is
# asked about for the name "Helvetica": without it the step's lookup finds
# nothing and neither platform could ever log a system-ui step.
MIXED_OS_CONTEXT_FONTS = ["Helvetica", "Helvetica Neue", "Menlo", "Arial"]
MIXED_OS_URI = "data:text/html,<h1>sysui138</h1>"
SYSTEM_UI_GENERIC = 7  # StyleGenericFontFamily::SystemUi in the generic-map line


def system_ui_steps(logdir: Path, uri: str):
    """(context ids that rendered `uri`, [(step, key)] of their system-ui lookups)."""
    texts = [f.read_text(errors="replace") for f in logdir.glob("cfx*")]
    ctxs = {c for t in texts
            for c in re.findall(r"CAMOU-FL group \S+ ctx=(\d+) hop=\S+ uri=" + re.escape(uri), t)}
    steps = [(step, key.strip()) for t in texts
             for ctx, step, key in re.findall(
                 rf"CAMOU-FL generic-map ctx=(\d+) generic={SYSTEM_UI_GENERIC} "
                 r"step=(\S+) key=(.*)", t)
             if ctx in ctxs]
    return ctxs, steps


async def test_mixed_os_context(max_attempts: int = 15) -> bool:
    from camoufox.async_api import AsyncCamoufox
    from camoufox.fingerprints import generate_context_fingerprint, get_random_preset

    # Not /tmp: the Linux content sandbox gives content processes their own
    # view of it, so their per-process logs would not land where this reads.
    work = Path(__file__).resolve().parents[2] / ".ci-work"
    work.mkdir(exist_ok=True)
    logdir = Path(tempfile.mkdtemp(prefix="sysui138-log-", dir=work))
    os.environ["MOZ_LOG"] = "fontlist:4,sync,append"
    os.environ["MOZ_LOG_FILE"] = str(logdir / "cfx%PID")
    try:
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
                    await page.goto(MIXED_OS_URI)
                    platform = await page.evaluate("navigator.platform")
                    result = await page.evaluate(MEASURE_TEXT_JS)
                break
            except ValueError as e:
                if "WebGL" in str(e):
                    continue
                raise
        else:
            raise RuntimeError(f"Could not find a valid preset after {max_attempts} attempts")

        ctxs, steps = system_ui_steps(logdir, MIXED_OS_URI)
    finally:
        os.environ.pop("MOZ_LOG", None)
        os.environ.pop("MOZ_LOG_FILE", None)
        shutil.rmtree(logdir, ignore_errors=True)

    widths = result["widths"]
    baseline = result["baseline"]
    print(f"  launch navigator.platform:  {launch_platform}")
    print(f"  context navigator.platform: {platform}")
    for name, w in widths.items():
        tag = " (baseline)" if w == baseline else ""
        print(f"    {name:20s}  {w}{tag}")
    print(f"  context ids that rendered the page: {sorted(ctxs)}; system-ui steps: {steps}")

    # Registered, never asserted in place: every check below runs, so one red
    # does not hide the readings of the others.
    failures = []

    if launch_platform != "Win32" or platform != "MacIntel":
        failures.append("the launch or the context did not take its platform -- "
                        "this arm measures nothing")
    # Precondition, not the verdict. The step only logs when its lookup of
    # "Helvetica" resolves, and that lookup is the canvas's named lookup. If the
    # name does not render here, a missing step=system-ui line says nothing about
    # which platform was asked.
    if widths["Helvetica"] == baseline:
        failures.append("Helvetica does not resolve in this font universe (rewritten to "
                        "Arial, which this list admits) -- the step cannot log, so this "
                        "arm measures nothing")
    if len(ctxs) != 1:
        failures.append(f"expected exactly one context id behind {MIXED_OS_URI}, found "
                        f"{sorted(ctxs)} -- the log cannot be attributed to the context")
    elif not steps:
        failures.append("no `CAMOU-FL generic-map ... generic=7` line for the context -- "
                        "the log module did not capture the step, so this arm measures nothing")
    else:
        # The verdict. A line `step=system-ui key=helvetica` can only come from
        # the context's own platform (MacIntel): the launch's (Win32) would ask
        # for "segoe ui", which this list refuses, and log `step=row` instead.
        # So the pass value and the fail value are different literals by
        # construction. WHAT WOULD PASS WRONGLY: a line naming "helvetica" from a
        # different context -- ruled out by filtering to the one ctx that rendered
        # this page's unique URI. WHAT WOULD FAIL WRONGLY: the log missing a step
        # that ran -- ruled out above by requiring at least one system-ui line.
        wrong = [s for s in steps if s != ("system-ui", "helvetica")]
        if wrong:
            failures.append(f"system-ui did not resolve from the context's platform: {wrong} "
                            "-- the launch's platform picked the family (#138)")

    for failure in failures:
        print(f"  FAIL: {failure}")
    if not failures:
        print("  PASS: system-ui follows the context's platform (step=system-ui key=helvetica)")
    return not failures


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
