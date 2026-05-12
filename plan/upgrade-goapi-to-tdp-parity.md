# Plan: nâng `camoufox/goapi` lên ngang `tdp` (browser-level parity)

> **Revision 2** — đã hiệu chỉnh sau evaluator critique. Mọi method/event đối chiếu trực tiếp với `additions/juggler/protocol/Protocol.js`. Mọi claim về tdp đối chiếu file thực. Mọi claim về goapi hiện tại đối chiếu source thực.

## Context

Hai lib cùng họ Go browser-automation, do user sở hữu cả hai:

- **`tdp`** — lib trưởng thành ~80 file Go, CDP/Chromium, có AI agent + memory SQLite + pool/supervisor + observe/feed navigator. Public API rộng.
- **`camoufox/goapi`** — Go client mới ~2.6k LOC, Juggler IPC, zero-dep. API tối thiểu: Launch/Context/Page/Element/Frame, Goto, Click/Type/Focus, QuerySelector(All), Evaluate, Screenshot (clip required), Route, Cookies, InitScript (page+context), Geolocation, Proxy, fingerprint preset.

**Goapi đã có (đừng đụng):** `Page.AddInitScript`, `BrowserContext.AddInitScript`, `BrowserContext.SetGeolocation`, `Page.MainFrame`, `Page.Frames`, `Frame.Parent`, `Frame.IsMain`, `frameAttached/frameDetached` events đã wire trong `frame.go:131 registerFrameEvents`. `Page.Screenshot(ctx, juggler.PageScreenshotClip)` đã hoạt động.

Mục tiêu: thu hẹp gap API ở **mức trình duyệt**, **giữ zero-dep**, scope = browser-level parity (không AI, không pool/supervisor/SQLite, không action cache).

Protocol khảo sát: **19/24 feature đã có method/event sẵn**; 5 feature cần JS workaround. Một số tên method trong protocol khác với CDP — plan dùng tên Juggler chính xác.

## Phân pha

Ship độc lập, không phá API cũ trừ khi đã ghi rõ rename. Mỗi phase có example + unit test. Zero deps mới.

---

### Phase 1 — Input + Navigation + Event parity + foundations

Mục tiêu: lấp gap Juggler có method/event sẵn, **build sẵn 2 nền tảng dùng chung cho phase sau**: (a) `wait.go` state machine và (b) internal `wrapObject(objectId)` để xpath/shadow/fileChooser tái dùng.

**Foundations (làm trước các file tính năng):**
- `goapi/element.go` (sửa) — thêm internal `func (p *Page) wrapObject(frameID, objectID string) *ElementHandle` để dựng ElementHandle từ objectId trả về của bất kỳ `Runtime.evaluate`/`Page.fileChooserOpened`. Hiện `QuerySelector` đang inline phần wrap này; refactor cho phase sau reuse.
- `goapi/wait.go` (mới) — `WaitForOptions{State: Visible|Hidden|Attached|Detached, Timeout, PollInterval}`, helper `waitState(page, selector, opts)`. Port `tdp/wait_for_element.go`. Phase 1 element helpers dùng luôn.

**Files mới (tính năng):**
- `goapi/dialog.go` — `Page.OnDialog(handler) Subscription`. Wire **`Page.dialogOpened`** + **`Page.dialogClosed`** (cả hai, L705+L711). Handler nhận `Dialog{Type, Message, DefaultValue}` + `Accept(promptText)` / `Dismiss()` → gọi **`Page.handleDialog{dialogId, accept, promptText}`** (L965).
- `goapi/navigation.go` — `Page.Reload(ctx)` (NO opts — protocol L874 `params: {}`); `Page.GoBack(ctx) (success bool, err)` và `Page.GoForward(ctx) (success bool, err)` — params **bắt buộc** `frameId` (lấy MainFrameID), return `{success: bool}` từ protocol L858/866.
- `goapi/console.go` — `Page.OnConsole(handler)` wire **`Runtime.console`** event (L604; là event của domain Runtime, KHÔNG phải method). `Page.OnPageError(handler)` wire **`Page.uncaughtError`** L672 (fields: `frameId, message, stack`). `Page.OnCrash(handler)` wire **`Page.crashed`** L666 (no fields).
- `goapi/keyboard.go` — **redesign sau khi đọc protocol**: `Page.dispatchKeyEvent` (L908) KHÔNG có `modifiers` field. Modifier phải gửi qua **state machine**: tách down/up cho mỗi physical key.
  - `Page.Keyboard()` → `*Keyboard`
  - `Keyboard.Down(key string) error` — gửi `dispatchKeyEvent{type: "keydown", key, code, keyCode, text?}`
  - `Keyboard.Up(key string) error` — gửi `dispatchKeyEvent{type: "keyup", ...}`
  - `Keyboard.Press(key string) error` — down + up tiện lợi
  - `Keyboard.Type(text string, opts{Delay})` — **dùng `Page.insertText`** (L957) cho fast path, hoặc per-char `dispatchKeyEvent` khi cần delay realistic
  - Modifier combo = caller gọi `Down("Shift")` → `Press("KeyA")` → `Up("Shift")`. Port keymap từ `tdp/key.go`.
- `goapi/mouse.go` — `Page.Mouse()` → `*Mouse`: `Move(x,y)`, `Down(button)`, `Up(button)`, `Click(x,y,opts)`, `DblClick(x,y)`, `Wheel(dx,dy)`. Dùng **`Page.dispatchMouseEvent`** (L936) + **`Page.dispatchWheelEvent`** (L947, đã xác nhận có). Mouse event có `modifiers` field (khác key event), truyền bitmask được.
- `goapi/permissions.go` — `BrowserContext.GrantPermissions(origin string, perms []string)` qua **`Browser.grantPermissions`** L411. `BrowserContext.ResetPermissions()` qua **`Browser.resetPermissions`** L418 (dùng tên gốc, không invent `ClearPermissions`).

**Files sửa:**
- `goapi/element.go` — thêm:
  - `ElementHandle.Hover(ctx)` — `BoundingBox` lấy center, gọi `Page.dispatchMouseEvent{type:"mousemove"}`
  - `ElementHandle.ScrollIntoViewIfNeeded(ctx)` — **`Page.scrollIntoViewIfNeeded`** L836 (`{frameId, objectId, rect?}`)
  - `ElementHandle.BoundingBox(ctx) (*Box, error)` — gọi **`Page.getContentQuads`** L899 trả về `quads: Array<DOMQuad>`; fold tất cả quad thành bounding box (min/max x,y trên all points). KHÔNG phải single rect.
  - `ElementHandle.Screenshot(ctx, opts) ([]byte, error)` — compute bounds → `Page.screenshot{clip: ...}` (clip là REQUIRED ở L888).

**Test:**
- `goapi/dialog_test.go` — `httptest` serve `<script>alert('x')</script>`, assert handler nhận, Dismiss xong page tiếp tục.
- `goapi/keyboard_test.go` — input + key listener, sequence `Down("Shift") → Press("KeyA") → Up("Shift")`, đọc `value === "A"`.
- `goapi/element_box_test.go` — element absolute-positioned, so BoundingBox.
- `goapi/wait_test.go` — element xuất hiện sau timer JS, `State: Visible` resolve khi `offsetParent != null`.

**Examples mới:** `example/dialog/`, `example/keyboard/` (không trùng `actions, baseline, basic, botdetect, canvas, creepjs, creepjs-probe, fingerprint, integration, proxy` hiện có).

**Verify:**
```bash
cd goapi && go vet ./... && go test ./... && CAMOUFOX_BIN=... go run ./example/dialog
```

---

### Phase 2 — File handling + Accessibility + Frame URL/Name + Touch

Mục tiêu: hoàn thiện I/O quanh page. **Frame tree đã có sẵn ở goapi**; chỉ bổ sung thuộc tính URL/Name khi protocol cho.

**Files mới:**
- `goapi/upload.go` —
  - `ElementHandle.SetInputFiles(ctx, paths []string)` qua **`Page.setFileInputFiles{frameId, objectId, files[]}`** L784.
  - `Page.OnFileChooser(handler)`: bật **`Page.setInterceptFileChooserDialog{intercept: true}`** L972, wire **`Page.fileChooserOpened`** L723. Event có field `element: RemoteObject` (objectId) → dựng `*ElementHandle` qua `wrapObject` ở Phase 1 → handler nhận element **đã sẵn sàng** `SetInputFiles` luôn, không cần re-query.
- `goapi/download.go` —
  - `BrowserContext.SetDownloadOptions(opts{Dir, Behavior})` qua **`Browser.setDownloadOptions`** L379 (scope `browserContextId`).
  - `BrowserContext.OnDownload(handler)` wire **`Browser.downloadCreated`** L232 + **`Browser.downloadFinished`** L240. Cross-domain routing: event chứa `pageTargetId` → resolve `pageTargetId → *Page` qua `Browser.pages` map đã có ở `launch.go:34`. Handler nhận `*Download{UUID, URL, SuggestedFilename, Page() *Page, Cancel(), Wait()}`.
  - `Cancel()` qua **`Browser.cancelDownload{uuid}`** L482 (param là `uuid`, KHÔNG phải URL).
- `goapi/accessibility.go` — `Page.Accessibility().Snapshot(ctx) (*AXNode, error)` qua **`Accessibility.getFullAXTree`** L1010 (return `{tree}`). **KHÔNG dùng `Page.describeNode`** — describeNode L826 trả `{contentFrameId, ownerFrameId}` cho frame-introspection, không phải AX. AX là domain riêng `Accessibility`.
- `goapi/touch.go` — `Page.Touchscreen()` với `Tap(x,y)`, `TouchStart`, `TouchMove`, `TouchEnd`. Wrap **`Page.dispatchTouchEvent`** L919 + **`Page.dispatchTapEvent`** L929. `BrowserContext.SetTouchOverride(bool)` qua **`Browser.setTouchOverride`** L385.

**Files sửa:**
- `goapi/frame.go` — bổ sung `Frame.URL()`, `Frame.Name()` nếu chưa có (đọc lại file để xác nhận; tracker hiện có nhưng có thể chưa expose URL/Name). Frame tree event scoping đã đúng: `frameAttached/Detached` là Page-domain delivered theo sessionId per target. **Không cần "context-level subscription"** — bỏ ý đó khỏi rev 1.

**Test:**
- `goapi/upload_test.go` — trang `<input type=file>`; nhánh A: gọi `SetInputFiles` trực tiếp lên element; nhánh B: trigger file chooser, handler nhận element → `SetInputFiles`. Assert `files[0].name`.
- `goapi/download_test.go` — endpoint trả `Content-Disposition: attachment`; SetDownloadOptions với tmp dir; click link → handler nhận download → Wait → assert file tồn tại.
- `goapi/accessibility_test.go` — trang có `<button aria-label="X">`, snapshot tree, assert node với role+name.
- `goapi/touch_test.go` — `SetTouchOverride(true)`, dispatch tap, assert `touchstart` event JS đọc được.

**Examples mới:** `example/upload/`, `example/download/`.

**Verify:**
```bash
cd goapi && go vet ./... && go test ./... && CAMOUFOX_BIN=... go run ./example/upload
```

---

### Phase 3 — Resilience + DOM workarounds

Mục tiêu: bring stability tdp. JS injection cho cái Juggler không expose ở protocol layer.

**Files mới:**
- `goapi/xpath.go` — `Page.QueryXPath(ctx, expr) ([]*ElementHandle, error)`. `Runtime.evaluate` chạy `document.evaluate(expr, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null)`; return list objectId; mỗi cái qua `wrapObject` thành ElementHandle.
- `goapi/shadow.go` — `Page.QueryDeep(ctx, selector) []*ElementHandle` pierce shadow DOM. Inject JS walker recursive vào `shadowRoot.querySelectorAll`. Port `tdp/element_shadow.go` (73 LOC). Tái dùng `wrapObject`.
- `goapi/mutation.go` — `Page.WatchMutations(ctx, selector, opts) (<-chan Mutation, cancel func())`. Dùng **`Page.addBinding`** L791 + **`Page.bindingCalled`** L714 (binding là Page-domain, không phải Runtime). Đây là **primary path**, không có fallback polling (rev 1 hedge sai). Inject `MutationObserver` qua `AddInitScript`; JS bên trong gọi binding khi có mutation → Go nhận qua event channel. Port `tdp/dom_mutation.go` (146 LOC).
- `goapi/resilience.go` — port `tdp/selector_resilience.go` (138 LOC): `Page.QueryResilient(ctx, []Selector)` với `Selector{Kind: CSS|XPath|Text|TestID, Value}`. Fallback theo thứ tự, retry on stale.
- `goapi/navguard.go` — port `tdp/navigate_guard.go` (155 LOC): `Page.NavigateGuarded(ctx, url, opts)`. Verify URL match sau load (cho phép redirect list), backoff retry, bot-wall detection qua title heuristic.
- `goapi/react.go` — **đọc lại `tdp/react.go` (432 LOC) + `tdp/react.js` (35 KB bundle) trước khi port**. Rev 1 oversimplified "truy `__reactFiber$*`": tdp dùng JS bundle riêng, không inline lookup. Grep `tdp/react.go` không thấy chuỗi `reactFiber`/`__react` — kỹ thuật khác (DevTools hook hoặc bundle helper). Implementer: đọc bundle, port nguyên cách tdp dò React 16/17/18.

**Files sửa:**
- `goapi/element.go` — `WaitVisible` dùng `wait.go` (đã build ở Phase 1).
- `goapi/actions.go` — **rename** `WaitForSelector` → `WaitFor(selector, opts)`. KHÔNG giữ alias (API chưa có external consumer; shim là dead surface). Single commit rename.

**Test:**
- `goapi/xpath_test.go` — trang HTML, xpath relative, assert match.
- `goapi/resilience_test.go` — primary selector fail, fallback pass, assert resolved.
- `goapi/mutation_test.go` — JS thêm `<div>` sau 100ms, handler nhận event với target html.
- `goapi/react_test.go` — chỉ thêm khi đã port `react.js` bundle thành công; render React UMD trong test page, assert props read.

**Examples mới:** `example/resilient/`.

**Verify:**
```bash
cd goapi && go vet ./... && go test ./... && CAMOUFOX_BIN=... go run ./example/resilient
```

---

### Phase 4 — UX helpers (scripted)

Mục tiêu: ergonomics, hầu hết = JS injection + Go wrapper.

**Files mới:**
- `goapi/scroll.go` — port `tdp/smart_scroll.go` (134) + `scroll_gesture.go` (84): `Page.ScrollTo(opts{X,Y,Smooth})`, `Page.ScrollBy(dx,dy)`, `Page.ScrollToBottom(opts{MaxSteps, IdleMs})`. Wheel-based với jitter, dùng `Page.dispatchWheelEvent` ở Phase 1.
- `goapi/modal.go` — port `tdp/modal_handler.go` (151): `Page.DismissOverlays(ctx, opts)`. Heuristic z-index cao + close button → click. Predicate-driven.
- `goapi/form.go` — port `tdp/form_interaction.go` (113): `Page.FillForm(ctx, map[string]string)` key = label/name/placeholder/aria-label.
- `goapi/extract.go` — port `tdp/content_extractor.go` (143) + `page_summary.go` (73): `Page.ExtractText(ctx)`, `Page.Summary(ctx) → {Title, URL, Headings, MainText}`.
- `goapi/storage.go` — **clarify semantics (rev 1 sai)**:
  - `Page.LocalStorage(ctx) (map[string]string, error)` — origin của document hiện tại, no arg
  - `Page.SessionStorage(ctx) (map[string]string, error)` — tương tự
  - `BrowserContext.StorageState(ctx) (*StorageState, error)` — Playwright-style snapshot multi-origin với `origins[]` array (yêu cầu navigate qua từng origin)
  - **Bỏ** `Context.LocalStorage(origin)` rev 1 — API confused.
- `goapi/state.go` — port `tdp/page_state.go` (141): `Page.StateSnapshot(ctx) (*PageState, error)` URL/title/readyState/frame count/cookie count.

**Files sửa:**
- `goapi/README.md` — update feature matrix.

**Test:**
- `goapi/scroll_test.go` — trang tall, `ScrollToBottom`, assert `scrollY > pageHeight - viewportHeight`.
- `goapi/form_test.go` — form với label-input pair, fill bằng map, assert values.
- `goapi/extract_test.go` — page với `<article>`, assert text gom đúng order.
- `goapi/storage_test.go` — set localStorage qua evaluate, assert `Page.LocalStorage` trả đúng map.

**Examples mới:** `example/scroll/`, `example/form/`.

**Verify:**
```bash
cd goapi && go vet ./... && go test ./... && CAMOUFOX_BIN=... go run ./example/scroll
```

---

## Critical files (tham chiếu khi implement)

### `tdp` — pattern nguồn (đã verify tồn tại + LOC)
- `wait_for_element.go` (126) — wait state machine
- `selector_resilience.go` (138) — multi-strategy
- `navigate_guard.go` (155) — redirect/bot-wall guard
- `element_shadow.go` (73) — shadow pierce
- `dom_mutation.go` (146) — MutationObserver bridge
- `react.go` (432) + `react.js` (35 KB) — fiber inspect (đọc cả 2 trước khi port)
- `smart_scroll.go` (134) + `scroll_gesture.go` (84)
- `modal_handler.go` (151)
- `form_interaction.go` (113)
- `content_extractor.go` (143) + `page_summary.go` (73)
- `page_state.go` (141)
- `key.go` (372) + `keyboard_action.go` (119)

Tất cả ở `/Users/lang/GolandProjects/github.com/lang315/tdp/`.

### `goapi` — file đích
- `launch.go`, `context.go`, `page.go`, `element.go`, `actions.go`, `frame.go`, `clip.go`, `cookies.go`, `intercept.go`, `internal.go`, `network.go`, `options.go`, `pipe_*.go` (root)
- `pkg/juggler/types.go` — thêm types method/event mới
- `pkg/juggler/dispatcher.go` — wire subscription event mới (cross-domain routing cho Browser.downloadCreated)
- `pkg/juggler/session.go` — đã có session pinning theo targetId, reuse

### Protocol reference (chính xác)
- `/Users/lang/GolandProjects/github.com/lang315/camoufox/additions/juggler/protocol/Protocol.js` (1023 LOC) — số dòng cho method/event chính:
  - L379 `Browser.setDownloadOptions`, L385 `setTouchOverride`, L411 `grantPermissions`, L418 `resetPermissions`, L482 `cancelDownload`
  - L232 `Browser.downloadCreated`, L240 `downloadFinished`
  - L604 `Runtime.console` event
  - L666 `Page.crashed`, L672 `uncaughtError`, L677 `frameAttached`, L681 `frameDetached`, L705 `dialogOpened`, L711 `dialogClosed`, L714 `bindingCalled`, L723 `fileChooserOpened`
  - L784 `setFileInputFiles`, L791 `addBinding`, L826 `describeNode` (FRAME, not AX), L836 `scrollIntoViewIfNeeded`, L858 `goBack`, L866 `goForward`, L874 `reload`, L888 `screenshot`, L899 `getContentQuads`, L908 `dispatchKeyEvent` (NO modifiers field), L919 `dispatchTouchEvent`, L929 `dispatchTapEvent`, L936 `dispatchMouseEvent`, L947 `dispatchWheelEvent`, L957 `insertText`, L965 `handleDialog`, L972 `setInterceptFileChooserDialog`
  - L1010 `Accessibility.getFullAXTree`

---

## Verification cuối plan

Sau mỗi phase:

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox/goapi
go vet ./...
go test ./...
export CAMOUFOX_BIN=/path/to/camoufox/Camoufox.app/Contents/MacOS/camoufox
for ex in example/basic example/actions example/<phase-example>; do
  go run ./$ex || echo "FAIL: $ex"
done
```

Acceptance:
- `go test ./...` pass toàn bộ
- `go vet ./...` clean
- Mỗi phase ít nhất 1 `example/*` runnable
- `goapi/go.mod` `require` count không tăng
- README feature matrix update ✓

## Out-of-scope (đã chốt với user)

- AI agent loop, multi-LLM (`tdp/ai/*`)
- Pool + supervisor + keepalive
- Action cache, session memory SQLite (cần gorm — vi phạm zero-dep)
- Fingerprint rotation runtime
- Observe/feed navigator (FB-specific)
- Prometheus, WASM

## Changelog vs Revision 1

Sửa sau evaluator critique:

1. **Keyboard redesign**: `dispatchKeyEvent` không có `modifiers` field → API thành state machine `Down/Up/Press`, không phải `Press(key, mods)`.
2. **Type fast path**: dùng `Page.insertText` (L957) thay per-char keyEvent.
3. **Accessibility**: chuyển từ `Page.describeNode` (sai domain) sang `Accessibility.getFullAXTree` (L1010).
4. **Navigation**: `reload` no opts; `goBack/goForward` cần `frameId` param + return `{success}`.
5. **Permissions**: `Browser.resetPermissions` (tên gốc) thay `ClearPermissions` invented.
6. **BoundingBox**: fold quads array, không single rect.
7. **Download cancel**: `uuid` không phải URL; route Browser-domain event → Page qua `pageTargetId`.
8. **File chooser**: handler nhận ElementHandle đã wrap sẵn từ `element: RemoteObject` field.
9. **Mutation observer**: `Page.addBinding` + `Page.bindingCalled` là primary, không có hedge "if Juggler has".
10. **Frame tree**: bỏ "context-level subscription" sai; goapi đã có `registerFrameEvents` ở `frame.go:131`.
11. **Foundations Phase 1**: thêm internal `wrapObject(objectId)` helper + `wait.go` build sớm để Phase 2/3 tái dùng.
12. **React port**: đọc lại `tdp/react.js` bundle 35 KB trước khi port; không inline `__reactFiber$*` lookup.
13. **WaitForSelector rename**: bỏ alias shim — API chưa release, không cần backward-compat.
14. **Storage API**: split `Page.LocalStorage()` (current origin) vs `Context.StorageState()` (Playwright-style multi-origin); bỏ `Context.LocalStorage(origin)` confused.
15. **dispatchWheelEvent**: xác nhận có, bỏ hedge "if present".
16. **dialogClosed**: thêm event L711 (rev 1 chỉ có dialogOpened).
17. **uncaughtError fields**: ghi rõ `frameId, message, stack` cho handler.
18. **console event**: clarify Runtime emit `console` event (không phải method).
