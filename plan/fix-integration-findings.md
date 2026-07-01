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

**Fix:** add the same guard block to `HTMLInputElement::InitFilePicker()`:
```cpp
nsCOMPtr<nsPIDOMWindowOuter> win = doc->GetWindow();
nsDocShell* docShell = win ? static_cast<nsDocShell*>(win->GetDocShell()) : nullptr;
if (docShell && docShell->IsFileInputInterceptionEnabled()) {
  docShell->FilePickerShown(this);
  return NS_OK;
}
```
(Keeping or removing the color-picker copy is a follow-up; color interception is harmless but
unused.) Then drop the unconditional `t.Skip` in `upload_test.go:TestOnFileChooser`.
**Confidence:** high — mirrors an existing working hunk, all downstream wiring present.
**Verify:** rebuild → `go test -run TestOnFileChooser` passes.

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

| Phase | Work | Verify | Cost |
|---|---|---|---|
| 1 | smoke.yml full suite | local run ✅ | done |
| 2 | filechooser hook → InitFilePicker | full rebuild + CI | 1 hunk + ~40min–4h build |
| 3 | jugglerSendTouchEvent patch | FF150 source + rebuild | patch + build; low value |

Phase 2/3 share one rebuild. Neither is verifiable without it.
