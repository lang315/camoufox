"""
Driven presses count clicks as the claimed OS does.

The OS, not the page, decides a press's click count (`detail`): a press in
place soon after the last one counts up. People's recordings on stock 159.0
(private, a mouse and a touchpad on each OS) follow these rules, checked
against every recorded press:
- Windows: Firefox counts a press within 500 ms of the last one, unless the
  pointer moved 4 device pixels from the last release; Windows itself reports
  a press within 1 device pixel of the last single press as a double click,
  which sets the count to 2. Fifteen quick presses in place count
  1, 2, 3, 2, 3, ...
- macOS: a press within 500 ms and 3 points of the last one counts up, without
  bound.
- GTK counts 1, 2, 3 and starts again, within its default 400 ms and 5 pixels.
A driven press always reported the clickCount the client sent: 1 for every
page.click(), however quick and wherever.

The guard presses in place under each identity, then presses after a pause
and after a move. It checks every count against the rule above, applied to
when the page saw each press (its `timeStamp`), not when the guard meant to
press. The browser stalls once soon after launch (#519): a press that comes
after it really is late, and the OS counts it so. The guard fails when no
press came soon enough after the last to count up, because then no count
could tell a driven press from one that always reports 1.

    python browser/tests/playwright/patches/driven-click-count.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import drawable, hidden_display, resolve_binary  # noqa: E402

PAGE = """<!doctype html><html><body style="margin:0;width:800px;height:600px"><script>
  const seen = [];
  for (const type of ['mousedown', 'mouseup', 'click'])
    addEventListener(type, (e) => {
      seen.push([type, e.detail, e.timeStamp]);
      document.body.dataset.seen = JSON.stringify(seen);
    }, true);
</script></body></html>"""
PRESSES = 8
CLICK_MS = {"windows": 500, "macos": 500, "linux": 400}


def os_counts(os_name, stamps):
    """The count the OS gives each press, from when the page saw it. Every
    press is in place but the last, which moved 60 px."""
    counts, single = [], False
    for i, at in enumerate(stamps):
        soon = 0 < i < len(stamps) - 1 and at - stamps[i - 1] < CLICK_MS[os_name]
        count = counts[-1] if counts else 0
        if os_name == "windows":
            count, single = (2, False) if soon and single else (count + 1 if soon else 1, True)
        elif os_name == "macos":
            count = count + 1 if soon else 1
        else:
            count = count + 1 if soon and count < 3 else 1
        counts.append(count)
    return counts


assert os_counts("windows", [0, 100, 200, 300, 400, 500, 600, 700, 1500, 1600]) == [1, 2, 3, 2, 3, 2, 3, 2, 1, 1]
assert os_counts("macos", [0, 100, 200, 300, 400, 500, 600, 700, 1500, 1600]) == [1, 2, 3, 4, 5, 6, 7, 8, 1, 1]
assert os_counts("linux", [0, 100, 200, 300, 400, 500, 600, 700, 1500, 1600]) == [1, 2, 3, 1, 2, 3, 1, 2, 1, 1]
assert os_counts("linux", [0, 100, 200, 300, 400, 900, 1000, 1100, 1900, 2000]) == [1, 2, 3, 1, 2, 1, 2, 3, 1, 1]


def probe(binary, os_name):
    from camoufox.sync_api import Camoufox

    with Camoufox(executable_path=str(binary), headless=False, os=os_name, i_know_what_im_doing=True) as browser:
        page = browser.new_page()
        page.set_content(PAGE)
        page.mouse.move(200, 200)
        for _ in range(PRESSES):
            page.mouse.click(200, 200)
            page.wait_for_timeout(60)
        page.wait_for_timeout(700)
        page.mouse.click(200, 200)
        page.mouse.move(260, 200)
        page.mouse.click(260, 200)
        page.wait_for_timeout(100)
        return page.evaluate("() => JSON.parse(document.body.dataset.seen || '[]')")


def main() -> int:
    failures = []
    with hidden_display("1920x1080"):
        seen = {os_name: probe(resolve_binary(), os_name) for os_name in drawable(CLICK_MS)}
    for os_name in seen:
        stamps = [at for t, _, at in seen[os_name] if t == "mousedown"]
        gaps = [round(b - a) for a, b in zip(stamps, stamps[1:])]
        expected = os_counts(os_name, stamps)
        if max(expected[:PRESSES], default=0) < 2:
            failures.append(f"{os_name}: no press came within {CLICK_MS[os_name]} ms of the last, so none could count up; gaps {gaps} ms")
        downs = [d for t, d, _ in seen[os_name] if t == "mousedown"]
        if downs != expected:
            failures.append(f"{os_name}: presses counted {downs}, the OS's count {expected} for presses {gaps} ms apart")
        for kind in ("mouseup", "click"):
            got = [d for t, d, _ in seen[os_name] if t == kind]
            if got != expected:
                failures.append(f"{os_name}: {kind} detail {got}, its press counted {expected}")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: driven presses count clicks as each OS does")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
