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

A page busy after a keydown returns reads every repeat the OS made while it
was busy, then the release. Juggler made each repeat only once the page had
read the one before, and a release dropped the rest, so a page busy past the
release read one (#518).

The guard holds a letter, then Shift, then a letter and another over it, then
presses a letter whose keydown keeps the page busy and holds another, under
each identity, and checks the repeat keydowns, their delay and interval, and
the text the repeats type. A last letter's keydown queues 1.5 s of work, so
the page is busy for the whole hold.

Juggler counts a hold from the keydown's return to the keyup's arrival: the
client's hold plus a hop each way. On a hosted Windows runner the Linux
identity's `f` read 21 repeats in eight launches and 22 in one, where 20 fit
1100 ms (#518). So the most repeats a hold may read are those of the time from
sending the press to sending the release, which carries the press's round trip.

The parent's main thread stalls once soon after a fresh profile loads its first
page, 1.7 to 2.3 s on a hosted Windows runner, as stock Firefox does (#518,
#519). A key held through it reads one repeat: Juggler's repeat timer cannot
fire, and the release comes next. The guard holds its keys once the parent's
round trips have stayed quick for 2 s, and measures the repeats, not the runner.

    python browser/tests/playwright/patches/driven-key-repeat.py
"""

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import drawable, hidden_display, resolve_binary  # noqa: E402

PAGE = """<!doctype html><html><body><input id="field"><script>
  const seen = [];
  for (const type of ['keydown', 'keyup'])
    addEventListener(type, (e) => {
      seen.push([type, e.key, e.repeat, e.timeStamp]);
      document.body.dataset.seen = JSON.stringify(seen);
      if (type === 'keydown' && !e.repeat && 'de'.includes(e.key))
        for (const end = performance.now() + 700; performance.now() < end;);
      if (type === 'keydown' && !e.repeat && e.key === 'f')
        setTimeout(() => { for (const end = performance.now() + 1500; performance.now() < end;); });
    }, true);
</script></body></html>"""
# Delay and interval in ms, and whether a modifier repeats.
REPEAT = {"windows": (500, 31.25, True), "macos": (500, 1000 / 12, False), "linux": (500, 30, False)}
HOLD = 1100


def hold(page, key, ms):
    """Hold `key` `ms`; returns the time from sending the press to sending the release."""
    sent = time.perf_counter()
    page.keyboard.down(key)
    page.wait_for_timeout(ms)
    span = (time.perf_counter() - sent) * 1000
    page.keyboard.up(key)
    return span


def settle(page):
    """Wait out the parent's startup stall: until its round trips stay under 100 ms for 2 s."""
    start = quiet = time.perf_counter()
    while time.perf_counter() - quiet < 2:
        sent = time.perf_counter()
        page.context.cookies()
        if time.perf_counter() - sent > 0.1:
            quiet = time.perf_counter()
        if time.perf_counter() - start > 20:
            raise SystemExit("the parent did not stay responsive for 2 s within 20 s")


def probe(binary, os_name):
    from camoufox.sync_api import Camoufox

    prefs = {"privacy.reduceTimerPrecision": False}
    with Camoufox(executable_path=str(binary), headless=False, os=os_name, firefox_user_prefs=prefs,
                  i_know_what_im_doing=True) as browser:
        page = browser.new_page()
        page.set_content(PAGE)
        page.click("#field")
        settle(page)
        spans = {"a": hold(page, "a", HOLD)}
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
        spans["f"] = hold(page, "f", HOLD)
        return page.evaluate("() => JSON.parse(document.body.dataset.seen || '[]')"), page.input_value("#field"), spans


def held(seen, key):
    downs = [t for type, k, _, t in seen if type == "keydown" and k == key]
    return downs[0], downs[1:]


def main() -> int:
    failures = []
    with hidden_display("1920x1080"):
        runs = {os_name: probe(resolve_binary(), os_name) for os_name in drawable(REPEAT)}
    for os_name in runs:
        delay, interval, modifiers = REPEAT[os_name]
        seen, value, spans = runs[os_name]
        # The repeats a hold of each span makes, the one at its very end included.
        most = {k: int((span - delay) / interval) + 1 for k, span in spans.items()}
        flagged = [k for type, k, repeat, _ in seen if type == "keydown" and repeat]
        first, repeats = held(seen, "a")
        e_down, e_repeats = held(seen, "e")
        e_first = e_repeats[0] - e_down if e_repeats else float("nan")
        expected = int((HOLD - delay) / interval)
        print(f"{os_name}: 'a' first repeat after "
              f"{repeats[0] - first if repeats else float('nan'):.1f} ms, {len(repeats)} repeats; "
              f"'d' {1 + len(held(seen, 'd')[1])} keydowns; 'e' on a busy page first repeat after {e_first:.1f} ms")
        if not expected - 3 <= len(repeats) <= most["a"]:
            failures.append(f"{os_name}: 'a' held {HOLD} ms repeated {len(repeats)} times, the OS {expected} "
                            f"to {most['a']} over {spans['a']:.0f} ms")
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
        f_repeats = held(seen, "f")[1]
        if not expected - 3 <= len(f_repeats) <= most["f"]:
            failures.append(f"{os_name}: 'f', held {HOLD} ms on a page busy after its keydown, "
                            f"repeated {len(f_repeats)} times, the OS {expected} to {most['f']} over {spans['f']:.0f} ms")
        if any(k not in "abcShiftdef" for k in flagged):
            failures.append(f"{os_name}: repeats of keys not held: {set(flagged)}")
        typed = "a" * (1 + len(repeats)) + "b" * (1 + len(b_repeats)) + "c" * len(held(seen, "c")[1] + [c_down]) + "d" + "e" * (1 + len(e_repeats)) + "f" * (1 + len(f_repeats))
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
