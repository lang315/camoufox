# Fix plan — integration-testing findings (2026-07-01)

Three findings from the full integration run (`plan/integration-testing.md`). One cheap+done,
two need an FF150 source fetch + full browser rebuild to verify.

## Finding 1 — CI never runs full suite vs real binary  ✅ DONE (Phase 1)

`goapi.yml` runs `go test ./...` with **no** `CAMOUFOX_BIN` → all 25 browser tests `t.Skip`.
`smoke.yml` set `CAMOUFOX_BIN` but ran only `-run TestRuntimeSpoofs`. So 24 feature tests never
touched a real build in CI.

**Fix:** `smoke.yml` step now runs `go test -timeout 15m -v ./...` (full suite) against the
downloaded artifact instead of the spoof subset.
**Evidence:** identical command run locally vs the real mac arm64 binary → 38 PASS / 0 FAIL /
3 SKIP, 204s (see integration-testing.md run log). Verify-in-CT: next `smoke` dispatch.

## Finding 2 — file-chooser interception hook is misplaced

`TestOnFileChooser` skips: `Page.fileChooserOpened` never fires for `<input type=file>`.

Root cause (not a missing feature — a misplaced hunk). All machinery is wired:
- juggler: `Protocol.js` `fileChooserOpened`, `PageAgent.js` `_filePickerShown` observer on
  `juggler-file-picker-shown`, `PageHandler.js` `pageFileChooserOpened` emit.
- C++: `docShell->IsFileInputInterceptionEnabled()` + `docShell->FilePickerShown(this)`.

But in `patches/playwright/0-playwright.patch` the interception block was inserted into
`HTMLInputElement::InitColorPicker()` (the `<input type=color>` path). `<input type=file>`
calls `InitFilePicker()`, which is unpatched → observer never notified.

**Attempted fix (necessary but INSUFFICIENT — reverted):** added the same guard block to
`HTMLInputElement::InitFilePicker()`:
```cpp
nsCOMPtr<nsPIDOMWindowOuter> win = doc->GetWindow();
nsDocShell* docShell = win ? static_cast<nsDocShell*>(win->GetDocShell()) : nullptr;
if (docShell && docShell->IsFileInputInterceptionEnabled()) {
  docShell->FilePickerShown(this);
  return NS_OK;
}
```
Built cleanly (hunk applied to real 150.0.2, offset -102) and the interception path IS reached:
`FilePickerShown` fires. **But `TestOnFileChooser` still fails**, and the failure exposes a
deeper blocker:

- Clicking `<input type=file>` opens the picker synchronously *inside* the `mouseup` dispatch.
  With interception this hits a Gecko nested event loop, so the `mouseup` RPC never returns.
- `Page.fileChooserOpened` and the handler's `SetFiles` only flush at teardown (context cancel),
  not during the click — the event is effectively serialized behind the blocked `mouseup`.
- Symptoms across two CI smoke runs (build 28529782482): `dispatchMouseEvent mouseup: context
  deadline exceeded` and `SetFiles: ... write |1: file already closed` (browser torn down first).
  Firing the click in a goroutine did not help — the browser doesn't emit the event until
  `mouseup` unblocks.

So the misplaced hook was real, but relocating it is not enough: the juggler file-picker flow
needs to return the click immediately (as upstream Playwright does) instead of nesting an event
loop. That is deeper patch work + more rebuild cycles for a parity feature that `SetInputFiles`
(direct upload, `TestSetInputFilesDirect` PASS) already covers.

**Decision:** reverted the InitFilePicker patch (keeping it would ship a latent click-deadlock
for anyone enabling `OnFileChooser`), left `TestOnFileChooser` skipped with the accurate reason.
Reopen only if a consumer needs the file-chooser *event* API.

## Finding 3 — synthetic touch injection unavailable

`TestTouchscreenTap` / `TestTouchscreenTouchEvents` skip: `windowUtils.sendTouchEvent is not a
function`. The test already enables touch (`dom.w3c_touch_events.enabled=1` +
`SetTouchOverride(true)`), so this is not persona/pref gating — the stock
`nsIDOMWindowUtils::sendTouchEvent` juggler relies on (`PageAgent.js:_dispatchTouchEvent`) is
absent in FF150. Mouse injection works only because the Playwright patch adds a *custom*
`jugglerSendMouseEvent`; touch has no equivalent.

**Fix options:**
- (a) Add a patched `jugglerSendTouchEvent` to `nsIDOMWindowUtils.idl` + `nsDOMWindowUtils.cpp`
  (mirror `jugglerSendMouseEvent`), point `PageAgent._dispatchTouchEvent` at it. Needs FF150
  source to find the current touch-injection entry point.
- (b) Keep documented skip. Touch *fingerprint* (`maxTouchPoints`, `ontouchstart`, `TouchEvent`)
  is already correct; synthetic touch *injection* is a mobile-emulation driver-parity feature,
  not a fingerprint leak. Lowest value of the three.

**Recommendation:** (b) unless a consumer (donutbrowser) needs mobile touch automation.

## Cost / sequencing

| Phase | Work | Verify | Outcome |
|---|---|---|---|
| 1 | smoke.yml full suite | local run + CI smoke ✅ | SHIPPED |
| 2 | filechooser hook → InitFilePicker | CI build + smoke | REVERTED — hook reached but picker click deadlocks (Gecko nested loop); needs juggler flow work |
| 3 | jugglerSendTouchEvent patch | FF150 source + rebuild | DEFERRED — low value; touch fingerprint already correct |

Only Phase 1 shipped. Phases 2/3 both bottom out in FF-source patch work with rebuild cycles for
parity features already covered by existing APIs (`SetInputFiles`, touch fingerprint spoof).
