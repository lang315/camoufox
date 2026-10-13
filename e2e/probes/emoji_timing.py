"""#165 probe: does U+1F603 change face during a context's first seconds?

    python3 e2e/probes/emoji_timing.py --binary BIN --os windows [--emoji-pref] [--mozlog DIR]

Prints one row per fresh context: measureText('😃') at 0, 0.3, 0.8, 1.5 and 3 s,
then the hexbox width (unassigned U+50000) it must not equal.
--emoji-pref sets font.name-list.emoji to the spoofed OS's emoji families.
--mozlog DIR captures MOZ_LOG=timestamp,fontlist:4 for the run.
"""

import argparse
import os
import time

from camoufox.sync_api import Camoufox

EMOJI = {"windows": "Segoe UI Emoji, Twemoji Mozilla", "macos": "Apple Color Emoji", "linux": "Twemoji Mozilla"}
AT = [0, 0.3, 0.8, 1.5, 3]
# U+50000 is unassigned, so no font has it: its width is the hexbox's, the
# reference that tells a missing emoji from a real face.
JS = "(cp) => { const x = document.createElement('canvas').getContext('2d'); x.font = '16px Arial'; return x.measureText(String.fromCodePoint(cp)).width; }"


def main() -> int:
    a = argparse.ArgumentParser()
    a.add_argument("--binary", required=True)
    a.add_argument("--os", required=True, choices=EMOJI)
    a.add_argument("--contexts", type=int, default=10)
    a.add_argument("--emoji-pref", action="store_true")
    a.add_argument("--mozlog")
    args = a.parse_args()
    env = dict(os.environ)
    if args.mozlog:
        os.makedirs(args.mozlog, exist_ok=True)
        env.update(MOZ_LOG="timestamp,fontlist:4", MOZ_LOG_FILE=os.path.join(args.mozlog, "moz"))
    prefs = {"font.name-list.emoji": EMOJI[args.os]} if args.emoji_pref else {}
    steady = 0
    with Camoufox(executable_path=args.binary, os=args.os, headless=True, env=env, firefox_user_prefs=prefs) as b:
        for i in range(args.contexts):
            page = b.new_context().new_page()
            page.goto("about:blank")
            t0, row = time.monotonic(), []
            for t in AT:
                time.sleep(max(0, t - (time.monotonic() - t0)))
                row.append(round(page.evaluate(JS, 0x1F603), 2))
            hexbox = round(page.evaluate(JS, 0x50000), 2)
            steady += len(set(row)) == 1 and hexbox not in row
            print(f"context {i}: {row} hexbox {hexbox}", flush=True)
            page.context.close()
    print(f"constant and not a hexbox in {steady}/{args.contexts} contexts (emoji pref {'on' if args.emoji_pref else 'off'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
