"""
A driven key held down repeats as the claimed OS repeats it.

The OS repeats the last key pressed while it is held. People's recordings on
stock 159.0 (private) and the defaults:
- Windows repeats after 500 ms, then every 31.25 ms (two ticks), and repeats
  Shift too: a person's Shift held a second sends about twenty repeat keydowns.
- macOS repeats after 500 ms, then every 83.3 ms, and never repeats a modifier.
- GNOME repeats after 500 ms, then every 30 ms (its schema defaults), and the
  XKB keymap does not repeat a modifier.
Pressing another key moves the repeat to that key. A driven key held down
sent one keydown however long it was held.

A key pressed and released at once never repeats, however long the page takes
to handle its keydown: the OS counts the delay from the press, and the release
comes before it. Juggler counted it from the command, so a keydown handler busy
for 700 ms got a repeat before the client could send the keyup (#510).

A key held on such a page repeats when the OS would have made the repeat: the
OS stamps it 500 ms after the press while the page is still busy, and the page
reads it once it is free. Juggler's timer can only fire after the keydown
returns, so each repeat it makes is stamped from its key's keydown, not from
the timer (#510).

The guard holds a letter, then Shift, then a letter and another over it, then
presses a letter whose keydown keeps the page busy and holds another, under
each identity, and checks the repeat keydowns, their delay and interval, and
the text the repeats type.

    python browser/tests/playwright/patches/driven-key-repeat.py
"""

import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import hidden_display, resolve_binary  # noqa: E402

PAGE = """<!doctype html><html><body><input id="field"><script>
  const seen = [];
  for (const type of ['keydown', 'keyup'])
    addEventListener(type, (e) => {
      seen.push([type, e.key, e.repeat, e.timeStamp]);
      document.body.dataset.seen = JSON.stringify(seen);
      if (type === 'keydown' && !e.repeat && 'de'.includes(e.key))
        for (const end = performance.now() + 700; performance.now() < end;);
    }, true);
</script></body></html>"""
# Delay and interval in ms, and whether a modifier repeats.
REPEAT = {"windows": (500, 31.25, True), "macos": (500, 1000 / 12, False), "linux": (500, 30, False)}
HOLD = 1100


def probe(binary, os_name):
    from camoufox.sync_api import Camoufox

    prefs = {"privacy.reduceTimerPrecision": False}
    with Camoufox(executable_path=str(binary), headless=False, os=os_name, firefox_user_prefs=prefs,
                  i_know_what_im_doing=True) as browser:
        page = browser.new_page()
        page.set_content(PAGE)
        page.click("#field")
        page.keyboard.down("a")
        page.wait_for_timeout(HOLD)
        page.keyboard.up("a")
        page.keyboard.down("Shift")
        page.wait_for_timeout(HOLD)
        page.keyboard.up("Shift")
        page.keyboard.down("b")
        page.wait_for_timeout(700)
        page.keyboard.down("c")
        page.wait_for_timeout(700)
        page.keyboard.up("b")
        page.keyboard.up("c")
        page.keyboard.press("d")
        page.wait_for_timeout(100)
        page.keyboard.down("e")
        page.wait_for_timeout(HOLD)
        page.keyboard.up("e")
        return page.evaluate("() => JSON.parse(document.body.dataset.seen || '[]')"), page.input_value("#field")


def held(seen, key):
    downs = [t for type, k, _, t in seen if type == "keydown" and k == key]
    return downs[0], downs[1:]


def main() -> int:
    failures = []
    with hidden_display("1920x1080"):
        runs = {os_name: probe(resolve_binary(), os_name) for os_name in REPEAT}
    for os_name, (delay, interval, modifiers) in REPEAT.items():
        seen, value = runs[os_name]
        flagged = [k for type, k, repeat, _ in seen if type == "keydown" and repeat]
        first, repeats = held(seen, "a")
        e_down, e_repeats = held(seen, "e")
        e_first = e_repeats[0] - e_down if e_repeats else float("nan")
        expected = int((HOLD - delay) / interval)
        print(f"{os_name}: 'a' first repeat after "
              f"{repeats[0] - first if repeats else float('nan'):.1f} ms, {len(repeats)} repeats; "
              f"'d' {1 + len(held(seen, 'd')[1])} keydowns; 'e' on a busy page first repeat after {e_first:.1f} ms")
        if not expected - 3 <= len(repeats) <= expected + 1:
            failures.append(f"{os_name}: 'a' held {HOLD} ms repeated {len(repeats)} times, the OS {expected}")
        else:
            # The Windows tick puts each stamp on a 15.625 ms step.
            if abs(repeats[0] - first - delay) > 17:
                failures.append(f"{os_name}: first repeat after {repeats[0] - first:.0f} ms, the OS's {delay}")
            gaps = statistics.median(b - a for a, b in zip(repeats, repeats[1:]))
            if abs(gaps - interval) > 2:
                failures.append(f"{os_name}: repeats every {gaps:.1f} ms, the OS every {interval:.1f}")
        shift = len(held(seen, "Shift")[1])
        if bool(shift) != modifiers:
            failures.append(f"{os_name}: Shift held {HOLD} ms repeated {shift} times; "
                            f"{'it repeats' if modifiers else 'a modifier does not repeat'} there")
        b_down, b_repeats = held(seen, "b")
        c_down = held(seen, "c")[0]
        if not b_repeats or any(t > c_down for t in b_repeats) or not held(seen, "c")[1]:
            failures.append(f"{os_name}: the repeat did not move from 'b' to 'c' when 'c' was pressed")
        if held(seen, "d")[1]:
            failures.append(f"{os_name}: 'd', pressed once on a page busy 700 ms in its keydown, "
                            f"sent {1 + len(held(seen, 'd')[1])} keydowns")
        if not abs(e_first - delay) <= 17:
            failures.append(f"{os_name}: 'e', held on a page busy 700 ms in its keydown, first repeated "
                            f"{e_first:.0f} ms after its keydown, the OS {delay}")
        if any(k not in "abcShiftde" for k in flagged):
            failures.append(f"{os_name}: repeats of keys not held: {set(flagged)}")
        typed = "a" * (1 + len(repeats)) + "b" * (1 + len(b_repeats)) + "c" * len(held(seen, "c")[1] + [c_down]) + "d" + "e" * (1 + len(e_repeats))
        if value != typed:
            failures.append(f"{os_name}: the field holds {value!r}, the repeats typed {typed!r}")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: a held key repeats as each OS repeats it")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
