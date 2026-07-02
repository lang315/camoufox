# Fix plan — integration-testing findings (2026-07-01/02)

Findings from the full integration run (`plan/integration-testing.md`), plus a follow-up
adversarial audit ("check all") that overturned two initial conclusions.

## Finding 1 — CI never runs full suite vs real binary  ✅ DONE

`goapi.yml` runs `go test ./...` with no `CAMOUFOX_BIN` → all 25 browser tests `t.Skip`.
`smoke.yml` set `CAMOUFOX_BIN` but ran only `-run TestRuntimeSpoofs`, so ~24 feature tests never
touched a real build. `smoke.yml` now runs the full `go test -timeout 15m -v ./...`.
Verified locally (38 PASS / 0 FAIL / 3 SKIP, 204s) and in CI (smoke 28543247273, success).

Known limitation (follow-up): `smoke.yml` is `workflow_dispatch`-only and takes a manual
`run_id`, so real-binary coverage does not automatically gate PRs; `goapi.yml` still runs
unit-only on push. Auto-triggering smoke after `build.yml` (workflow_run) is a separate task.

## Finding 2 — file-chooser interception  ✅ FIXED (two bugs)

`TestOnFileChooser` originally skipped: `Page.fileChooserOpened` never fired. Two independent
bugs, both now fixed:

**Bug 2a — misplaced C++ hook.** The interception block sat in `HTMLInputElement::InitColorPicker`
(the `<input type=color>` path); `<input type=file>` calls `InitFilePicker`, which was unpatched.
All downstream machinery was already wired (juggler `fileChooserOpened` / `_filePickerShown`
observer; `nsDocShell::FilePickerShown` / `IsFileInputInterceptionEnabled` / setter). Fix: add the
same guard block to `InitFilePicker`. Applies clean to real 150.0.2 (offset +18, `patch -l`); CI
build 28529782482 confirmed it compiles and the interception path is reached.

**Bug 2b — goapi self-deadlock (the real blocker; first misdiagnosed as a Gecko nested loop).**
Juggler event handlers run *synchronously on the single readLoop goroutine* (contract in
`pkg/juggler/dispatcher.go:48`; dispatch at `:238`). `OnFileChooser` (`upload.go`) made a
*blocking* `callFunction` probe (`el.multiple`, with `context.Background()`) inside the handler,
so readLoop blocked waiting for a response only readLoop could deliver → deadlock. That, not the
browser, is why `mouseup` timed out and the event/SetFiles only flushed at teardown. Fix: run the
probe + user handler in a goroutine off readLoop, with a real timeout. (The adversarial audit
caught this after the hook patch had been wrongly reverted; the patch was correct.)

`TestOnFileChooser` un-skipped; asserts the input receives the file after the chooser fires.

## Finding 3 — synthetic touch injection  ✅ FIXED (JS-only)

`TestTouchscreenTap` / `TestTouchscreenTouchEvents` skipped: `windowUtils.sendTouchEvent is not a
function`. FF150 removed `nsIDOMWindowUtils::sendTouchEvent` (confirmed against 150.0.2 source),
but ships `Window.synthesizeTouchEvent()` (`dom/webidl/Window.webidl:677`, `[ChromeOnly]`,
returns defaultPrevented) as the replacement — reachable from the already-privileged juggler.
Fix: rewrite `PageAgent.js:_dispatchTouchEvent` to call `frame.domWindow().synthesizeTouchEvent(
type, touchPoints.map(p => ({identifier, offsetX, offsetY, radiiX, radiiY, rotationAngle,
pressure})), modifiers)`. JS-only juggler change (omni.ja repackage), no Gecko C++ compile. Base
`SynthesizeEventData` carries `pressure`, so force maps cleanly. Touch skips removed.

## Sequencing / cost

| # | Work | Verify | Status |
|---|------|--------|--------|
| 1 | smoke.yml full suite | local + CI smoke ✅ | DONE |
| 2 | InitFilePicker hook + goapi probe-off-readLoop | rebuild + smoke | FIXED (pending CI confirm) |
| 3 | PageAgent.js → synthesizeTouchEvent | rebuild + smoke | FIXED (pending CI confirm) |

Findings 2 and 3 share one browser rebuild (both touch build-baked files: the playwright patch +
`additions/juggler/content/PageAgent.js`). Touch caveat: `synthesizeTouchEvent` has no separate
tilt/twist beyond the dict defaults we pass — semantically fine for tap/touchstart/move/end.
