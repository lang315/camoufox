"""
Verify a context's own font and voice lists reach every content process that
renders one of its pages (#149).

setFontList / setSpeechVoices store the list in a per-process table. With
Fission every new page gets its own process, so each process has to receive the
list through that context's own init script. Before #149 the setter's
"already called" flag was stored cross-process, so it hid the setter from every
later process and only a context's first page carried its list. Every later page
fell back to the launch-level list.

How this guard measures it:

  * Context A's list is the generated list minus Georgia. The launch list is the
    same list plus Georgia, so only the per-context list can refuse it.
  * Context B's list includes Georgia: the positive control. Georgia must
    render there, or a refusal in A proves nothing.
  * A opens pages on two origins and a second same-origin page. Every one must
    refuse Georgia.
  * The fontlist log must show A's pages in at least two content processes, or
    the run could not have seen the bug. Each of those processes must have
    installed A's list (a "CAMOU-FL set ctx=A" line).
  * getVoices() must return the same count on every page of A, when the host has
    voices at all.

Rendered versus refused is read under two fallbacks whose widths differ: a
family that renders measures the same under both.
"""

import asyncio
import functools
import http.server
import os
import re
import sys
import tempfile
import threading
from pathlib import Path

PROBE = "Georgia"
SAMPLE = "mmmmmmmmmmlliWWQ@#"

MEASURE_JS = """async (probe) => {
    const s = %r;
    const c = document.createElement('canvas').getContext('2d');
    const w = (f) => { c.font = '72px ' + f; return c.measureText(s).width; };
    const cands = ['sans-serif', 'monospace', 'serif'];
    let pair = null;
    for (const a of cands) for (const b of cands)
        if (!pair && a !== b && w(a) !== w(b)) pair = [a, b];
    let vs = speechSynthesis.getVoices();
    for (let i = 0; i < 30 && !vs.length; i++) {
        await new Promise(r => setTimeout(r, 100));
        vs = speechSynthesis.getVoices();
    }
    if (!pair) return { valid: false, voices: vs.length };
    const [a, b] = pair;
    const pa = w('"' + probe + '", ' + a), pb = w('"' + probe + '", ' + b);
    return { valid: true, rendered: pa === pb, refused: pa === w(a) && pb === w(b),
             voices: vs.length };
}""" % SAMPLE


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve(root):
    srv = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(_Quiet, directory=root))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1]


def context_processes(logdir, path):
    """{ctx id: [log text of each process that rendered a page at `path`]}"""
    by_ctx = {}
    for f in logdir.glob("cfx*"):
        text = f.read_text(errors="replace")
        for ctx in set(re.findall(r"CAMOU-FL group \S+ ctx=(\d+) hop=\S+ uri=\S+" + re.escape(path), text)):
            by_ctx.setdefault(ctx, []).append(text)
    return by_ctx


async def main() -> int:
    from camoufox.async_api import AsyncCamoufox
    from camoufox.fingerprints import generate_context_fingerprint, get_random_preset

    site = tempfile.mkdtemp(prefix="guard149-")
    for name in ("a.html", "b.html"):
        Path(site, name).write_text("<!doctype html><meta charset=utf-8><body></body>")
    port = serve(site)
    # Not /tmp: the Linux content sandbox gives content processes their own
    # view of it, so their per-process logs would not land where this reads.
    work = Path(__file__).resolve().parents[2] / ".ci-work"
    work.mkdir(exist_ok=True)
    logdir = Path(tempfile.mkdtemp(prefix="guard149-log-", dir=work))
    os.environ["MOZ_LOG"] = "fontlist:4,sync,append"
    os.environ["MOZ_LOG_FILE"] = str(logdir / "cfx%PID")

    for _ in range(15):
        preset = get_random_preset(os="windows")
        base = generate_context_fingerprint(preset=preset)
        fonts = sorted(set(base["config"].get("fonts", [])) - {PROBE})
        fp_a = generate_context_fingerprint(preset=preset, config_overrides={"fonts": fonts})
        fp_b = generate_context_fingerprint(preset=preset, config_overrides={"fonts": fonts + [PROBE]})
        try:
            async with AsyncCamoufox(fingerprint_preset=preset, os="windows",
                                     fonts=fonts + [PROBE], headless=True) as browser:
                ctx_b = await browser.new_context(**fp_b["context_options"])
                await ctx_b.add_init_script(fp_b["init_script"])
                page_b = await ctx_b.new_page()
                await page_b.goto(f"http://127.0.0.1:{port}/b.html")
                control = await page_b.evaluate(MEASURE_JS, PROBE)

                ctx_a = await browser.new_context(**fp_a["context_options"])
                await ctx_a.add_init_script(fp_a["init_script"])
                rows = []
                for host in ("127.0.0.1", "localhost", "127.0.0.1"):
                    page = await ctx_a.new_page()
                    await page.goto(f"http://{host}:{port}/a.html")
                    rows.append((host, await page.evaluate(MEASURE_JS, PROBE)))
            break
        except ValueError as e:
            if "WebGL" in str(e):
                continue
            raise
    else:
        raise RuntimeError("Could not find a valid preset after 15 attempts")

    ok = True
    print(f"  control (context B, {PROBE} on its list): {control}")
    if not control.get("valid") or not control.get("rendered"):
        print(f"  FAIL: {PROBE} does not render where it is allowed -- this guard measures nothing")
        return 1

    for i, (host, r) in enumerate(rows):
        print(f"  context A page {i} on {host}: {r}")
        if not r.get("valid"):
            print(f"  FAIL: page {i}: no two fallbacks differ, so nothing can be read")
            ok = False
        elif not r["refused"]:
            print(f"  FAIL: page {i} renders {PROBE}: its process answered from the launch list, "
                  f"not context A's (#149)")
            ok = False

    procs = context_processes(logdir, "/a.html")
    files = sorted(f.name for f in logdir.glob("cfx*"))
    print(f"  log files: {len(files)} ({sum(n.startswith('cfx-child') for n in files)} content) in {logdir}")
    if len(procs) != 1:
        print(f"  FAIL: expected one context id behind /a.html, found {sorted(procs)}")
        return 1
    ctx, texts = next(iter(procs.items()))
    installed = [bool(re.search(rf"CAMOU-FL set ctx={ctx} ", t)) for t in texts]
    print(f"  context A is ctx={ctx}, rendered in {len(texts)} content process(es), "
          f"list installed in {sum(installed)}")
    if len(texts) < 2:
        print("  FAIL: every page shared one process, so this run cannot see #149")
        ok = False
    elif not all(installed):
        print("  FAIL: a process rendered context A without installing its list (#149)")
        ok = False

    counts = {r["voices"] for _, r in rows}
    if counts == {0}:
        print("  SKIP voices: the host reports none")
    elif len(counts) != 1:
        print(f"  FAIL: getVoices() differs between pages of one context: {[r['voices'] for _, r in rows]}")
        ok = False

    print("  PASS" if ok else "  FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
