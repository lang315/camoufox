"""
Verify a context's own font and voice lists reach every content process that
renders one of its pages (#149).

With Fission every new page of a context can get its own process, but only the
first document calls setFontList / setSpeechVoices: the setter's "already
called" flag is shared by every process. Before #149 the list itself was kept
per process, so only a context's first page carried it, and every later page
fell back to the launch-level list. The list now lives in the same shared
store (RoverfoxStorageManager), and each process parses it on first use.

How this guard measures it:

  * Context A's list is the generated list minus Georgia. The launch list is the
    same list plus Georgia, so only the per-context list can refuse it.
  * Context B's list includes Georgia: the positive control. Georgia must
    render there, or a refusal in A proves nothing.
  * A opens pages on two origins and a second same-origin page. Every one must
    refuse Georgia.
  * The parent's ProcessIsolation log must show A's two origins isolated
    apart, so they ran in different content processes; otherwise the run could
    not have seen the bug. It is read from the parent because the parent is
    unsandboxed. On Linux the content processes' own log files are not a
    process count: the guard-only run on main saw one file while its pages
    plainly ran in several.
  * getVoices() must return the same count on every page of A, when the host has
    voices at all.
  * Flush arm. A lookup that ran in a process before A's list reached it
    answered without the list (`CAMOU-FL gate ... hasList=0`), and the font
    caches memoized that answer. The list arrives through `CAMOU-FL set` in the
    setter's process, and through RoverfoxStorageManager's pref callback,
    `CAMOU-FL flush`, everywhere else. Read per process, from the pid in each
    line's prefix, since several processes can share one log file: every
    process with a hasList=0 lookup for A must log an arrival after it, and no
    process may log a hasList=0 lookup for A after its arrival. At least one
    `set` line for A must be read, or the reader measured nothing, and at
    least one `flush ... fontlist=1` line from a content process, or the
    callback never ran where lookups happen (the parent flushes too).
    Whether a later process's first lookup already had the list is printed
    per process. The
    arm checks ordering only: a stale memo answers above the gate and writes
    no `gate` line, so a leak through one is read by the refusal checks above,
    not here. "Without the list after its arrival" counts main-thread lookups
    only, because a worker's gate line can be written after a flush line it
    was computed before.

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


def process_lines(logdir):
    """{"Child <pid>" or "Parent <pid>": [CAMOU-FL message, ...]} in log order.
    The process comes from each line's prefix, since several processes can
    share one log file."""
    by_pid = {}
    for f in sorted(logdir.glob("cfx*")):
        for line in f.read_text(errors="replace").splitlines():
            m = re.search(r"\[(Child|Parent) (\d+):[^\]]*\]: \S+ (CAMOU-FL .*)", line)
            if m:
                by_pid.setdefault(f"{m.group(1)} {m.group(2)}", []).append(m.group(3))
    return by_pid


def flush_arm(logdir, ctx):
    """False when a process answered context `ctx` without its list after the
    list had arrived there, or never received it after answering without it,
    or when no set or flush line for `ctx` was read at all."""
    ok = True
    sets = flushes = 0
    for pid, msgs in sorted(process_lines(logdir).items()):
        arrivals = [i for i, m in enumerate(msgs) if re.match(rf"CAMOU-FL (set|flush) ctx={ctx}\b", m)]
        lookups = [(i, "hasList=1" in m, m.endswith(" main=1")) for i, m in enumerate(msgs)
                   if re.match(rf"CAMOU-FL gate ctx={ctx} ", m)]
        sets += sum(m.startswith(f"CAMOU-FL set ctx={ctx} ") for m in msgs)
        # Only a content process with a live font list shows the callback ran
        # where lookups happen; the parent flushes too.
        if pid.startswith("Child "):
            flushes += sum(m == f"CAMOU-FL flush ctx={ctx} fontlist=1" for m in msgs)
        if not lookups and not arrivals:
            continue
        first = arrivals[0] if arrivals else None
        blind = [i for i, has, _ in lookups if not has]
        # Main thread only: a worker's gate line can be written after a flush
        # line it was computed before.
        blind_main = [i for i, has, main in lookups if not has and main]
        print(f"  {pid}: lookups {len(lookups)}, without the list {len(blind)}, "
              f"first lookup had the list: {lookups[0][1] if lookups else '-'}, "
              f"arrival before first lookup: "
              f"{'-' if not lookups else first is not None and first < lookups[0][0]} "
              f"({'set' if any(msgs[i].startswith('CAMOU-FL set') for i in arrivals) else 'flush' if arrivals else 'none'})")
        if blind and first is None:
            print(f"  FAIL flush: {pid} answered context {ctx} without its list and never "
                  f"received it, so its memoized answers were never flushed")
            ok = False
        elif first is not None and any(i > first for i in blind_main):
            print(f"  FAIL flush: {pid} answered context {ctx} without its list after the "
                  f"list had arrived")
            ok = False
    if sets == 0:
        print(f"  FAIL flush: no CAMOU-FL set line for context {ctx} was read, so this arm "
              f"measured nothing")
        ok = False
    if flushes == 0:
        print(f"  FAIL flush: no content process logged CAMOU-FL flush ctx={ctx} with its "
              f"font list live: the storage pref callback never ran where lookups happen")
        ok = False
    return ok


async def main() -> int:
    from camoufox.async_api import AsyncCamoufox
    from camoufox.fingerprints import generate_context_fingerprint, get_random_preset

    site = tempfile.mkdtemp(prefix="guard149-")
    for name in ("a.html", "b.html"):
        Path(site, name).write_text("<!doctype html><meta charset=utf-8><body></body>")
    port = serve(site)
    # Not /tmp: the Linux content sandbox gives content processes their own
    # view of it, so their per-process logs would not land where this reads.
    work = Path(__file__).resolve().parents[4] / ".ci-work"
    work.mkdir(exist_ok=True)
    logdir = Path(tempfile.mkdtemp(prefix="guard149-log-", dir=work))
    os.environ["MOZ_LOG"] = "fontlist:4,ProcessIsolation:4,sync,append"
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
    if len(procs) != 1:
        print(f"  FAIL: expected one context id behind /a.html, found {sorted(procs)}")
        return 1
    ctx, texts = next(iter(procs.items()))
    installed = sum(bool(re.search(rf"CAMOU-FL set ctx={ctx} ", t)) for t in texts)
    print(f"  context A is ctx={ctx}; content logs that carry it: {len(texts)}, "
          f"with its list installed by the setter: {installed} (informational; only the "
          f"setter's process installs it, the others read it from the shared store)")

    parent = "".join(f.read_text(errors="replace") for f in logdir.glob("cfx-main*"))
    isolated = {}
    for behavior, host, suffix in re.findall(
            rf"Using IsolationBehavior (\w+) for http://(127\.0\.0\.1|localhost):{port}(\S*)", parent):
        if f"userContextId={ctx}" in suffix:
            isolated.setdefault(host, set()).add(behavior)
    print(f"  parent isolation for context A: { {h: sorted(b) for h, b in isolated.items()} }")
    if set(isolated) != {"127.0.0.1", "localhost"} or any(
            b & {"Parent", "Anywhere"} for b in isolated.values()):
        print("  FAIL: the parent log does not show A's two origins isolated apart, so this "
              "run cannot see #149")
        ok = False

    if not flush_arm(logdir, ctx):
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
