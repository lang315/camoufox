#!/usr/bin/env python3
"""Measure the font read paths that only a native macOS host can see (#148).

    PYTHONPATH=pythonlib python3 build-tester/scripts/probe_macos_font_paths.py \
        --executable-path /path/Camoufox.app/Contents/MacOS/camoufox --logdir out/

Run it against the packaged app, so the font universe is the one that ships:
the host's fonts plus the bundled windows and linux sets (`package-macos`
bundles every OS except the target's own).

PART 1: HOST PATHS, one launch per spoofed OS
---------------------------------------------
  a   Optima, a host font on the mac list only and not bundled. It must be
      refused under a windows or linux spoof. Under a mac spoof it is forced
      into the list as the positive control.
  a'  JetBrains Mono, user-installed and on no list. Refused everywhere.
  b   local() by full and PostScript name, plus a bundled Arial control.
  c   system-ui against Helvetica, Segoe UI and sans-serif.
  d   codepoint fallback, read from the sys-fallback and global-fallback lines,
      never from pixels. Every resolved family must be on the context's list.
  e   every allowed=1 answer for a family off the context's list. Context-0
      lines from before the process received any list are reported apart, as
      "startup" (InitFontList's last-resort default).

Each page is measured on http and on file. On builds before the #149 fix
the two were not the same measurement: the file page ran in a content process
that never received the context's list, so its rows described the launch-level
mask. The per-process summary line (set / hasList) says which one applied.

PART 2: IS THE CONTEXT'S LIST IN EVERY PROCESS THAT RENDERS ITS PAGES?
----------------------------------------------------------------------
The launch list is the context's list plus Optima. Six pages of one context go
to three origins. A page in a process that holds the context's list refuses
Optima. A page in a process that never ran setFontList falls to the launch
mask and renders it. speechSynthesis.getVoices() is counted on the same pages.

HOW A READING EARNS ITS VERDICT
-------------------------------
Each family is measured under two fallbacks whose widths differ on that page.
A family that renders measures the same under both, and a refused one tracks
its fallback. The pair is chosen at run time from the generics and then from
the context's own list, because on some pages every generic collapses onto one
face. Equal floors read INVALID, never PASS. A positive control that does not
render makes its arm meaningless, so check the mac rows first.
"""

import argparse
import asyncio
import functools
import http.server
import json
import os
import re
import tempfile
import threading
from pathlib import Path

HOST_MAC_ONLY = "Optima"
HOST_UNLISTED = "JetBrains Mono"
LOCAL_MAC = 'local("Optima Regular"), local("Optima-Regular")'
LOCAL_UNL = 'local("JetBrainsMono-Regular"), local("JetBrains Mono Regular Regular")'
ABSENT = "Zq Absent Family 148"
# Emoji, Apple logo (PUA), command key, Cherokee, Yi, Tibetan.
FALLBACK_CHARS = [0x1F600, 0xF8FF, 0x2318, 0x13A0, 0xA000, 0x0F00]

MEASURE = r"""
const s = 'mmmmmmmmmmlliWWQ@#';
const c = document.createElement('canvas').getContext('2d');
const w = (f) => { c.font = '72px ' + f; return c.measureText(s).width; };
const pickPair = (extra) => {
  const cand = ['serif', 'monospace', 'sans-serif', 'cursive', 'fantasy', ...extra.map(f => `"${f}"`)];
  for (const a of cand) for (const b of cand) if (a !== b && w(a) !== w(b)) return [a, b];
  return ['serif', 'monospace'];
};
"""

HOST_JS = r"""
async ([macOnly, unlisted, absent, localMac, localUnl, fbChars, allowed]) => {
""" + MEASURE + r"""
  const [gA, gB] = pickPair(allowed);
  const pair = (fam) => ({ a: w(`"${fam}", ${gA}`), b: w(`"${fam}", ${gB}`) });

  const st = document.createElement('style');
  st.textContent = `
    @font-face { font-family: "CssLocalMac"; src: ${localMac}; }
    @font-face { font-family: "CssLocalUnl"; src: ${localUnl}; }`;
  document.head.appendChild(st);
  for (const f of ['CssLocalMac', 'CssLocalUnl']) {
    const sp = document.createElement('span');
    sp.style.fontFamily = `"${f}", serif`; sp.textContent = s; document.body.appendChild(sp);
  }
  for (const cp of fbChars) {
    const d = document.createElement('div');
    d.style.fontFamily = `"${absent}"`; d.textContent = String.fromCodePoint(cp);
    document.body.appendChild(d); void d.offsetWidth;
  }
  const status = {};
  for (const [k, src] of [['ApiLocalMac', localMac], ['ApiLocalUnl', localUnl],
                          ['ApiLocalArial', 'local("Arial"), local("ArialMT")']]) {
    const ff = new FontFace(k, src); document.fonts.add(ff);
    try { await ff.load(); } catch (e) {}
    status[k] = ff.status;
  }
  await document.fonts.ready;
  for (const r of document.fonts) {
    const fam = r.family.replace(/"/g, '');
    if (fam.startsWith('Css')) status[fam] = r.status;
  }
  const measured = {};
  for (const f of [macOnly, unlisted, absent, 'Helvetica', 'Segoe UI', 'Arial',
                   'CssLocalMac', 'CssLocalUnl', 'ApiLocalMac', 'ApiLocalUnl', 'ApiLocalArial'])
    measured[f] = pair(f);
  return {
    platform: navigator.platform, floors: { a: w(gA), b: w(gB), pair: [gA, gB] },
    measured, status,
    systemUi: { 'system-ui': w('system-ui'), 'sans-serif': w('sans-serif'),
                // monospace, never system-ui: a refused family would fall back onto
                // the very value it is compared with (lesson 4).
                Helvetica: w('"Helvetica", monospace'), 'Segoe UI': w('"Segoe UI", monospace'),
                monospace: w('monospace') },
  };
}
"""

PAGE_JS = r"""
async ([allowed]) => {
""" + MEASURE + r"""
  const [gA, gB] = pickPair(allowed);
  let vs = speechSynthesis.getVoices();
  for (let i = 0; i < 30 && !vs.length; i++) { await new Promise(r => setTimeout(r, 100)); vs = speechSynthesis.getVoices(); }
  return { opt: [w(`"Optima", ${gA}`), w(`"Optima", ${gB}`)], jet: [w(`"JetBrains Mono", ${gA}`), w(`"JetBrains Mono", ${gB}`)],
           floors: [w(gA), w(gB)], voices: vs.length };
}
"""


def verdict(p, fl):
    if fl["a"] == fl["b"]:
        return "INVALID"
    if p["a"] == p["b"]:
        return "RENDERED"
    if p["a"] == fl["a"] and p["b"] == fl["b"]:
        return "REFUSED"
    return "MIXED"


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve(root):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Quiet, directory=root))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1]


def processes(logdir):
    """One summary per content process that carries a real context id."""
    out = []
    for f in sorted(logdir.glob("cfx*")):
        t = f.read_text(errors="replace")
        if not re.search(r"CAMOU-FL \S+ ctx=[1-9]", t):
            continue
        out.append({
            "file": f.name,
            "set": t.count("CAMOU-FL set ctx="),
            "hasList1": len(re.findall(r"ctx=[1-9]\d* hasList=1", t)),
            "hasList0": len(re.findall(r"ctx=[1-9]\d* hasList=0", t)),
            "uris": sorted({u.split("/")[2] if "//" in u and u.split("/")[2] else u.split(":")[0]
                            for u in re.findall(r"uri=(\S+)", t)}),
            "text": t,
        })
    return out


def log_findings(logdir, fonts):
    allowed = {x.lower() for x in fonts}
    off_list = {"ctx": {}, "ctx0": {}, "startup": {}}
    fallback = {}
    want = {f"{c:04X}" for c in FALLBACK_CHARS}
    unfiltered = 0
    for p in processes(logdir):
        seen_set = False
        for ln in p["text"].splitlines():
            if "CAMOU-FL" not in ln:
                continue
            if "CAMOU-FL set ctx=" in ln:
                seen_set = True
            unfiltered += "default-unfiltered" in ln
            m = re.search(r"CAMOU-FL (gate|pref-fallback|facename) ctx=(\d+) .*?key=(.*?) allowed=1", ln)
            if m and m.group(3).lower() not in allowed:
                b = off_list["ctx"] if m.group(2) != "0" else off_list["ctx0" if seen_set else "startup"]
                k = f"{m.group(1)}:{m.group(3)}"
                b[k] = b.get(k, 0) + 1
            m = re.search(r"CAMOU-FL (?:sys|global)-fallback .*?ch=U\+([0-9A-F]+).*?resolved=(.*)$", ln)
            if m and m.group(1) in want:
                fallback.setdefault(m.group(1), set()).add(m.group(2).strip())
    fb = {k: ("OK" if all(r == "none" or r.lower() in allowed for r in v) else "LEAK") + " " + ",".join(sorted(v))
          for k, v in sorted(fallback.items())}
    return off_list, fb, unfiltered


async def launch(exe, spoof_os, extra_fonts, drop_fonts=()):
    from camoufox.async_api import AsyncCamoufox
    from camoufox.fingerprints import generate_context_fingerprint, get_random_preset

    for _ in range(15):
        preset = get_random_preset(os=spoof_os)
        base = generate_context_fingerprint(preset=preset)
        ctx_fonts = sorted((set(base["config"].get("fonts", [])) | set(extra_fonts)) - set(drop_fonts))
        fp = generate_context_fingerprint(preset=preset, config_overrides={"fonts": ctx_fonts})
        try:
            browser_cm = AsyncCamoufox(fingerprint_preset=fp["preset"], os=spoof_os, headless=True,
                                       executable_path=exe, fonts=ctx_fonts + list(drop_fonts))
            browser = await browser_cm.__aenter__()
        except ValueError as e:
            if "WebGL" in str(e):
                continue
            raise
        ctx = await browser.new_context(**fp["context_options"])
        await ctx.add_init_script(fp["init_script"])
        return browser_cm, ctx, ctx_fonts
    raise RuntimeError("no valid preset after 15 attempts")


def set_log(logdir):
    logdir.mkdir(parents=True, exist_ok=True)
    os.environ["MOZ_LOG"] = "fontlist:4,timestamp,sync,append"
    os.environ["MOZ_LOG_FILE"] = str(logdir / "cfx%PID")


async def part1(exe, root, urls):
    results = {}
    for spoof_os, extra in [("windows", []), ("linux", []), ("macos", [HOST_MAC_ONLY])]:
        for scheme, url in urls.items():
            logdir = root / "part1" / f"{spoof_os}-{scheme}"
            set_log(logdir)
            cm, ctx, fonts = await launch(exe, spoof_os, extra)
            try:
                page = await ctx.new_page()
                await page.goto(url)
                allowed = [f for f in fonts if f not in (HOST_MAC_ONLY, HOST_UNLISTED)]
                res = await page.evaluate(HOST_JS, [HOST_MAC_ONLY, HOST_UNLISTED, ABSENT, LOCAL_MAC, LOCAL_UNL,
                                                    FALLBACK_CHARS, allowed])
            finally:
                await cm.__aexit__(None, None, None)
            off_list, fb, unfiltered = log_findings(logdir, fonts)
            page_procs = [p for p in processes(logdir) if any(u.startswith(("127.0.0.1", "file")) for u in p["uris"])]
            res.update(verdicts={k: verdict(v, res["floors"]) for k, v in res["measured"].items()},
                       off_list=off_list, fallback=fb, default_unfiltered=unfiltered,
                       page_process={k: [p[k] for p in page_procs] for k in ("set", "hasList1", "hasList0")},
                       listHasMacOnly=HOST_MAC_ONLY in fonts)
            results[f"{spoof_os}-{scheme}"] = res
            print(f"\n=== {spoof_os} spoof, {scheme} page (platform={res['platform']}, "
                  f"{HOST_MAC_ONLY} in list={res['listHasMacOnly']}, page process {res['page_process']}, "
                  f"floor pair {res['floors']['pair']})")
            for k, v in res["verdicts"].items():
                print(f"  {k:22s} {v}")
            print(f"  status              {res['status']}")
            print(f"  system-ui           {res['systemUi']}")
            print(f"  allowed off-list    {off_list}")
            print(f"  fallback            {fb}")
            print(f"  default-unfiltered  {unfiltered}")
    return results


async def part2(exe, root, urls):
    logdir = root / "part2"
    set_log(logdir)
    cm, ctx, fonts = await launch(exe, "macos", [], drop_fonts=[HOST_MAC_ONLY])
    rows = []
    try:
        allowed = [f for f in fonts if f not in (HOST_MAC_ONLY, HOST_UNLISTED)]
        order = [urls["http"], urls["http2"], urls["file"]] * 2
        for i, url in enumerate(order):
            page = await ctx.new_page()
            await page.goto(url)
            r = await page.evaluate(PAGE_JS, [allowed])
            fl = {"a": r["floors"][0], "b": r["floors"][1]}
            rows.append({"page": i, "url": url.split("/")[2] or "file",
                         "Optima": verdict({"a": r["opt"][0], "b": r["opt"][1]}, fl),
                         "JetBrains Mono": verdict({"a": r["jet"][0], "b": r["jet"][1]}, fl),
                         "voices": r["voices"]})
    finally:
        await cm.__aexit__(None, None, None)
    print(f"\n=== part 2: one macos context, launch list = context list + {HOST_MAC_ONLY}")
    for r in rows:
        print("  page {page} {url:18s} Optima {Optima:9s} JetBrains Mono {JetBrains Mono:9s} voices {voices}".format(**r))
    procs = [{k: p[k] for k in ("file", "set", "hasList1", "hasList0", "uris")} for p in processes(logdir)]
    for p in procs:
        print(f"  {p['file']}: set={p['set']} hasList=1:{p['hasList1']} hasList=0:{p['hasList0']} uris={p['uris']}")
    return {"pages": rows, "processes": procs}


async def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--executable-path", required=True)
    ap.add_argument("--logdir", default="macos-font-paths")
    args = ap.parse_args()
    root = Path(args.logdir).resolve()
    site = tempfile.mkdtemp(prefix="probe148-")
    Path(site, "blank.html").write_text("<!doctype html><html><head><meta charset=utf-8></head><body></body></html>")
    port = serve(site)
    urls = {"http": f"http://127.0.0.1:{port}/blank.html", "file": Path(site, "blank.html").as_uri(),
            "http2": f"http://localhost:{port}/blank.html"}
    out = {"part1": await part1(args.executable_path, root, {"http": urls["http"], "file": urls["file"]}),
           "part2": await part2(args.executable_path, root, urls)}
    (root / "result.json").write_text(json.dumps(out, indent=2))
    print(f"\nwrote {root / 'result.json'}")


if __name__ == "__main__":
    asyncio.run(main())
