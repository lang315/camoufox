#!/usr/bin/env python3
"""
Guard: a worker reads the same per-context navigator values as its page.

WorkerNavigator::GetPlatform, GetUserAgent and HardwareConcurrency
(navigator-spoofing.patch) ask RoverfoxStorageManager off the main thread.
Since the storage stopped touching libpref off the main thread, those reads
answer from the local cache alone, which InitPrefMirror() fills from the
process's prefs and keeps current through a prefix callback
(anti-font-fingerprinting.patch, ContentChild::InitXPCOM).

The discriminating arm is a macOS context inside a Windows launch: if the
cache were empty on the worker thread, WorkerNavigator would fall back to the
launch-level MaskConfig and the worker would say Win32 while its page says
MacIntel. A worker that merely agrees with its page is not enough, since both
could have fallen to the launch value.

A third arm launches with only a launch-level hardwareConcurrency, one that is not
the host's core count, and reads it first thing in a fresh page and in a fresh
worker. Each navigator resolves its value on its first read and then answers from
that; a first read that fell through to stock would report the host's count and
fail here, where an arm that only compares page with worker would pass.

Exit 0 on pass, 1 on fail.
"""

import asyncio
import os
import sys

WORKER_PROBE_JS = """() => new Promise((resolve, reject) => {
    const src = 'postMessage({platform: navigator.platform,'
        + ' userAgent: navigator.userAgent,'
        + ' hardwareConcurrency: navigator.hardwareConcurrency})';
    const url = URL.createObjectURL(new Blob([src], {type: 'application/javascript'}));
    const w = new Worker(url);
    w.onmessage = (e) => { w.terminate(); resolve(e.data); };
    w.onerror = (e) => reject(new Error(e.message || 'worker error'));
})"""

PAGE_PROBE_JS = """() => ({platform: navigator.platform,
    userAgent: navigator.userAgent,
    hardwareConcurrency: navigator.hardwareConcurrency})"""

FIELDS = ("platform", "userAgent", "hardwareConcurrency")


def check(label: str, page: dict, worker: dict, expected_platform: str) -> bool:
    ok = True
    print(f"\n=== {label} ===")
    for f in FIELDS:
        tag = "" if page[f] == worker[f] else "  <-- MISMATCH"
        print(f"  {f:20s} page={page[f]!r} worker={worker[f]!r}{tag}")
        if page[f] != worker[f]:
            ok = False
    if page["platform"] != expected_platform:
        print(f"  FAIL: page platform {page['platform']!r} is not {expected_platform!r} -- "
              "this arm measures nothing")
        return False
    if worker["platform"] != expected_platform:
        print(f"  FAIL: worker platform {worker['platform']!r} is not {expected_platform!r}")
        return False
    print("  PASS" if ok else "  FAIL: worker and page disagree")
    return ok


async def launch_value_arm() -> bool:
    """A launch-level hardwareConcurrency, read first in a fresh page and worker."""
    from camoufox.async_api import AsyncCamoufox

    # Never the host's count: stock would answer it too, and the arm would pass
    # on a spoof that was lost.
    host = os.cpu_count() or 1
    want = next(n for n in (3, 6, 12) if n != host)
    print(f"\n=== launch-level hardwareConcurrency {want} (host has {host}) ===")
    async with AsyncCamoufox(config={"navigator.hardwareConcurrency": want},
                             headless=True, i_know_what_im_doing=True) as browser:
        page = await browser.new_page()
        await page.goto("about:blank")
        first = await page.evaluate("navigator.hardwareConcurrency")
        worker = (await page.evaluate(WORKER_PROBE_JS))["hardwareConcurrency"]
    ok = first == want and worker == want
    print(f"  first page read={first} first worker read={worker}  "
          f"{'PASS' if ok else 'FAIL: the launch value was lost'}")
    return ok


async def main(max_attempts: int = 15) -> int:
    from camoufox.async_api import AsyncCamoufox
    from camoufox.fingerprints import generate_context_fingerprint, get_random_preset

    for _ in range(max_attempts):
        launch_fp = generate_context_fingerprint(preset=get_random_preset(os="windows"))
        mac_fp = generate_context_fingerprint(preset=get_random_preset(os="macos"))
        try:
            async with AsyncCamoufox(
                fingerprint_preset=launch_fp["preset"],
                os="windows",
                headless=True,
            ) as browser:
                win_page = await (await browser.new_context()).new_page()
                await win_page.goto("about:blank")
                win = (await win_page.evaluate(PAGE_PROBE_JS),
                       await win_page.evaluate(WORKER_PROBE_JS))

                context = await browser.new_context(**mac_fp["context_options"])
                await context.add_init_script(mac_fp["init_script"])
                mac_page = await context.new_page()
                await mac_page.goto("about:blank")
                mac = (await mac_page.evaluate(PAGE_PROBE_JS),
                       await mac_page.evaluate(WORKER_PROBE_JS))
            break
        except ValueError as e:
            if "WebGL" in str(e):
                continue
            raise
    else:
        raise RuntimeError(f"Could not find a valid preset after {max_attempts} attempts")

    passed = check("windows launch, launch-level context", *win, "Win32")
    passed &= check("macos context in a windows launch", *mac, "MacIntel")
    passed &= await launch_value_arm()
    print()
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
