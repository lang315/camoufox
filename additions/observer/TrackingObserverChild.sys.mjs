// One drain timer per content process, not per window. The C++ access buffer is
// process-local; N same-process windows (a page + its same-origin iframes) each
// running a 500ms drain means N-1 redundant main-thread wakeups draining an
// already-empty buffer. Module scope is per process, so track live actors here
// and run a single timer through whichever actor owns it, handing off on
// teardown. Any actor's sendAsyncMessage reaches the parent, so the owner need
// not be a specific window.
let gActors = new Set();
let gOwner = null;
let gTimer = null;

function arm(actor) {
  gActors.add(actor);
  if (gOwner) return; // one timer already running in this process
  gOwner = actor;
  // Low-frequency drain keeps all IPC/serialize off the fingerprint read path.
  gTimer = actor.contentWindow.setInterval(() => {
    if (gOwner) gOwner._drain();
  }, 500);
}

function disarm(actor) {
  gActors.delete(actor);
  if (actor !== gOwner) return; // a non-owner left; timer keeps running
  // Owner's window is going away (its interval dies with it); reclaim + hand off.
  try {
    actor.contentWindow?.clearInterval(gTimer);
  } catch {}
  gTimer = null;
  gOwner = null;
  const next = gActors.values().next().value;
  if (next) arm(next); // give the single timer to another live window
}

export class TrackingObserverChild extends JSWindowActorChild {
  actorCreated() {
    arm(this);
  }
  didDestroy() {
    // contentWindow may already be torn down here; guard + swallow so a
    // teardown race never throws into the console (a page-observable tell).
    try {
      disarm(this);
    } catch {}
  }
  _drain() {
    // Swallow everything: a dead actor's sendAsyncMessage, a ChromeUtils hiccup,
    // or a parse error must not spam the console or break the interval.
    try {
      let json = ChromeUtils.camouDrainAccessRecords(); // "[]" when empty
      if (json === "[]") return;
      let records;
      try {
        records = JSON.parse(json);
      } catch {
        return;
      }
      if (records.length) {
        this.sendAsyncMessage("camoufox-observer:batch", { records });
      }
    } catch {}
  }
}
