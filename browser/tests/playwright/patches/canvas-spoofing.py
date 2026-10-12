"""
Verify the fork's per-context canvas noise (canvas-spoofing.patch).

The seed is the context's, found through the document's principal
(RoverfoxStorageManager::UserContextId), so a canvas in a document without a
browsing context of its own gets its creator's noise. The patch used to walk
document -> inner window -> BrowsingContext instead. A DOMParser document has
no inner window, so its canvas read seed 0 and came back clean: a second,
unnoised answer for the same drawing in the same page.

Arm 1, a launch the canvas placeholder does not cover. Three contexts, whose
init scripts set seeds S1, S1 and S2, and no launch-level canvas:seed. Each
page draws one canvas in its own document and the same canvas in a DOMParser
document, then hashes getImageData of both:

    DOMParser S1 == DOMParser S1   the read rendered, and the noise is keyed by seed
    DOMParser S1 != DOMParser S2   the context's seed reached the DOMParser document
    page S1 == DOMParser S1        it is the seed the page's own canvas uses
    perturb lines carry S1 and S2  the log arm 2 counts can be read at all

With the old lookup all three DOMParser hashes are the unnoised canvas, so the
second check fails.

Arm 2, a covered launch: the RFP canvas targets the launchers add for an
identity on another OS (python/src/camoufox/host_rendering.py). Its context
sets a seed anyway, so what is measured is that every read takes the
placeholder before the fork's perturb, not that no seed was set. The page's
own canvas and the DOMParser canvas are read in two separate launches, each
with its own log, because a perturb line does not name its document. For each
of them:

    two getImageData reads differ  the placeholder answered
    a set line carries the seed    the seed arrived
    no perturb line                not for getImageData, toDataURL or toBlob

A DOMParser document has no channel, parent or opener, so
Document::RecomputeResistFingerprinting may not carry the launch's baseline
overrides into it. A red on the DOMParser half is therefore a real finding,
not a guard bug. Cross-OS canvas readback is covered by the RFP placeholder,
and a page that draws in a DOMParser document would escape it.

Perturbation is read from the patch's own CAMOU-CANVAS log lines, never from
pixels: the placeholder is random, so its pixels cannot show whether noise was
added to them.

Run from any venv that has playwright:
    python browser/tests/playwright/patches/canvas-spoofing.py --binary /path/to/camoufox-bin
"""

import asyncio
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import check, resolve_binary  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "python" / "src"))
from camoufox.host_rendering import add_canvas_placeholder  # noqa: E402
from camoufox.utils import get_pref_env_vars  # noqa: E402

S1, S2 = 2654435761, 40503
ORIGIN = "https://camoufox.test/"
# The probe runs as the page's own script: an isolated-world evaluate cannot
# read getImageData's pixels through the Xray. No text: a document without a
# window may resolve fonts differently, and the two canvases must render alike.
# ?read=page or ?read=parsed reads only that document's canvas.
PAGE = r"""<!doctype html><script>
(async () => {
  const read = new URLSearchParams(location.search).get('read') || 'both';
  const draw = (canvas) => {
    canvas.width = 256; canvas.height = 128;
    const ctx = canvas.getContext('2d', {willReadFrequently: true});
    ctx.fillStyle = '#2a6'; ctx.fillRect(0, 0, 256, 128);
    ctx.fillStyle = '#c33'; ctx.fillRect(16, 16, 96, 64);
    ctx.fillStyle = '#33c'; ctx.beginPath(); ctx.arc(176, 72, 40, 0, 2 * Math.PI); ctx.fill();
    return ctx;
  };
  const hash = async (ctx) => Array.from(new Uint8Array(await crypto.subtle.digest(
      'SHA-256', ctx.getImageData(0, 0, 256, 128).data))).map(b => b.toString(16).padStart(2, '0')).join('');
  const readAll = async (ctx) => {
    const hashes = [await hash(ctx), await hash(ctx)];
    ctx.canvas.toDataURL();
    await new Promise(resolve => ctx.canvas.toBlob(resolve));
    return hashes;
  };
  const probe = {};
  try {
    if (read !== 'parsed') {
      probe.page = await readAll(draw(document.createElement('canvas')));
    }
    if (read !== 'page') {
      const parsed = new DOMParser().parseFromString('<canvas></canvas>', 'text/html');
      probe.parsed = await readAll(draw(parsed.querySelector('canvas')));
    }
  } catch (e) {
    probe.error = String(e);
  }
  document.documentElement.dataset.probe = JSON.stringify(probe);
})();
</script>"""

WORK = REPO_ROOT / ".ci-work"


async def run(
    binary: Path, prefs: Dict[str, Any], seeds: Sequence[int], read: str
) -> Tuple[List[Dict[str, Any]], List[int], List[int]]:
    """One probe per context, each seeded by its own init script, and the seeds
    of this launch's CAMOU-CANVAS set and perturb lines."""
    from playwright.async_api import async_playwright

    # Not /tmp: the Linux content sandbox gives content processes their own
    # view of it, so their logs would not land where this reads.
    WORK.mkdir(exist_ok=True)
    logdir = Path(tempfile.mkdtemp(prefix="canvas-", dir=WORK))
    env = {
        **os.environ,
        "CAMOU_CONFIG_1": "{}",
        **get_pref_env_vars(prefs),
        "MOZ_LOG": "CamouCanvas:4,sync,append",
        "MOZ_LOG_FILE": str(logdir / "cfx%PID"),
    }
    results = []
    try:
        async with async_playwright() as p:
            browser = await p.firefox.launch(
                executable_path=str(binary), headless=True, env=env, firefox_user_prefs=prefs
            )
            try:
                for seed in seeds:
                    context = await browser.new_context()
                    # Playwright runs it on about:blank first; the setter is gone after that.
                    await context.add_init_script(
                        f'if (typeof window.setCanvasSeed === "function") window.setCanvasSeed({seed});'
                    )
                    page = await context.new_page()
                    await page.route(ORIGIN + "**", lambda route: route.fulfill(content_type="text/html", body=PAGE))
                    await page.goto(f"{ORIGIN}?read={read}")
                    handle = await page.wait_for_function("() => document.documentElement.dataset.probe")
                    results.append(json.loads(await handle.json_value()))
            finally:
                await browser.close()
        text = "".join(f.read_text(errors="replace") for f in logdir.glob("cfx*"))
    finally:
        shutil.rmtree(logdir, ignore_errors=True)

    def seeds_of(kind: str) -> List[int]:
        return [int(s) for s in re.findall(rf"CAMOU-CANVAS {kind} (?:ctx=\d+ )?seed=(\d+)", text)]

    return results, seeds_of("set"), seeds_of("perturb")


async def main() -> int:
    binary = resolve_binary()
    print(f"Binary: {binary}")
    failures: List[str] = []

    print("\n=== uncovered launch, contexts seeded S1, S1, S2 ===")
    (a, b, c), _, perturbed = await run(binary, {}, (S1, S1, S2), "both")
    for name, r in (("S1", a), ("S1 again", b), ("S2", c)):
        check(failures, f"context {name} reads its canvases", r.get("error"), None)
    if not any(r.get("error") for r in (a, b, c)):
        check(failures, "the page's canvas reads the same twice", a["page"][0], a["page"][1])
        check(failures, "DOMParser canvas, same seed, same noise", a["parsed"][0], b["parsed"][0])
        check(failures, "DOMParser canvas carries its context's seed", a["parsed"][0] != c["parsed"][0], True)
        check(failures, "DOMParser canvas has the page's noise", a["parsed"][0], a["page"][0])
    check(failures, "perturb lines carry S1 and S2", {S1, S2} <= set(perturbed), True)

    prefs: Dict[str, Any] = {}
    add_canvas_placeholder(prefs)
    for read, label in (("page", "page"), ("parsed", "DOMParser")):
        print(f"\n=== covered launch (canvas placeholder), context seeded S1, {label} canvas only ===")
        (covered,), set_seeds, perturbed = await run(binary, prefs, (S1,), read)
        check(failures, f"covered {label} canvas reads", covered.get("error"), None)
        if read in covered:
            check(failures, f"the placeholder answers the {label} canvas's getImageData",
                  covered[read][0] != covered[read][1], True)
        check(failures, f"the seed arrived ({label} launch)", S1 in set_seeds, True)
        check(failures, f"no {label} canvas read was perturbed", perturbed, [])

    print()
    if failures:
        print(f"FAIL: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("PASS: a context's seed reaches every document it creates, and the placeholder is read before the noise.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
