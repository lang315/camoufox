"""
Verify `src: local()` follows the same gate as `font-family` (#150).

Before #150 every local() source failed while a font mask applied, including a
face the page could render by family name, and a local()-only face took its
FontFace.status from its DECLARED family name. So `new FontFace("Arial",
'local("Arial")')` read `loaded` while rendering nothing. Stock Firefox renders
and loads all of them. Each disagreement is a tell.

Windows spoof. Context A's list is the generated list minus Georgia and Comic
Sans MS. The launch list adds Georgia back, so only A's own list can refuse it.
Context B's list holds both families: the positive control that they exist and
render at all.

  row                                  render    status
  local() of Arial (on A's list)       yes       loaded
  alias face -> local("ArialMT")       yes       loaded
  local() of Georgia (launch only)     no        error
  local() of Comic Sans MS (no list)   no        error
  CSS @font-face alias -> Arial        yes       loaded
  CSS @font-face local() of Georgia    no        error

Every row's status must also agree with its render.
"""

import asyncio
import functools
import http.server
import sys
import tempfile
import threading
from pathlib import Path

ALLOWED = 'local("Arial"), local("ArialMT")'
ROWS = [
    # (declared family, src, must render)
    ("Arial", ALLOWED, True),
    ("ZqLocalAlias", ALLOWED, True),
    ("Georgia", 'local("Georgia")', False),
    ("Comic Sans MS", 'local("Comic Sans MS"), local("ComicSansMS")', False),
]
# The same gate through a CSS @font-face rule, the InsertRuleFontFace path that
# FontFaceSet::Load/Check do not scope (CLAUDE.md lesson 2).
CSS_ROWS = [
    ("CssArialAlias", ALLOWED, True),
    ("CssGeorgia", 'local("Georgia")', False),
]
CONTROL = ["Georgia", "Comic Sans MS"]

JS = r"""async ([rows, control, cssRows]) => {
  const s = 'mmmmmmmmmmlliWWQ@#';
  const c = document.createElement('canvas').getContext('2d');
  const w = (f) => { c.font = '72px ' + f; return c.measureText(s).width; };
  const cands = ['serif', 'monospace', 'sans-serif'];
  let pair = null;
  for (const a of cands) for (const b of cands) if (!pair && a !== b && w(a) !== w(b)) pair = [a, b];
  if (!pair) return { valid: false };
  const [a, b] = pair;
  const rendered = (fam) => w(`"${fam}", ${a}`) === w(`"${fam}", ${b}`);
  const refused = (fam) => w(`"${fam}", ${a}`) === w(a) && w(`"${fam}", ${b}`) === w(b);
  const out = { valid: true, control: {}, rows: {} };
  for (const fam of control) out.control[fam] = rendered(fam);
  const st = document.createElement('style');
  st.textContent = cssRows.map(([f, src]) => `@font-face { font-family: "${f}"; src: ${src}; }`).join('\n');
  document.head.appendChild(st);
  for (const [fam] of cssRows) {
    const sp = document.createElement('span');
    sp.style.fontFamily = `"${fam}", serif`; sp.textContent = s;
    document.body.appendChild(sp); void sp.offsetWidth;
  }
  for (const [fam, src] of rows) {
    const ff = new FontFace(fam, src);
    document.fonts.add(ff);
    try { await ff.load(); } catch (e) {}
    out.rows[fam] = { status: ff.status };
  }
  await document.fonts.ready;
  for (const r of document.fonts) {
    const fam = r.family.replace(/"/g, '');
    if (cssRows.some(([f]) => f === fam)) out.rows[fam] = { status: r.status };
  }
  for (const [fam] of [...rows, ...cssRows]) {
    out.rows[fam] = out.rows[fam] || { status: 'missing' };
    out.rows[fam].rendered = rendered(fam);
    out.rows[fam].refused = refused(fam);
  }
  return out;
}"""


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve(root):
    srv = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(_Quiet, directory=root))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1]


async def main() -> int:
    from camoufox.async_api import AsyncCamoufox
    from camoufox.fingerprints import generate_context_fingerprint, get_random_preset

    site = tempfile.mkdtemp(prefix="guard150-")
    Path(site, "p.html").write_text("<!doctype html><meta charset=utf-8><body></body>")
    port = serve(site)
    url = f"http://127.0.0.1:{port}/p.html"

    for _ in range(15):
        preset = get_random_preset(os="windows")
        base = generate_context_fingerprint(preset=preset)
        fonts = sorted((set(base["config"].get("fonts", [])) | {"Arial"}) - set(CONTROL))
        fp_a = generate_context_fingerprint(preset=preset, config_overrides={"fonts": fonts})
        fp_b = generate_context_fingerprint(preset=preset, config_overrides={"fonts": fonts + CONTROL})
        try:
            async with AsyncCamoufox(fingerprint_preset=preset, os="windows", headless=True,
                                     fonts=fonts + CONTROL) as browser:
                ctx_b = await browser.new_context(**fp_b["context_options"])
                await ctx_b.add_init_script(fp_b["init_script"])
                page_b = await ctx_b.new_page()
                await page_b.goto(url)
                control = await page_b.evaluate(JS, [[], CONTROL, []])

                ctx_a = await browser.new_context(**fp_a["context_options"])
                await ctx_a.add_init_script(fp_a["init_script"])
                page_a = await ctx_a.new_page()
                await page_a.goto(url)
                result = await page_a.evaluate(JS, [[[f, s] for f, s, _ in ROWS], [],
                                                     [[f, s] for f, s, _ in CSS_ROWS]])
            break
        except ValueError as e:
            if "WebGL" in str(e):
                continue
            raise
    else:
        raise RuntimeError("Could not find a valid preset after 15 attempts")

    print(f"  control (context B, both families on its list): {control.get('control')}")
    if not control.get("valid") or not all(control["control"].values()):
        print("  FAIL: a control family does not render where it is allowed -- this guard "
              "measures nothing")
        return 1
    if not result.get("valid"):
        print("  FAIL: no two fallbacks differ on context A's page")
        return 1

    ok = True
    for fam, _src, must_render in ROWS + CSS_ROWS:
        r = result["rows"][fam]
        print(f"  {fam:16s} {r}")
        if must_render and not (r["rendered"] and r["status"] == "loaded"):
            print(f"  FAIL: {fam}: an allowed local() face must render and load (#150)")
            ok = False
        if not must_render and not (r["refused"] and r["status"] == "error"):
            print(f"  FAIL: {fam}: a local() face the list refuses must neither render nor load")
            ok = False
        if (r["status"] == "loaded") != r["rendered"]:
            print(f"  FAIL: {fam}: status {r['status']!r} disagrees with what renders (#150)")
            ok = False

    print("  PASS" if ok else "  FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
