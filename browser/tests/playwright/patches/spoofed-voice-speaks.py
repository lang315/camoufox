"""
Verify speechSynthesis.speak() on a spoofed voice behaves like a real voice.

A spoofed voice has no speech engine behind it. voice-spoofing.patch used to fire
an `error` event for it unless `voices:fakeCompletion` was set, and even then it
fired `start` and `end` in the same instant. A real voice never errors on a plain
utterance, and its `end` arrives after the text has been spoken. Both were tells.

The host's own speech backend must not matter either. On a Linux host where
speech-dispatcher cannot start, Firefox broadcasts a voices error, and every
page used to error its queued utterances. A spoofed Windows identity's voices
do not depend on the host's daemon, so the guard runs with it unreachable.

What PASS means:
    * the page sees spoofed voices at all (so the check is not vacuous);
    * speaking 25 characters on one fires `start`, then `end`, and no `error`;
    * `end` comes no sooner than the text takes to say at ~150 words per minute
      (2s here), less 500ms: the old tell was `end` in the same tick as `start`;
    * `end`'s `elapsedTime` is the time the page saw pass between `start` and
      `end`, as a real voice's is (#494).

There is no upper bound on when `end` comes. The parent's main thread runs the
2s timer (a delayed runnable in nsSynthVoiceRegistry::SpeakImpl), so a busy
runner delays `end`. Stock Firefox's `end` is delayed the same way: every
engine's `end` reaches the page through SpeechTaskParent::DispatchEndImpl's
SendOnEnd, an actor under PContent, on the parent's main thread. A ceiling
measured the runner, not the browser (#370). What a stall must not do is leave
`elapsedTime` at the nominal 2s while the page saw 4s: stock's (SAPI's) is the
time since the utterance started, taken when `end` is dispatched.

`elapsedTime` is read in the parent and the page's span in the page, so the two
differ by how much longer `end` took than `start` to reach the page's listener.
Each hop waits on the page's event loop, which the probe watches (`lag`), and
on IPC transit, which the page cannot see. The check allows the page's lag,
plus HOPS_MS, twice the largest difference measured between the page's span
and the parent's own interval:
    * Windows, build 44055836267 (main b074a8ce), e2e run 44084344153, job
      134043585700: 59 utterances, -3 to +1ms, except the first after each
      launch, +13 to +25ms;
    * the same build, e2e run 44089875316, job 134062178121: 24 utterances,
      with and without uBlock Origin, -1 to +1ms, except the first after each
      launch, +21 to +49ms;
    * macOS arm64, fork.3, local: 60 utterances, -1.1 to +1.7ms.
The parent's interval there was read from MOZ_LOG
(SpeechSynthesis:5,timestamp,sync): SpeakImpl's log line, which comes just
before the stamp this patch takes ahead of Init and DispatchStart, and
SpeakNext's, which DispatchEnd logs just after the runnable reads the time.
Each pair is the same task on the parent's main thread with no wait between
them, so the gap is assumed small next to the hops.

The same Windows run measured how late the parent's timer runs: 0-3ms, except
on the first utterance after each launch, 56ms to 14.5s late (a 16.5s interval
at most, against the timer's 2s). The probe waits WAIT_MS for `end`, twice that
16.5s, and a wait that expires is its own failure, not the elapsedTime check's.

    python browser/tests/playwright/patches/spoofed-voice-speaks.py
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

TEXT = "a" * 25  # 25 chars at 12.5 chars/s = 2.0s
NOMINAL_MS = 2000
FLOOR_MS = NOMINAL_MS - 500
HOPS_MS = 100
WAIT_MS = 33000
PROBE = """async ([text, wait]) => {
  const p0 = performance.now();
  let voices = speechSynthesis.getVoices();
  if (!voices.length) {
    await new Promise(r => { speechSynthesis.onvoiceschanged = r; setTimeout(r, 3000); });
    voices = speechSynthesis.getVoices();
  }
  const loaded = Math.round(performance.now() - p0);
  if (!voices.length) return {voices: 0};
  const u = new SpeechSynthesisUtterance(text);
  u.voice = voices[0];
  const events = [];
  let last = performance.now(), lag = 0;
  const beat = setInterval(() => {
    const now = performance.now();
    lag = Math.max(lag, Math.round(now - last - 50));
    last = now;
  }, 50);
  const t0 = performance.now();
  const done = new Promise(resolve => {
    for (const type of ['start', 'end', 'error']) {
      u.addEventListener(type, e => {
        events.push([type, Math.round(performance.now() - t0), e.elapsedTime]);
        if (type !== 'start') resolve();
      });
    }
    setTimeout(resolve, wait);
  });
  speechSynthesis.speak(u);
  const speakCall = Math.round(performance.now() - t0);
  await done;
  clearInterval(beat);
  return {voices: voices.length, loaded, speakCall, lag, events};
}"""


async def main() -> int:
    from camoufox.async_api import AsyncCamoufox

    # An unreachable speech-dispatcher socket: the host backend fails to start,
    # as it does on a machine without the daemon.
    env = {**os.environ, "SPEECHD_ADDRESS": "unix_socket:/nonexistent/speechd.sock"}
    async with AsyncCamoufox(headless=True, os="windows", env=env,
                             executable_path=str(resolve_binary())) as browser:
        page = await browser.new_page()
        await page.goto("about:blank")
        got = await page.evaluate(PROBE, [TEXT, WAIT_MS])
    print(f"  {got}")

    if not got["voices"]:
        print("  FAIL: the page sees no voices, so nothing was tested")
        return 1
    phases = (f"voices loaded in {got['loaded']}ms, speak() took {got['speakCall']}ms, "
              f"the page's event loop lagged up to {got['lag']}ms")
    kinds = [kind for kind, *_ in got["events"]]
    if kinds == ["start"]:
        print(f"  FAIL: no end within {WAIT_MS // 1000}s of start ({phases})")
        return 1
    if kinds != ["start", "end"]:
        print(f"  FAIL: expected start then end, got {kinds}")
        return 1
    spoken = got["events"][1][1] - got["events"][0][1]
    # Firefox's elapsedTime is in seconds (SapiService's ToSeconds()).
    reported = round(got["events"][1][2] * 1000)
    if spoken < FLOOR_MS:
        print(f"  FAIL: end came {spoken}ms after start, sooner than the text takes "
              f"to say ({NOMINAL_MS}ms) ({phases})")
        return 1
    if abs(spoken - reported) > got["lag"] + HOPS_MS:
        print(f"  FAIL: end's elapsedTime is {reported}ms, but the page saw {spoken}ms "
              f"pass between start and end ({phases})")
        return 1
    print(f"  PASS: start, then end {spoken}ms later with elapsedTime {reported}ms, no error")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
