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
    * `end` arrives about as long after `start` as the text takes to say at
      ~150 words per minute (2s here), not in the same tick.

`end` is scheduled by the browser's main thread (a delayed runnable in
nsSynthVoiceRegistry::SpeakImpl) and reaches the page over IPC, so a late `end`
can be a stalled parent, a stalled page, or a slow hop between them. The printed
phases tell which: how long the voices took, how long speak() blocked, and how
far the page's own event loop lagged while the utterance ran.

    python browser/tests/playwright/patches/spoofed-voice-speaks.py
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

TEXT = "a" * 25  # 25 chars at 12.5 chars/s = 2.0s
PROBE = """async (text) => {
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
      u.addEventListener(type, () => {
        events.push([type, Math.round(performance.now() - t0)]);
        if (type !== 'start') resolve();
      });
    }
    setTimeout(resolve, 10000);
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
        got = await page.evaluate(PROBE, TEXT)
    print(f"  {got}")

    if not got["voices"]:
        print("  FAIL: the page sees no voices, so nothing was tested")
        return 1
    kinds = [kind for kind, _ in got["events"]]
    if kinds != ["start", "end"]:
        print(f"  FAIL: expected start then end, got {kinds}")
        return 1
    spoken = got["events"][1][1] - got["events"][0][1]
    if not 1500 <= spoken <= 4000:
        print(f"  FAIL: end came {spoken}ms after start, expected about 2000ms "
              f"(voices loaded in {got['loaded']}ms, speak() took {got['speakCall']}ms, "
              f"the page's event loop lagged up to {got['lag']}ms)")
        return 1
    print(f"  PASS: start, then end {spoken}ms later, no error")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
