# Fix Plan: 7 E2E test failures sau Phase 1-4

## Context

E2E full suite (29 pass, 7 fail) chạy với `CAMOUFOX_BIN=/tmp/camoufox-test/Camoufox.app/Contents/MacOS/camoufox`. Plan này fix từng failure theo nhóm root cause, ưu tiên fix dễ → khó.

Protocol verified verbatim từ `/Users/lang/GolandProjects/github.com/lang315/camoufox/additions/juggler/protocol/Protocol.js`. Wiring hiện tại check qua grep:

- Event subs đều dùng `p.bc.b.conn.On("...", ...)` + filter `ev.SessionID != p.session.ID()` — pattern đúng.
- `Page.dispatchKeyEvent` slow path gửi `text` field cùng keydown → race với Shift.
- `Page.setInterceptFileChooserDialog` param key dùng `enabled` (đúng protocol L972).
- `Page.fileChooserOpened` event field là `executionContextId`, KHÔNG phải `frameId` (L723).
- `Page.dispatchTouchEvent` params: `type` enum, `touchPoints` (NOT `touches`), `modifiers` number.
- AXTree top-level role `"document"` → walker phải đệ quy `children` để tìm node.

## Phase 5 — fix grouped by root cause

### Group A — Test assertion bug (trivial)

**A1. `resilience_test.go:68` — whitespace mismatch**

- Hiện: `expected 'Submit', got "\nSubmit\n"`
- Root: `ElementHandle.TextContent()` trả raw `textContent` có whitespace từ HTML formatting; `KindText` match dùng `.trim()` ở JS nên match thành công nhưng test assertion so chuỗi trực tiếp.
- Fix: trong `goapi/resilience_test.go` đổi `if text != "Submit"` thành `if strings.TrimSpace(text) != "Submit"`. KHÔNG đụng implementation (trim ở Go side sẽ phá contract của TextContent đối với caller khác).
- File: `goapi/resilience_test.go`

### Group B — Event wiring / field mismatch

**B1. `dialog_test.go:62` — "dialog handler never fired" sau 30s**

- Hiện: handler subscribed, navigate page có `<script>alert('x')</script>`, nhưng `Page.dialogOpened` không tới.
- Root candidates (debug theo thứ tự):
  1. Subscription register **sau** navigation hoàn tất → alert đã fire khi browser load script. Reorder: `OnDialog` trước `Goto`.
  2. Goto chờ `load`; alert chặn document onload → Goto chưa return khi alert fire → test deadlock trên Goto, không trên handler chờ.
  3. Page.dialogOpened auto bị firefox auto-dismiss khi không có handler đăng ký timely → check `Browser.setInterceptDialogs` hoặc tương đương (Protocol.js KHÔNG có method này — confirm).
  4. `Goto` block trên `load` event mà alert đang giữ document → fix: `Goto` với `waitUntil: domcontentloaded`.
- Action:
  - Đọc `goapi/dialog_test.go` thực tế xem thứ tự `OnDialog` vs `Goto`.
  - Nếu reorder không đủ, đổi waitUntil sang `domcontentloaded` hoặc dùng goroutine để `Goto` không block.
  - Thêm debug log tạm để confirm subscription nhận event nào.
- File: `goapi/dialog.go` (nếu thiếu enable call), `goapi/dialog_test.go` (reorder + waitUntil).

**B2. `upload_test.go:146` — `OnFileChooser` handler never fired**

- Hiện: handler đăng ký, JS hoặc Go gọi click input → event không tới.
- Root candidates:
  1. `Page.setInterceptFileChooserDialog` call **bị silently swallowed** trong `upload.go:53` (`_ = p.session.Call(...)`) — verify nó trả nil error bằng cách check log. Nếu error → handler không bao giờ fire vì intercept off.
  2. Event payload trong dispatcher decode sai: protocol nói `executionContextId` + `element`, nhưng types.go có thể decode bằng `frameId` → field bỏ trống → handler vẫn fire nhưng `wrapObject` panic / element nil. Verify `pkg/juggler/types.go` cho `PageFileChooserOpenedEvent`.
  3. JS `.click()` ở test không phải "user gesture" thật — Firefox có thể gate file chooser sau user input. Fix: gọi `p.Mouse().Click(...)` tại bounding-box của input thay JS `.click()`.
- Action:
  - Đổi `upload.go:53` từ `_ = ...` thành check error + log nếu fail.
  - Verify event struct trong `pkg/juggler/types.go` field name là `ExecutionContextID` không phải `FrameID`.
  - Đổi test trigger từ JS click sang Mouse click.
- File: `goapi/upload.go`, `goapi/pkg/juggler/types.go`, `goapi/upload_test.go`.

### Group C — Implementation bug

**C1. `keyboard_test.go:68` — Shift+KeyA cho ra "a" không "A"**

- Hiện: sequence `Down("Shift") → Press("KeyA") → Up("Shift")` nhưng input nhận lowercase.
- Root: protocol `Page.dispatchKeyEvent` KHÔNG có `modifiers` field (L908). Firefox theo dõi modifier state qua keydown/keyup ordering. NHƯNG slow path gửi `text:"a"` cùng keydown của `KeyA` — `text` field override → browser insert "a" trực tiếp, bỏ qua Shift state.
- Fix trong `goapi/keyboard.go`:
  - `Keyboard.Down(key)` và `Keyboard.Up(key)` KHÔNG gửi `text` field.
  - `Keyboard.Press(key)` KHÔNG gửi `text` field.
  - `Keyboard.Type(text)` fast path đã đúng (dùng `Page.insertText`).
  - `Keyboard.Type` slow path (khi có Delay): gửi per-char keydown + keyup. `text` field chỉ gửi khi caller muốn ký tự cụ thể VÀ không có modifier — nhưng API không track modifier state → đơn giản nhất: bỏ `text` ở slow path luôn, để Firefox tự compose ký tự từ key + state.
- Verify trên Firefox: keydown với `key:"a", code:"KeyA", keyCode:65, text:""` + Shift đang held → input nhận "A".
- File: `goapi/keyboard.go`.

**C2. `accessibility_test.go:63` — root="document", expected button "Submit form" in tree**

- Hiện: snapshot trả root role `"document"`, không thấy button khi assert.
- Root candidates:
  1. Walker không recurse `children` (protocol AXTree có `children: Optional(Array<AXTree>)`, L151). Verify trong `goapi/accessibility.go` rằng `Snapshot` parse + traverse đệ quy.
  2. Test walker logic sai: tìm role+name nhưng chỉ check root.
  3. Firefox a11y service chưa init → tree trả về document trống. Tốn-known: cần page có content load xong + a11y service activate. Có thể cần wait `domcontentloaded` + extra delay trước snapshot.
- Action:
  - Đọc `goapi/accessibility.go` để xác nhận `AXNode` struct có `Children []*AXNode` + parser fill đệ quy.
  - Đọc `goapi/accessibility_test.go:63` để xem walker logic.
  - Nếu walker đúng nhưng tree trả về thiếu button → thêm `time.Sleep(500*time.Millisecond)` post-load hoặc dùng `waitState` cho selector trước.
- File: `goapi/accessibility.go` + `goapi/accessibility_test.go`.

### Group D — Platform / browser limitation

**D1+D2. `touch_test.go:67` + `touch_test.go:137` — `windowUtils.sendTouchEvent is not a function`**

- Hiện: cả `dispatchTapEvent` và `dispatchTouchEvent` fail vì Firefox desktop build không expose `sendTouchEvent` trong `domWindow.windowUtils` mặc dù gọi `Browser.setTouchOverride(true)`.
- Root: Firefox desktop cần pref `dom.w3c_touch_events.enabled=1` (hoặc `2` cho force-on) **lúc khởi động**, không thể bật runtime qua override một mình. `Browser.setTouchOverride` chỉ flag emulation flag UI level; backend touch API vẫn cần pref.
- 2 lựa chọn:
  - **Option A (preferred):** thêm pref vào launch args / CAMOU_CONFIG. Camoufox CAMOU_CONFIG có key tương đương — check `pkg/config/config.go`. Nếu không có, dùng `WithFirefoxPref("dom.w3c_touch_events.enabled", "1")` hoặc tương đương qua `--MOZ_LOG`/profile prefs.js.
  - **Option B (fallback):** skip test trên `runtime.GOOS == "darwin"` || `"linux"` desktop với `t.Skipf("touch events require dom.w3c_touch_events.enabled=1 in browser prefs")`. Document caveat trong `touch.go` godoc.
- Action ưu tiên: tìm cách wire pref qua launch options. Nếu Camoufox không expose, dùng Option B.
- File: `goapi/touch.go` (godoc caveat), `goapi/touch_test.go` (skip on desktop OR enable pref), `goapi/options.go` hoặc `pkg/config/config.go` (thêm pref nếu khả thi).

## Order of execution

Ưu tiên dễ → khó để verify từng bước:

1. **A1** (test trim) — 1 dòng sửa, chạy lại assert pass.
2. **C1** (keyboard text field) — chỉnh keyboard.go bỏ `text` ở Down/Up/Press + slow path.
3. **B2** (fileChooser field name) — verify types.go, sửa nếu mismatch.
4. **B1** (dialog ordering / waitUntil) — đọc test, reorder/waitUntil.
5. **C2** (accessibility walker) — đọc walker + test, fix recursion hoặc thêm delay.
6. **D1/D2** (touch pref) — research pref injection; fallback skip.

Mỗi item chạy `CAMOUFOX_BIN=... go test -run <TestName>` ngay sau fix để verify trước khi sang item tiếp.

## Verification cuối

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox/goapi
go vet ./...
go build ./...
CAMOUFOX_BIN=/tmp/camoufox-test/Camoufox.app/Contents/MacOS/camoufox \
  go test -timeout 10m ./...
grep -c '^require' go.mod   # vẫn = 0
```

Acceptance:
- 36/36 test pass (hoặc 34 pass + 2 touch skip-on-darwin với reason).
- Zero new deps.
- Không revert API design Phase 1-4.

## Out-of-scope

- KHÔNG đổi public API (giữ `Keyboard.Down/Up/Press/Type`, `Page.OnDialog`, etc.).
- KHÔNG thêm prometheus/log framework — fix bằng stdlib `log` hoặc `fmt.Errorf` chain.
- KHÔNG port thêm feature mới — chỉ fix bug.
