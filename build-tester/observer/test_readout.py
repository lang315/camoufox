import os, sys
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import harness

CANVAS_POKE = """
const c = document.createElement('canvas'); c.width=200; c.height=50;
const x = c.getContext('2d'); x.textBaseline='top'; x.font='14px Arial';
x.fillText('camoufox-observer-probe', 2, 2);
c.toDataURL();
window.__done__ = true; return true;
"""

def main():
    port, stop = harness.serve(HERE)
    try:
        with harness.Session(camou_config={"canvas:seed": 424242}) as s:
            s.navigate(f"http://127.0.0.1:{port}/")   # real origin, not about:blank
            s.eval_content(CANVAS_POKE)
            snap = s.snapshot()
    finally:
        stop()
    assert any("canvas" in row["surfaces"] for row in snap), f"no canvas record: {snap}"
    print("PASS: canvas recorded ->", snap)

main()
