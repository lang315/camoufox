"""Journey 10: bundled fonts draw the same glyphs in the real window, with or without the GPU process (#356).

On a Mac, WebRender rasterizes in the GPU process. Content hands it a font as
a PostScript name plus a file path, and that process has no font list, so it
never registered the bundle with CoreText: the lookup falls to another font
and the bundled font's glyph ids are drawn with those outlines. Every capture
that does not go through WebRender (Page.screenshot, the screencast,
Marionette) paints the same page correctly, so only the window shows it.

The reference is the same page, in the same identity, in a second launch with
the GPU process off (`layers.gpu-process.enabled`), where WebRender runs in
the parent, which did register the bundle. The two crops of the window must be
equal in every pixel. A reference that only had to look similar would pass a window that
drew the wrong font everywhere, so the test also requires the crop to differ
from a blank page's crop (else VACUOUS).

What this cannot see: a Windows or Linux host (WebRender gets a file path
there), canvas text (readback of a non-host identity is randomized), and
anything the window capture does not include.
"""

import json
import platform
import subprocess
import time

import pytest

TEXT = "Cầu công an nhận 100.000 USD “chạy” CHƠI ầậểạộ"
FAMILIES = ["Segoe UI", "Arial", "Verdana", "Times New Roman", "system-ui"]
PAGE = (
    "document.body.style.cssText='margin:8px;background:#fff;color:#000';"
    "document.body.innerHTML=''; for (const f of %s) { const d = document.createElement('div');"
    "d.style.cssText = 'font:18px ' + (/\\s/.test(f) && f !== 'system-ui' ? '\"' + f + '\"' : f) + ';height:30px;white-space:nowrap';"
    "d.textContent = %s; document.body.appendChild(d); }"
    "[window.mozInnerScreenX, window.mozInnerScreenY, window.devicePixelRatio]"
) % (json.dumps(FAMILIES), json.dumps(TEXT))

WINDOWS_JXA = """
ObjC.import('CoreGraphics');
const l = ObjC.deepUnwrap(ObjC.castRefToObject($.CGWindowListCopyWindowInfo(0, 0)));
console.log(JSON.stringify(l.filter(w => w.kCGWindowLayer === 0)
  .map(w => [w.kCGWindowOwnerName, w.kCGWindowNumber, w.kCGWindowBounds.X, w.kCGWindowBounds.Y, w.kCGWindowBounds.Width, w.kCGWindowBounds.Height])));
"""


# The crop must fit in the narrowest window an identity draws.
CROP_W, CROP_H = 500, 5 * 30 + 8


def window_crop(tmp_path, name, inner):
    """The page's top-left corner as the window shows it: the raw pixels of a crop of the window capture."""
    deadline = time.time() + 30
    windows, owners = [], []
    while not windows and time.time() < deadline:
        out = subprocess.run(["osascript", "-l", "JavaScript", "-e", WINDOWS_JXA], capture_output=True, text=True, check=True)
        owners = json.loads(out.stderr.strip() or "[]")  # osascript prints console.log to stderr
        windows = sorted((w[1:] for w in owners if "camoufox" in w[0].lower()), key=lambda w: -w[3] * w[4])
        time.sleep(0.5)
    assert windows, f"no Camoufox window to capture; windows on screen: {sorted({w[0] for w in owners})}"
    wid, wx, wy = windows[0][:3]
    shot = tmp_path / f"{name}.png"
    subprocess.run(["screencapture", "-x", "-o", "-l", str(wid), str(shot)], check=True)
    inner_x, inner_y, dpr = inner
    crop = tmp_path / f"{name}-crop.bmp"
    left, top = round((inner_x - wx) * dpr), round((inner_y - wy) * dpr)
    # sips: --cropOffset <y> <x>, then the size to keep. BMP is raw pixels: two PNGs of equal pixels can differ in bytes.
    subprocess.run(["sips", "-s", "format", "bmp", "--cropOffset", str(top), str(left), "-c", str(round(CROP_H * dpr)), str(round(CROP_W * dpr)),
                    str(shot), "--out", str(crop)], check=True, capture_output=True)
    return crop.read_bytes()


def one_launch(drv, tmp_path, name, prefs):
    """The crop of the window with no text, then with the rows, from one launch."""
    b = drv.launch(os="windows", headless=False, prefs=prefs)
    page = b.new_context().new_page()
    inner = page.eval(PAGE.replace("d.textContent = " + json.dumps(TEXT), "d.textContent = ''"))
    time.sleep(2)
    blank = window_crop(tmp_path, f"{name}-blank", inner)
    page.eval(PAGE)
    time.sleep(2)
    rows = window_crop(tmp_path, name, inner)
    b.close()
    return blank, rows


def test_bundled_fonts_draw_the_same_in_the_window_with_or_without_the_gpu_process(drv, check, tmp_path):
    """A Windows identity on a Mac draws the Segoe UI and Arial rows the same whether WebRender runs in the GPU process or in the parent (#356)."""
    if platform.system() != "Darwin":
        pytest.skip("WebRender gets a file path for a font on Windows and Linux hosts, so only a Mac can show this")
    if drv.name == "go":
        pytest.skip("goapi applies prefs after the browser starts, and layers.gpu-process.enabled is read at startup")
    blank, default = one_launch(drv, tmp_path, "default", None)
    _, parent = one_launch(drv, tmp_path, "gpu-off", {"layers.gpu-process.enabled": False})
    check(default != blank and parent != blank, "the rows are visible in the crop: it differs from the same window with no text (else VACUOUS)", ledger=False)
    check(default == parent,
          f"the window draws the same with the GPU process on and off: {len(default)} bytes against {len(parent)} (#356)")
    check.done()
