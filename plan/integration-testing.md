# Integration testing plan — goapi ↔ real Camoufox binary

Drive the **built** browser (not a mock) through the goapi Juggler driver end-to-end.
Closes the CI gap: `goapi.yml` runs tests with no `CAMOUFOX_BIN` so all 25 browser
tests **skip**; `smoke.yml` runs only `TestRuntimeSpoofs` on a **linux** artifact.
Nothing exercises the other 24 feature tests against a real binary.

Binary under test: `/Applications/Camoufox.app/Contents/MacOS/camoufox` (FF150.0.2-beta.25, mac arm64).

## Layers

| # | Layer | Command | Verify |
|---|-------|---------|--------|
| 1 | Compile gate | `go vet ./... && go build ./...` | exit 0 |
| 2 | Functional integration (25 tests, real browser via Juggler) | `CAMOUFOX_BIN=<bin> go test -timeout 12m -v ./...` | 0 fail, 0 unexpected skip |
| 3 | Fingerprint spoof (subset of 2) | `-run TestRuntimeSpoofs` | 10/10 pass |
| 4 | Detector-site smoke (live: creepjs/sannysoft/areyouheadless/webrtc) | `go run ./example/integration` | runs to completion, JSON written, no headless/bot flag |

Layers 1–3 deterministic (offline localhost pages) → gating. Layer 4 hits live third-party
sites → network-dependent, informational (non-gating).

## Feature surface covered by layer 2

navigation+guard, DOM query (css/xpath/deep/shadow), element box, extract text, forms,
keyboard, mouse/scroll, touch, dialogs, downloads, uploads/file-chooser, mutations,
localStorage/state snapshot, accessibility snapshot, wait-for, query resilience,
runtime fingerprint spoofs.

## Success criteria

- Layer 1: clean.
- Layer 2: every test PASS or a *documented* skip (env without WebGL etc.); zero FAIL.
- Layer 4: session completes 4 oracles, `integration-results/*.json` written; headless=false.

## Run log — 2026-07-01, mac arm64, go1.26.4, binary /Applications/Camoufox.app/Contents/MacOS/camoufox

**Layer 1 — compile gate:** `go vet ./...` exit 0, `go build ./...` exit 0.

**Layer 2 — functional integration (`go test -timeout 9m -v ./...`, CAMOUFOX_BIN set):**
`ok  github.com/lang315/camoufox/goapi  204.052s` — exit 0.
Tally: **38 PASS / 0 FAIL / 3 SKIP** (browser suite + pkg/config + pkg/fingerprint + pkg/juggler).
Skips are documented build-capability gaps, not failures:
- `TestTouchscreenTap`, `TestTouchscreenTouchEvents` — build lacks `windowUtils.sendTouchEvent`
  (synthetic touch injection). Touch *fingerprint* still verified: `TestRuntimeSpoofs/touch_trio` PASS.
- `TestOnFileChooser` — Camoufox patches `InitColorPicker` only, no `InitFilePicker`
  (file-chooser interception). Direct file-set `TestSetInputFilesDirect` PASS.

**Layer 3 — fingerprint spoofs:** `TestRuntimeSpoofs` PASS, all 10 subtests
(webgpu_absent, webgl_renderer, codec_hevc, codec_decodingInfo, css_media, intl_consistency,
screen_orientation, touch_trio, voices_lang, readpixels_deterministic).

**Layer 4 — live detector smoke (`go run ./example/integration`):** all 4 oracles completed, no detection flags.
- creepjs: `6% like headless` (low), fp_id emitted.
- sannysoft: `navigator.webdriver=false`, "WebDriver Advanced" passed; consistent Windows persona
  (platform Win32, UA Firefox/133 Win64, WebGL ANGLE/NVIDIA GTX 980 Direct3D11, screen 1366×768).
- areyouheadless: "You are not Chrome headless".
- browserleaks/webrtc: "No Leak", local IP masked (`-`), SDP has only srflx public candidate — no host/mDNS leak.

**Result: PASS.** Every deterministic layer green; live smoke shows no detector flags. JSON in `goapi/integration-results/`.

## Follow-up (optional, not blocking)

CI gap remains: no job runs layer 2's full suite against a real binary — `goapi.yml` skips
(no CAMOUFOX_BIN), `smoke.yml` runs only `TestRuntimeSpoofs` on linux. To close, add a `CAMOUFOX_BIN`
step to the smoke job that runs `go test ./...` (not just `-run TestRuntimeSpoofs`) on the downloaded artifact.
