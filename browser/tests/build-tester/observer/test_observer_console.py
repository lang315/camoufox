"""An armed observer logs nothing to the browser console, and a disarmed one has no actor.

The actor's `events` entry makes Firefox call `handleEvent` on it for each
DOMWindowCreated; a child without one logs "Property 'handleEvent' is not
callable" once per window.
"""
from pathlib import Path
import harness

HERE = Path(__file__).parent

CONSOLE_JS = "return Services.console.getMessageArray().map(m => m.message).filter(m => m.includes('handleEvent'));"
ACTOR_JS = """
  try {
    gBrowser.selectedBrowser.browsingContext.currentWindowGlobal.getActor('TrackingObserver');
    return 'registered';
  } catch (e) { return String(e); }
"""


def run(arm):
    with harness.serve(HERE) as port, harness.Session(arm=arm) as s:
        s.navigate(f"http://127.0.0.1:{port}/probe_all_surfaces.html")
        s.wait_done(30)
        with s.m.using_context("chrome"):
            return s.m.execute_script(CONSOLE_JS), s.m.execute_script(ACTOR_JS)


def main():
    errors, actor = run(arm=True)
    print("armed: actor =", actor, "| handleEvent console messages:", errors)
    assert actor == "registered", f"armed: the actor is not registered: {actor}"
    assert not errors, f"armed: the console logged {len(errors)} handleEvent error(s): {errors[:2]}"
    print("PASS: armed observer logs no handleEvent error")

    errors, actor = run(arm=False)
    print("disarmed: actor =", actor)
    assert actor != "registered", "disarmed: the actor is registered"
    assert not errors, f"disarmed: console messages: {errors[:2]}"
    print("PASS: disarmed observer registers no actor")


main()
