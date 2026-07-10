# Spoofing-patch hardening — P1 (coherence at the C++ chokepoint + goapi guard) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make three spoofed signals internally coherent *at the C++ chokepoint* (`additions/camoucfg/MaskConfig.hpp` + the patch getters that read through it), so goapi, pythonlib, and a hand-authored raw `CAMOU_CONFIG` all get the same coherent answer: (1) `screen.orientation.angle` is derived from the spoofed orientation type instead of leaking the native host angle when the angle key is absent; (2) `canPlayType`/`isTypeSupported`/`decodingInfo` read one merged per-codec table so they cannot disagree; (3) `prefers-color-scheme` and Gecko's repainted system colors (`Canvas`/`CanvasText`/`AccentColor` + scrollbars/form controls) agree, via a new PreferenceSheet patch. On top of the chokepoint, goapi gets a fail-fast, **non-authoritative** `Config.Validate() error` dev guard wired into `Launch`.

**Architecture (per spec §Phase 1):** Items 1, 2, and 4 touch only goapi + two *already-clean* patches and run in parallel with P0 — no dependency on the canvas/webrtc re-anchor. Item 3 is a brand-new C++ patch (`patches/system-color-spoofing.patch`), carries its own re-anchor risk (R1 in the design doc), and ships as its **own PR**, sequenced after P0 established the rehearsal method (`scripts/rehearse-patch.sh`, already on this branch as of P0 Task 1). This plan is therefore split into two tracks in one document:

- **Track A** (Tasks 1–7): orientation + media-codec chokepoint fixes, goapi defaults, `Config.Validate()`. One PR.
- **Track B** (Tasks 8–10): the new system-color patch + its build-tester collector. A second, independent PR.

**Design decisions made explicit here (not fully spelled out in the spec — stating them per "Think Before Coding" so an implementer doesn't have to silently pick one):**

1. **Single source of truth for the orientation `(type, angle)` mapping.** `goapi/pkg/fingerprint` already depends on `goapi/pkg/config` (not the reverse), so the mapping (`*-primary` → 0, `*-secondary` → 180 — the desktop-natural-only mapping the spec specifies) is implemented **once**, in a new exported helper in `pkg/config`, and called from both the generator default (Task 2) and `Config.Validate()` (Task 1). The C++ chokepoint (Task 3) cannot import Go, so it reimplements the identical two-line mapping with a comment cross-referencing the Go function name — kept in sync by convention, flagged as a residual risk in Self-Review.
2. **The "coherence test" the spec asks for in items 1 and 2 is implemented by reusing `Config.Validate()`**, not by duplicating the iff-checks in a separate test-only helper: Task 6 generates configs across every OS × several seeds and asserts `cfg.Validate() == nil`. This is a property/regression test (already green once Tasks 2–5 land), not RED-first — Task 1's and Tasks 2/4's own unit tests are the RED-first drivers. This is called out explicitly so nobody mistakes it for a failing-first test.
3. **P1 registers no new `CAMOU_CONFIG` keys.** Items 1 and 2 reuse `screen:orientation` / `screen:orientationAngle` / `mediaCapabilities:canPlayType` / `mediaCapabilities:decodingInfo` (already emitted by `config.go` and already listed in `knownConfigOnlyKeys` in `goapi/pkg/config/drift_test.go` as a documented properties.json lag). Item 3 reuses the existing `cssMedia:prefersColorScheme` key at the C++ layer — it does not add a Go-side field. **`settings/camoucfg.jvv` and `settings/properties.json` are not touched in this plan.**

**Tech Stack:** Go 1.22 (`goapi/`), C++ (Firefox patches + `additions/camoucfg/MaskConfig.hpp`, a whole-file copy — not a diff), TypeScript (`build-tester/`), Python (`build-tester/scripts/`), GitHub Actions.

## Global Constraints

- Firefox pinned: `version=152.0.4`, `release=beta.25` (`upstream.sh`). Track B's fetch step targets `https://hg.mozilla.org/releases/mozilla-release/raw-file/FIREFOX_152_0_4_RELEASE/<path>`.
- `patches/screen-orientation-spoofing.patch` (Task 3) is an edit to an **already-applied, already-clean** patch — not a re-anchor against fresh upstream source. Still gate it through `FETCH="curl -fsSL" bash scripts/rehearse-patch.sh screen-orientation-spoofing.patch` (built in P0 Task 1) before commit: `rejects==0 AND skipped==0 AND wrongpath==0 AND fuzz==0 AND max|offset|<=2`. If `gpatch` reports a hunk-count mismatch, recount the `@@` header — the gate catches a miscount immediately, do not hand-trust the arithmetic in this doc.
- `patches/media-codec-spoofing.patch` is **not modified** in this plan — only `additions/camoucfg/MaskConfig.hpp` changes (item 2), and the patch's three call sites (`HTMLMediaElement::CanPlayType`, `MediaSource::IsTypeSupported`, `MediaCapabilities::CreateDecodingInfoPromise`) already call `MaskConfig::GetMediaCanPlayType`/`GetMediaDecodingInfo` with unchanged signatures, so no patch hunk needs touching.
- `additions/camoucfg/MaskConfig.hpp` is a **whole-file copy** (`copy-additions.sh`), not a unified diff — it is edited directly, not through `scripts/rehearse-patch.sh` (that tool is `patches/*.patch`-only). It has no local compile path (depends on `mozilla/glue/Debug.h`); its only verification short of a full CI build is structural/grep self-review (Task 5) — the real compile proof is Track A's CI gate (Task 7).
- **`Config.Validate()` is non-authoritative.** State this in its doc comment verbatim per spec: it protects only goapi callers that route through `Launch`; pythonlib and a hand-authored raw `CAMOU_CONFIG` bypass it entirely. The real guarantee is the C++ chokepoint (Tasks 3, 5, and Track B's patch).
- Backward-compat (spec R3): both `screen:orientation` and `screen:orientationAngle` config keys are retained; only the *default* when the angle key is absent changes from "fall through to native" to "derive from type." Note this in the PR body.
- Every PR: tied to a GitHub issue; **both** `build-tester/` and `service-tester/` pass; PR body carries concrete evidence (command output + exit status), per repo rule and the user's global PR-evidence rule.
- `cd goapi && go vet ./... && go build ./... && go test -timeout 5m ./...` is the exact command sequence CI runs (`.github/workflows/goapi.yml`) — use it locally before every Track A commit.
- Surgical: `git add` exact files, never a whole directory.
- Tooling floor inherited from P0 (Task 9 only): bash ≥ 4, `gpatch`, `FETCH` env for `hg.mozilla.org` egress (`scripts/rehearse-patch.README.md` documents the sandboxed-host caveat — this plan's Task 9 may need to run on a host with open egress).

---

### Task 0: Tracking issues

**Files:** none

- [ ] **Step 1: Track A issue**
```bash
gh issue create --repo lang315/camoufox --title "P1: coherence at the C++ chokepoint (orientation, media-codec) + goapi Validate()" --body "Phase 1 items 1,2,4 — orientation angle derivation, unified media-codec table, fail-fast Config.Validate(). Runs parallel with P0. Spec: docs/superpowers/specs/2026-07-08-spoofing-patch-hardening-design.md. Plan: docs/superpowers/plans/2026-07-08-spoofing-patch-hardening-p1.md"
```
Record issue number `NA`.

- [ ] **Step 2: Track B issue**
```bash
gh issue create --repo lang315/camoufox --title "P1.3: new system-color PreferenceSheet patch (prefers-color-scheme <-> system colors)" --body "Phase 1 item 3 — patches/system-color-spoofing.patch, own PR, subject to the P0 rehearsal method. Spec: docs/superpowers/specs/2026-07-08-spoofing-patch-hardening-design.md. Plan: docs/superpowers/plans/2026-07-08-spoofing-patch-hardening-p1.md"
```
Record issue number `NB`.

---

## Track A

### Task 1: `Config.Validate() error` — orientation + media-codec rules (RED → GREEN)

**Files:** Create `goapi/pkg/config/validate.go`, `goapi/pkg/config/validate_test.go`

**Interfaces:**
```go
func OrientationAngleForType(t string) (angle uint32, ok bool)
func AspectMatchesOrientation(orientationType string, width, height uint32) bool
func (c *Config) Validate() error
```

- [ ] **Step 1 (RED): write `validate_test.go`** — table-driven, package `config`. `Validate()` does not exist yet, so this fails to compile (red):
```go
package config

import "testing"

func TestValidateOrientation(t *testing.T) {
	cases := []struct {
		name    string
		cfg     Config
		wantErr bool
	}{
		{"unset - ok", Config{}, false},
		{"landscape-primary/0 - legal", Config{ScreenOrientation: "landscape-primary", ScreenOrientationAngle: Uint32(0)}, false},
		{"landscape-secondary/180 - legal", Config{ScreenOrientation: "landscape-secondary", ScreenOrientationAngle: Uint32(180)}, false},
		{"portrait-primary/0 - legal", Config{ScreenOrientation: "portrait-primary", ScreenOrientationAngle: Uint32(0)}, false},
		{"portrait-secondary/180 - legal", Config{ScreenOrientation: "portrait-secondary", ScreenOrientationAngle: Uint32(180)}, false},
		{"landscape-primary/180 - illegal pair", Config{ScreenOrientation: "landscape-primary", ScreenOrientationAngle: Uint32(180)}, true},
		{"landscape-secondary/0 - illegal pair", Config{ScreenOrientation: "landscape-secondary", ScreenOrientationAngle: Uint32(0)}, true},
		{"unrecognized type", Config{ScreenOrientation: "flat", ScreenOrientationAngle: Uint32(0)}, true},
		{"type/aspect mismatch: landscape on portrait dims", Config{
			ScreenOrientation: "landscape-primary", ScreenWidth: Uint32(1080), ScreenHeight: Uint32(1920),
		}, true},
		{"type/aspect coherent: landscape on landscape dims", Config{
			ScreenOrientation: "landscape-primary", ScreenWidth: Uint32(1920), ScreenHeight: Uint32(1080),
		}, false},
		{"type/aspect mismatch: portrait on landscape dims", Config{
			ScreenOrientation: "portrait-primary", ScreenWidth: Uint32(1920), ScreenHeight: Uint32(1080),
		}, true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			err := tc.cfg.Validate()
			if (err != nil) != tc.wantErr {
				t.Errorf("Validate() err=%v, wantErr=%v", err, tc.wantErr)
			}
		})
	}
}

func TestValidateMediaCodecs(t *testing.T) {
	cases := []struct {
		name    string
		cfg     Config
		wantErr bool
	}{
		{"unset - ok", Config{}, false},
		{"coherent both sides", Config{
			MediaCanPlayType:  map[string]string{"hvc1": "probably"},
			MediaDecodingInfo: map[string]MediaDecodeInfo{"hvc1": {Supported: true}},
		}, false},
		{"coherent unsupported", Config{
			MediaCanPlayType:  map[string]string{"hvc1": ""},
			MediaDecodingInfo: map[string]MediaDecodeInfo{"hvc1": {Supported: false}},
		}, false},
		{"one-sided: canPlayType only", Config{
			MediaCanPlayType: map[string]string{"hvc1": "probably"},
		}, true},
		{"one-sided: decodingInfo only", Config{
			MediaDecodingInfo: map[string]MediaDecodeInfo{"hvc1": {Supported: true}},
		}, true},
		{"per-key disagreement", Config{
			MediaCanPlayType:  map[string]string{"hvc1": "probably"},
			MediaDecodingInfo: map[string]MediaDecodeInfo{"hvc1": {Supported: false}},
		}, true},
		{"key present only in canPlayType", Config{
			MediaCanPlayType:  map[string]string{"hvc1": "probably", "av1": ""},
			MediaDecodingInfo: map[string]MediaDecodeInfo{"hvc1": {Supported: true}},
		}, true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			err := tc.cfg.Validate()
			if (err != nil) != tc.wantErr {
				t.Errorf("Validate() err=%v, wantErr=%v", err, tc.wantErr)
			}
		})
	}
}
```

- [ ] **Step 2: confirm RED** — `cd goapi && go test ./pkg/config/... -run TestValidate` → compile error (`Validate` undefined). This is the expected red state.

- [ ] **Step 3 (GREEN): write `validate.go`**:
```go
package config

import (
	"fmt"
	"strings"
)

// OrientationAngleForType returns the coherent screen.orientation.angle for
// a desktop-natural (landscape) screen:orientation type: 0 for the
// *-primary member of a pair, 180 for *-secondary. ok is false for an
// unrecognized type. Mobile / portrait-natural devices need a
// natural-orientation field (not modeled yet) before this can return
// 90/270 for the cross pair — see design doc P1.1; portrait presets are
// out of scope until then.
//
// This is the single source of truth for the mapping in Go. The C++
// chokepoint (dom/base/ScreenOrientation.cpp::GetAngle, edited by
// patches/screen-orientation-spoofing.patch) reimplements the identical
// two-way mapping — Go and C++ cannot share code across the process
// boundary, so keep them in sync by hand if this mapping ever changes.
func OrientationAngleForType(t string) (angle uint32, ok bool) {
	switch t {
	case "landscape-primary", "portrait-primary":
		return 0, true
	case "landscape-secondary", "portrait-secondary":
		return 180, true
	default:
		return 0, false
	}
}

// AspectMatchesOrientation reports whether width×height agrees with the
// landscape/portrait sense of orientationType (landscape ⟺ width>=height).
// Returns true (no opinion) for a type this function doesn't recognize as
// landscape/portrait — callers must reject unrecognized types separately
// (OrientationAngleForType's ok return does that).
func AspectMatchesOrientation(orientationType string, width, height uint32) bool {
	switch {
	case strings.HasPrefix(orientationType, "landscape"):
		return width >= height
	case strings.HasPrefix(orientationType, "portrait"):
		return height > width
	default:
		return true
	}
}

// Validate is a fail-fast DEV GUARD against an internally incoherent
// config: illegal screen.orientation (type,angle) pairs, orientation<->
// aspect mismatches, and one-sided/disagreeing media-codec maps.
//
// It is deliberately NON-AUTHORITATIVE. The real coherence guarantee is
// the C++ chokepoint (additions/camoucfg/MaskConfig.hpp + the patch
// getters), which is the only thing every producer — goapi, pythonlib,
// and a hand-authored raw CAMOU_CONFIG — is forced through. Validate only
// protects goapi callers that route through Launch (see goapi/launch.go);
// pythonlib and raw CAMOU_CONFIG bypass it entirely.
func (c *Config) Validate() error {
	var errs []string
	if err := c.validateOrientation(); err != nil {
		errs = append(errs, err.Error())
	}
	if err := c.validateMediaCodecs(); err != nil {
		errs = append(errs, err.Error())
	}
	if len(errs) == 0 {
		return nil
	}
	return fmt.Errorf("config: %s", strings.Join(errs, "; "))
}

func (c *Config) validateOrientation() error {
	if c.ScreenOrientation == "" {
		return nil // not spoofed — nothing to check
	}
	if c.ScreenOrientationAngle != nil {
		want, ok := OrientationAngleForType(c.ScreenOrientation)
		if !ok {
			return fmt.Errorf("screen:orientation %q is not a recognized type", c.ScreenOrientation)
		}
		if *c.ScreenOrientationAngle != want {
			return fmt.Errorf("screen:orientation %q with screen:orientationAngle %d is an illegal pair (want %d)",
				c.ScreenOrientation, *c.ScreenOrientationAngle, want)
		}
	}
	if c.ScreenWidth != nil && c.ScreenHeight != nil &&
		!AspectMatchesOrientation(c.ScreenOrientation, *c.ScreenWidth, *c.ScreenHeight) {
		return fmt.Errorf("screen:orientation %q does not match screen %dx%d aspect",
			c.ScreenOrientation, *c.ScreenWidth, *c.ScreenHeight)
	}
	return nil
}

func (c *Config) validateMediaCodecs() error {
	if len(c.MediaCanPlayType) == 0 && len(c.MediaDecodingInfo) == 0 {
		return nil // not spoofed — nothing to check
	}
	if (len(c.MediaCanPlayType) == 0) != (len(c.MediaDecodingInfo) == 0) {
		return fmt.Errorf("one-sided media codec config: canPlayType has %d entries, decodingInfo has %d",
			len(c.MediaCanPlayType), len(c.MediaDecodingInfo))
	}
	for k, cp := range c.MediaCanPlayType {
		dec, ok := c.MediaDecodingInfo[k]
		if !ok {
			return fmt.Errorf("media codec %q: present in canPlayType, missing from decodingInfo", k)
		}
		if (cp != "") != dec.Supported {
			return fmt.Errorf("media codec %q: canPlayType=%q disagrees with decodingInfo.Supported=%v", k, cp, dec.Supported)
		}
	}
	for k := range c.MediaDecodingInfo {
		if _, ok := c.MediaCanPlayType[k]; !ok {
			return fmt.Errorf("media codec %q: present in decodingInfo, missing from canPlayType", k)
		}
	}
	return nil
}
```

- [ ] **Step 4: confirm GREEN** — `cd goapi && go test ./pkg/config/... -run 'TestValidateOrientation|TestValidateMediaCodecs' -v` → all subtests pass.

- [ ] **Step 5: commit**
```bash
git add goapi/pkg/config/validate.go goapi/pkg/config/validate_test.go
git commit -m "feat(goapi): Config.Validate() fail-fast dev guard for orientation/media-codec coherence"
```

---

### Task 2: Orientation — goapi generator default (RED → GREEN)

**Files:** Modify `goapi/pkg/fingerprint/generator.go:127-135`, `goapi/pkg/fingerprint/fingerprint_test.go`

- [ ] **Step 1 (RED): extend `TestScreenOrientation`** in `fingerprint_test.go` (currently lines 153-172) with a case the current hardcoded `angle=0` fails — a caller-supplied secondary type with no angle:
```go
	// Caller-supplied secondary type must get angle=180, not the hardcoded
	// 0 the old generator always wrote (P1.1 bug).
	secondary := &config.Config{ScreenOrientation: "landscape-secondary"}
	if err := Generate(secondary, Options{OS: "windows", Rand: rand.New(rand.NewPCG(4, 4))}); err != nil {
		t.Fatal(err)
	}
	if secondary.ScreenOrientationAngle == nil || *secondary.ScreenOrientationAngle != 180 {
		t.Errorf("landscape-secondary angle = %v, want 180", secondary.ScreenOrientationAngle)
	}
```
Append this to the existing `TestScreenOrientation` function body (after the portrait-dims block, before its closing `}`).

- [ ] **Step 2: confirm RED** — `cd goapi && go test ./pkg/fingerprint/... -run TestScreenOrientation -v` → fails: `landscape-secondary angle = 0, want 180`.

- [ ] **Step 3 (GREEN): fix `generator.go`** — replace the hardcoded angle block (current lines 133-135):
```go
	if cfg.ScreenOrientationAngle == nil {
		cfg.ScreenOrientationAngle = config.Uint32(0)
	}
```
with:
```go
	if cfg.ScreenOrientationAngle == nil {
		angle, _ := config.OrientationAngleForType(cfg.ScreenOrientation)
		cfg.ScreenOrientationAngle = config.Uint32(angle)
	}
```
(`ok` is discarded: at this call site `cfg.ScreenOrientation` is always non-empty — set either by the block immediately above or by the caller — so an unrecognized type falls back to angle 0, same as the old default for the case `OrientationAngleForType` doesn't know.)

- [ ] **Step 4: confirm GREEN** — `cd goapi && go test ./pkg/fingerprint/... -run TestScreenOrientation -v` → passes. Also re-run `TestGenerateWindowsPreset` and the full package (`go test ./pkg/fingerprint/...`) to confirm no other test regressed.

- [ ] **Step 5: commit**
```bash
git add goapi/pkg/fingerprint/generator.go goapi/pkg/fingerprint/fingerprint_test.go
git commit -m "fix(goapi): derive orientation angle from type instead of hardcoding 0"
```

---

### Task 3: Orientation — C++ chokepoint (`ScreenOrientation::GetAngle`)

The current patch (`patches/screen-orientation-spoofing.patch`) makes `GetAngle` return the explicit `screen:orientationAngle` key when present, but falls through to the **native host angle** when it's absent — leaking real device rotation even though `screen:orientation` (the type) is spoofed. Fix: when the angle key is absent, derive it from the spoofed type using the same `*-primary`→0 / `*-secondary`→180 mapping as `OrientationAngleForType` (Task 1). **Both config keys stay** — this only changes what happens when the angle key is *absent*.

**Files:** Modify `patches/screen-orientation-spoofing.patch`

- [ ] **Step 1: edit the `GetAngle` hunk** — the current hunk (patch lines 28-38) is:
```diff
@@ -739,6 +748,10 @@ OrientationType ScreenOrientation::GetType(CallerType aCallerType,
 
 uint16_t ScreenOrientation::GetAngle(CallerType aCallerType,
                                      ErrorResult& aRv) const {
+  // camoufox: spoof orientation angle, coherent with screen:orientation (#20).
+  if (auto v = MaskConfig::GetUint32("screen:orientationAngle")) {
+    return static_cast<uint16_t>(*v);
+  }
   Document* doc = GetResponsibleDocument();
   BrowsingContext* bc = doc ? doc->GetBrowsingContext() : nullptr;
   if (!bc) {
```
Replace it with (7 new `+` lines inserted between the existing angle-key check and the native fallback; `@@` new-count updated from 10 to 17 — `old_count` stays 6, only new-count changes since no context lines are touched):
```diff
@@ -739,6 +748,17 @@ OrientationType ScreenOrientation::GetType(CallerType aCallerType,
 
 uint16_t ScreenOrientation::GetAngle(CallerType aCallerType,
                                      ErrorResult& aRv) const {
+  // camoufox: spoof orientation angle, coherent with screen:orientation (#20).
+  if (auto v = MaskConfig::GetUint32("screen:orientationAngle")) {
+    return static_cast<uint16_t>(*v);
+  }
+  // camoufox: no explicit angle key — derive from the spoofed type instead
+  // of falling through to the native host angle (P1.1). *-primary => 0,
+  // *-secondary => 180; keep in sync with goapi's
+  // config.OrientationAngleForType().
+  if (auto v = MaskConfig::GetString("screen:orientation")) {
+    bool secondary = v->size() >= 10 && v->compare(v->size() - 10, 10, "-secondary") == 0;
+    return secondary ? 180 : 0;
+  }
   Document* doc = GetResponsibleDocument();
   BrowsingContext* bc = doc ? doc->GetBrowsingContext() : nullptr;
   if (!bc) {
```

- [ ] **Step 2: gate** — `FETCH="curl -fsSL" bash scripts/rehearse-patch.sh screen-orientation-spoofing.patch` → `rejects=0 skipped=0 wrongpath=0 fuzz=0 max|offset|<=2`, exit 0. If the hunk fails to apply, the `@@` new-count is the first thing to recheck (count every context + `+` line under the header by hand).

- [ ] **Step 3: identifier check**:
```bash
T=.rehearse/screen-orientation-spoofing.patch/tree
grep -n -A12 "uint16_t ScreenOrientation::GetAngle" "$T"/dom/base/ScreenOrientation.cpp
```
Expected: both the `screen:orientationAngle` branch and the new `screen:orientation` derive-from-type branch appear inside `GetAngle`, in that order, before the native `Document* doc = GetResponsibleDocument();` fallback.

- [ ] **Step 4: commit**
```bash
git add patches/screen-orientation-spoofing.patch
git commit -m "fix(patches): derive orientation angle from spoofed type when angle key absent"
```

---

### Task 4: Media-codec — goapi regen guard (RED → GREEN)

The regen guard at `generator.go:103` only regenerates the codec maps when **both** are empty (`&&`). A caller (or a partial hand-built `Config`) that sets only one of `MediaCanPlayType`/`MediaDecodingInfo` leaves the other empty — the empty side falls through to the real host decoder in the C++ layer, a one-sided leak. Fix: regenerate (both maps, wholesale) when **either** is empty (`||`).

**Files:** Modify `goapi/pkg/fingerprint/generator.go:100-105`, `goapi/pkg/fingerprint/fingerprint_test.go`

- [ ] **Step 1 (RED): add a one-sided case to `TestMediaCodecProfile`** (currently lines 86-122) — append after the existing "User-supplied codec config must not be clobbered" block (which covers the *both-sided* case and must keep passing):
```go
	// One-sided user config (only canPlayType set) must be backfilled
	// coherently, not left with an empty decodingInfo (P1.2 bug: the old
	// `&&` guard only regenerated when BOTH maps were empty).
	oneSided := &config.Config{
		MediaCanPlayType: map[string]string{"hvc1": "maybe"}, // arbitrary pre-existing value
	}
	if err := Generate(oneSided, Options{OS: "linux", Rand: rand.New(rand.NewPCG(9, 10))}); err != nil {
		t.Fatal(err)
	}
	if len(oneSided.MediaDecodingInfo) == 0 {
		t.Fatal("one-sided canPlayType map left decodingInfo empty")
	}
	for k, cp := range oneSided.MediaCanPlayType {
		dec, ok := oneSided.MediaDecodingInfo[k]
		if !ok {
			t.Errorf("codec %q missing from decodingInfo after regen", k)
			continue
		}
		if (cp != "") != dec.Supported {
			t.Errorf("codec %q: canPlayType=%q disagrees with decodingInfo.Supported=%v", k, cp, dec.Supported)
		}
	}
```

- [ ] **Step 2: confirm RED** — `cd goapi && go test ./pkg/fingerprint/... -run TestMediaCodecProfile -v` → fails: `one-sided canPlayType map left decodingInfo empty`.

- [ ] **Step 3 (GREEN): fix the guard** — `generator.go:103`, change:
```go
	if len(cfg.MediaCanPlayType) == 0 && len(cfg.MediaDecodingInfo) == 0 {
```
to:
```go
	if len(cfg.MediaCanPlayType) == 0 || len(cfg.MediaDecodingInfo) == 0 {
```
Update the comment immediately above (currently "keep canPlayType / isTypeSupported / decodingInfo coherent with the spoofed OS instead of leaking the host's real decoder support.") by appending: `A one-sided map (only one of the two set) is treated as absent and both are regenerated — a partial codec map is more dangerous than overwriting it with a coherent default.`

- [ ] **Step 4: confirm GREEN** — `cd goapi && go test ./pkg/fingerprint/... -run TestMediaCodecProfile -v` → all subtests (including the pre-existing both-sided "not clobbered" case) pass. The both-sided case stays green because `len(canPlayType)==0` is `false` and `len(decodingInfo)==0` is `false`, so the `||` is `false` and regen does not fire — user data with both sides set is still respected.

- [ ] **Step 5: commit**
```bash
git add goapi/pkg/fingerprint/generator.go goapi/pkg/fingerprint/fingerprint_test.go
git commit -m "fix(goapi): regenerate media-codec maps when EITHER side is empty, not only when both are"
```

---

### Task 5: Media-codec — C++ chokepoint (`MaskConfig.hpp` unified table)

`GetMediaCanPlayType` and `GetMediaDecodingInfo` currently run two **independent** loops over two separate JSON objects (`mediaCapabilities:canPlayType`, `mediaCapabilities:decodingInfo`). Task 4 stops goapi from *producing* a one-sided map, but the chokepoint itself has no defense against one arriving anyway (pythonlib, a hand-authored raw `CAMOU_CONFIG`, or a future goapi bug). Fix: back both getters with **one** merged per-codec-pattern table built once, deriving the absent side from the present one so the two APIs cannot disagree.

**Files:** Modify `additions/camoucfg/MaskConfig.hpp:127-181` (the "Media codec spoofing" section)

- [ ] **Step 1: add the missing include** — this file currently has no `#include <map>` (it has `<vector>`, `<algorithm>`, etc. — see the include block at the top). Add it, e.g. right after `#include <vector>`:
```cpp
#include <vector>
#include <map>
#include <algorithm>
```

- [ ] **Step 2: replace the two independent lookups with one merged table.** Replace the entire block from the `// --- Media codec spoofing ...` comment through the end of `GetMediaDecodingInfo` (current lines 127-181) with:
```cpp
// --- Media codec spoofing (device-faking target #6) -----------------------
// A cross-OS profile must not leak the host's real decoder support through
// canPlayType() / MediaSource.isTypeSupported() / mediaCapabilities
// .decodingInfo(). GetMediaCanPlayType and GetMediaDecodingInfo used to run
// two independent lookups over two separate config keys
// ("mediaCapabilities:canPlayType" / "mediaCapabilities:decodingInfo"); a
// one-sided config (e.g. a hand-authored raw CAMOU_CONFIG, or a producer bug
// upstream of this header) could make them disagree. They now share one
// merged table (built once, below) so the two APIs read the same entry and
// physically cannot answer two different queries inconsistently — a pattern
// present on only one side has its other side derived here (canPlayType !=
// "" <=> decodingInfo.supported). goapi's own regen guard
// (goapi/pkg/fingerprint/generator.go) is the primary defense for the goapi
// producer path; this table is the chokepoint defense for every path.
// Matching is by codec substring (e.g. "hvc1") found in the queried type,
// case-insensitively; first matching entry wins, using std::map's
// alphabetical key order (deterministic, same first-match semantics as the
// original two independent std::map-backed nlohmann::json loops).
struct MediaCodecEntry {
  std::optional<std::string> canPlayType;  // "probably" | "maybe" | ""
  std::optional<bool> supported;
  bool smooth = true;
  bool powerEfficient = false;
};

inline const std::map<std::string, MediaCodecEntry>& GetMediaCodecTable() {
  static std::map<std::string, MediaCodecEntry> table;
  static std::once_flag initFlag;
  std::call_once(initFlag, []() {
    const auto& data = GetJson();
    auto lower = [](std::string s) {
      std::transform(s.begin(), s.end(), s.begin(),
                     [](unsigned char c) { return std::tolower(c); });
      return s;
    };
    if (auto it = data.find("mediaCapabilities:canPlayType");
        it != data.end() && it->is_object()) {
      for (const auto& [pattern, val] : it->items()) {
        if (!val.is_string() || pattern.empty()) continue;
        table[lower(pattern)].canPlayType = val.get<std::string>();
      }
    }
    if (auto it = data.find("mediaCapabilities:decodingInfo");
        it != data.end() && it->is_object()) {
      for (const auto& [pattern, val] : it->items()) {
        if (!val.is_object() || pattern.empty()) continue;
        auto& e = table[lower(pattern)];
        e.supported = val.value("supported", true);
        e.smooth = val.value("smooth", true);
        e.powerEfficient = val.value("powerEfficient", false);
      }
    }
    // Derive the absent side so the two APIs cannot disagree.
    for (auto& [pattern, e] : table) {
      if (!e.canPlayType && e.supported) {
        e.canPlayType = *e.supported ? "probably" : "";
      }
      if (!e.supported && e.canPlayType) {
        e.supported = !e.canPlayType->empty();
      }
    }
  });
  return table;
}

// Returns "probably" | "maybe" | "" for canPlayType()/isTypeSupported(), or
// nullopt to fall through to the real decoder query.
inline std::optional<std::string> GetMediaCanPlayType(const std::string& type) {
  const auto& table = GetMediaCodecTable();
  if (table.empty()) return std::nullopt;
  std::string lower = type;
  std::transform(lower.begin(), lower.end(), lower.begin(),
                 [](unsigned char c) { return std::tolower(c); });
  for (const auto& [pattern, e] : table) {
    if (!pattern.empty() && e.canPlayType && lower.find(pattern) != std::string::npos)
      return *e.canPlayType;
  }
  return std::nullopt;
}

// Fills a spoofed mediaCapabilities.decodingInfo() result via out-params (kept
// dom-agnostic so this header has no Gecko dependency; the caller fills the
// dom struct). Returns true when the type matched a config entry.
inline bool GetMediaDecodingInfo(const std::string& type, bool& outSupported,
                                 bool& outSmooth, bool& outPowerEfficient) {
  const auto& table = GetMediaCodecTable();
  if (table.empty()) return false;
  std::string lower = type;
  std::transform(lower.begin(), lower.end(), lower.begin(),
                 [](unsigned char c) { return std::tolower(c); });
  for (const auto& [pattern, e] : table) {
    if (pattern.empty() || !e.supported || lower.find(pattern) == std::string::npos) continue;
    outSupported = *e.supported;
    outSmooth = e.smooth;
    outPowerEfficient = e.powerEfficient;
    return true;
  }
  return false;
}
```
Note the function **signatures are unchanged** (`GetMediaCanPlayType(const std::string&) -> std::optional<std::string>`, `GetMediaDecodingInfo(const std::string&, bool&, bool&, bool&) -> bool`) — `patches/media-codec-spoofing.patch`'s three call sites need no edits.

- [ ] **Step 3: structural self-check** (no local compile path for this header — see Global Constraints; this is best-effort review, the real proof is Task 7's CI build):
```bash
grep -n "GetMediaCanPlayType\|GetMediaDecodingInfo\|GetMediaCodecTable\|#include <map>" additions/camoucfg/MaskConfig.hpp
```
Confirm: the include is present; both public functions still exist with matching signatures; `GetMediaCodecTable` is defined above both and used by both.

- [ ] **Step 4: commit**
```bash
git add additions/camoucfg/MaskConfig.hpp
git commit -m "fix(camoucfg): back canPlayType/decodingInfo with one merged per-codec table"
```

---

### Task 6: Cross-cutting coherence test + wire `Validate()` into `Launch`

This is the "coherence test" the spec names for items 1 and 2 (see Design decision #2 above): it reuses `Config.Validate()` (Task 1) rather than re-implementing the iff-checks. It is a property/regression test — expected to already pass once Tasks 2–5 land, not RED-first; run it before landing this task's own new code to confirm that expectation, then treat any future failure as a real regression.

**Files:** Modify `goapi/pkg/fingerprint/coherence_test.go`, `goapi/launch.go`; create `goapi/launch_validate_test.go`

- [ ] **Step 1: add `TestGeneratedConfigValidates`** to `coherence_test.go`:
```go
// TestGeneratedConfigValidates guards P1: every OS x seed combination the
// generator can produce must pass config.Validate() — the orientation
// (type,angle,aspect) and media-codec coherence rules the C++ chokepoint
// also enforces (screen-orientation-spoofing.patch, MaskConfig.hpp). This
// is a property/regression test, not RED-first: it is expected to already
// pass once the generator fixes (angle derivation, regen-guard OR-fix) are
// in place — it exists to catch a *future* generator change that silently
// reintroduces incoherent defaults.
func TestGeneratedConfigValidates(t *testing.T) {
	for _, os := range []string{"windows", "macos", "linux"} {
		for seed := uint64(0); seed < 8; seed++ {
			cfg := &config.Config{}
			if err := Generate(cfg, Options{OS: os, Rand: rand.New(rand.NewPCG(seed, seed+1))}); err != nil {
				t.Fatalf("%s seed=%d: Generate: %v", os, seed, err)
			}
			if err := cfg.Validate(); err != nil {
				t.Errorf("%s seed=%d: generated config fails Validate(): %v", os, seed, err)
			}
		}
	}
}
```
This needs `"math/rand/v2"` and `"github.com/lang315/camoufox/goapi/pkg/config"` imports in `coherence_test.go` — add them (the file currently imports only `"strings"` and `"testing"`).

- [ ] **Step 2: run it** — `cd goapi && go test ./pkg/fingerprint/... -run TestGeneratedConfigValidates -v` → passes (confirms the design-decision-#2 claim above; if it fails, Tasks 2–5 are incomplete — stop and fix those first, do not weaken this test).

- [ ] **Step 3 (RED): write `launch_validate_test.go`** — proves `Launch` rejects an incoherent config *before* attempting to spawn a process, without needing `CAMOUFOX_BIN`:
```go
package camoufox_test

import (
	"context"
	"strings"
	"testing"

	camoufox "github.com/lang315/camoufox/goapi"
	"github.com/lang315/camoufox/goapi/pkg/config"
)

// TestLaunchRejectsIncoherentConfig guards P1.4: Config.Validate() is wired
// into Launch and fails fast, before any process-spawn attempt (proven by
// using a nonexistent executable path — if Validate() ran, the returned
// error is the validate error, not an exec/spawn error).
func TestLaunchRejectsIncoherentConfig(t *testing.T) {
	bad := &config.Config{
		ScreenOrientation:      "landscape-primary",
		ScreenOrientationAngle: config.Uint32(180), // illegal pair
	}
	_, err := camoufox.Launch(context.Background(),
		camoufox.WithExecutablePath("/nonexistent/camoufox-bin"),
		camoufox.WithConfig(bad),
		camoufox.WithNoFingerprint(),
	)
	if err == nil {
		t.Fatal("expected an error for an incoherent config")
	}
	if !strings.Contains(err.Error(), "orientation") {
		t.Errorf("error = %q, want it to mention the orientation coherence failure (got a different error — did Validate() run before the exec attempt?)", err.Error())
	}
}
```

- [ ] **Step 4: confirm RED** — `cd goapi && go test . -run TestLaunchRejectsIncoherentConfig -v` → fails: either no error (Launch proceeds to a later error, or the current error is an exec/"no such file" error, not one mentioning "orientation").

- [ ] **Step 5 (GREEN): wire `Validate()` into `launch.go`** — immediately before the existing `emitLeakWarnings` call (currently `launch.go:108-110`):
```go
	// Detection-risk warnings (mirrors pythonlib LeakWarning). Evaluated
	// after geo resolution + fingerprint so cfg reflects the final config.
	emitLeakWarnings(os.Stderr, leakWarnings(cfg, lc.proxy != nil, lc.geoIPEnabled))
```
becomes:
```go
	// Fail-fast dev guard: reject an internally incoherent config before
	// spawning the browser. Non-authoritative (see Config.Validate doc) —
	// callers that bypass Launch (pythonlib, raw CAMOU_CONFIG) are not
	// covered.
	if err := cfg.Validate(); err != nil {
		return nil, fmt.Errorf("camoufox: %w", err)
	}

	// Detection-risk warnings (mirrors pythonlib LeakWarning). Evaluated
	// after geo resolution + fingerprint so cfg reflects the final config.
	emitLeakWarnings(os.Stderr, leakWarnings(cfg, lc.proxy != nil, lc.geoIPEnabled))
```
(`fmt` is already imported in `launch.go`.) This runs on the **final** `cfg` — after fingerprint generation (Tasks 2/4's now-coherent defaults) — for every `Launch` call, whether or not `WithNoFingerprint()`/`WithConfig()` was used.

- [ ] **Step 6: confirm GREEN** — `cd goapi && go test . -run TestLaunchRejectsIncoherentConfig -v` → passes. Also run the full package (`go test ./...`) to confirm `runtime_spoof_test.go` (the only other `WithConfig` caller in the repo — its `cfg` is built via `fingerprint.Generate`, so it is coherent) and all other `Launch`-calling tests still pass (they are `CAMOUFOX_BIN`-gated and skip without a binary, but must still compile and not error before the skip).

- [ ] **Step 7: commit**
```bash
git add goapi/pkg/fingerprint/coherence_test.go goapi/launch.go goapi/launch_validate_test.go
git commit -m "test(goapi): coherence regression test + wire Config.Validate() into Launch (fail-fast)"
```

---

### Task 7: Track A CI gate

**Files:** none (dispatch + evidence)

- [ ] **Step 1: local gate** — from repo root:
```bash
FETCH="curl -fsSL" bash scripts/rehearse-patch.sh screen-orientation-spoofing.patch
cd goapi && go vet ./... && go build ./... && go test -timeout 5m ./...
```
All must pass: rehearsal all-zero/exit-0, `go vet`/`go build` clean, `go test` green (including `TestValidateOrientation`, `TestValidateMediaCodecs`, `TestScreenOrientation`, `TestMediaCodecProfile`, `TestGeneratedConfigValidates`, `TestLaunchRejectsIncoherentConfig`).

- [ ] **Step 2: push + dispatch CI build** (proves `additions/camoucfg/MaskConfig.hpp`'s Task 5 changes and the Task 3 patch edit compile — the only proof available for the C++ side in this plan):
```bash
git push -u origin spec/spoofing-patch-hardening
gh workflow run "Build and Release" --repo lang315/camoufox -f build_target=linux-x86_64 --ref spec/spoofing-patch-hardening
```

- [ ] **Step 3: confirm clean apply + successful build**
```bash
gh run view <id> --repo lang315/camoufox --log | grep -iE "FAILED|\.rej|can.?t find file|ignored" || echo "clean apply"
gh run view <id> --repo lang315/camoufox --exit-status
```
Expected: `clean apply`; workflow exit status 0. A build failure at this point means a name/type in Task 5's `MaskConfig.hpp` rewrite doesn't match Gecko's actual `nlohmann::json`/STL usage in this codebase — fix and re-dispatch.

- [ ] **Step 4: build-tester + service-tester** — download the built binary and run both suites (no new collector is required for Track A — item 3's system-color collector is Track B's deliverable; Track A's runtime proof is the successful compile plus the existing build-tester suite continuing to pass unchanged):
```bash
gh run download <id> --repo lang315/camoufox --name CamoufoxBuilds-linux-x86_64 -D /tmp/cf-p1a
cd build-tester && python scripts/run_tests.py /tmp/cf-p1a/<bin>
cd ../service-tester && python run_tests.py
```
Capture pass output from both.

- [ ] **Step 5: PR**
```bash
gh pr create --title "P1: orientation angle derivation + unified media-codec table + Config.Validate()" --body "$(cat <<'EOF'
## Summary
- screen.orientation.angle now derives from the spoofed type (*-primary=>0, *-secondary=>180) instead of leaking the native host angle when screen:orientationAngle is absent; both config keys retained.
- MaskConfig::GetMediaCanPlayType / GetMediaDecodingInfo now share one merged per-codec table so they cannot disagree, independent of the producer.
- goapi generator's media-codec regen guard fixed (|| instead of &&) so a one-sided caller-supplied map is backfilled coherently instead of leaking the host decoder on the empty side.
- New Config.Validate() error (non-authoritative dev guard) wired into Launch: rejects illegal (type,angle) pairs, orientation/aspect mismatches, one-sided or disagreeing media maps.

## Test plan
- [x] go vet / go build / go test ./... (goapi) — attach output
- [x] scripts/rehearse-patch.sh screen-orientation-spoofing.patch — all-zero, exit 0
- [x] CI Linux build — clean apply + green
- [x] build-tester — attach pass output
- [x] service-tester — attach pass output

Closes #NA
EOF
)"
```

---

## Track B

### Task 8: New system-color build-tester collector (scaffolding, precedes the patch)

Written against current (unpatched) behavior first, so it establishes a red baseline once the binary from Task 9 doesn't exist yet — this task alone does not require a new CI build; it lands as dead code exercised once Task 10 builds a binary with Task 9's patch.

**Files:** Modify `build-tester/src/lib/types.ts`, `build-tester/src/lib/checks/collectors.ts`, `build-tester/src/lib/checks/index.ts`, `build-tester/scripts/grading.py`, `build-tester/scripts/runner.py`

**Interfaces:** `checkSystemColorScheme(): Promise<SystemColorResult>`, `SystemColorResult = { passed:boolean; skipped:boolean; expected:string; colors:Record<string,string>; detail:string }`.

- [ ] **Step 1: type** (`types.ts`, alongside the existing `WebRTCLinkLocalResult`/`CanvasPerturbationResult` and the `TestResults` interface):
```typescript
export interface SystemColorResult {
  passed: boolean;
  skipped: boolean;
  expected: string;
  colors: Record<string, string>;
  detail: string;
}
```
Add `systemColorScheme: SystemColorResult;` to `TestResults`.

- [ ] **Step 2: collector** (`collectors.ts`) — reads Gecko's *repainted* system colors via `getComputedStyle`, independent of the `matchMedia("(prefers-color-scheme: ...)")` check `extended.ts` already does (that only proves the media-query answer is spoofed, not that system colors/form controls repaint to match it — the P1.3 gap):
```typescript
import type { SystemColorResult } from "../types";

function luminance(rgb: string): number | null {
  const m = rgb.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
  if (!m) return null;
  const [r, g, b] = [1, 2, 3].map((i) => Number(m[i]) / 255);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export async function checkSystemColorScheme(): Promise<SystemColorResult> {
  const expected = (window as any).__expectedColorScheme__ as "dark" | "light" | undefined;
  const res: SystemColorResult = { passed: false, skipped: false, expected: expected ?? "", colors: {}, detail: "" };
  if (!expected) { res.skipped = true; res.passed = true; res.detail = "skipped (no __expectedColorScheme__)"; return res; }
  const el = document.createElement("div");
  el.style.cssText = "color: CanvasText; background-color: Canvas; border-color: AccentColor; position:absolute; visibility:hidden;";
  document.body.appendChild(el);
  const cs = getComputedStyle(el);
  const canvas = cs.backgroundColor, canvasText = cs.color, accent = cs.borderColor;
  document.body.removeChild(el);
  res.colors = { Canvas: canvas, CanvasText: canvasText, AccentColor: accent };
  const lumCanvas = luminance(canvas), lumText = luminance(canvasText);
  if (lumCanvas === null || lumText === null) {
    res.detail = "could not parse computed system colors: " + JSON.stringify(res.colors);
    return res;
  }
  const wantDark = expected === "dark";
  const canvasOk = wantDark ? lumCanvas < 0.5 : lumCanvas >= 0.5;
  const textOk = wantDark ? lumText >= 0.5 : lumText < 0.5;
  res.passed = canvasOk && textOk;
  res.detail = res.passed
    ? `Canvas/CanvasText contrast matches scheme=${expected}`
    : `FAIL scheme=${expected} Canvas=${canvas}(lum=${lumCanvas.toFixed(2)}) CanvasText=${canvasText}(lum=${lumText.toFixed(2)})`;
  return res;
}
```
Interpretation note (stating the assumption explicitly, per the spec's shorthand "assert CanvasText/AccentColor render dark when scheme=dark"): for readable contrast, a dark scheme means the `Canvas` *background* is dark and `CanvasText` *foreground* is light — this collector checks exactly that pairing (not that `CanvasText` itself is a dark color, which would be illegible). `AccentColor` is captured in `colors` for evidence/debugging but is not asserted on numerically — Gecko does not constrain accent-color luminance by scheme (it can be any OS-chosen hue), so no pass/fail rule is applied to it here.

- [ ] **Step 3: wire** (`index.ts`) — alongside the existing `checkWebRTCLinkLocal`/`checkCanvasPerturbation` imports and `onPhaseComplete` calls:
```typescript
const { checkSystemColorScheme } = await import("./collectors");
const systemColorScheme = await checkSystemColorScheme();
onPhaseComplete?.({ phase: "systemColorScheme" });
```
and add `systemColorScheme,` to the returned result object (alongside `webrtcLinkLocal, canvasPerturbation,`).

- [ ] **Step 4: grade** (`grading.py`, after the `canvasPerturbation`/`webrtcLinkLocal` block added in P0 Task 3):
```python
    total_checks += 1
    if results.get("systemColorScheme", {}).get("passed"):
        pass_count += 1
```

- [ ] **Step 5: inject the expected scheme for the test profile** (`runner.py`) — mirror the existing `canvas:seed`/`webrtc:localipv4` injection precedent (per-context site around the existing `canvas:seed` setdefault, and the global-profile site around the existing `__expectedWebRTC__` injection):
```python
p["camouConfig"]["cssMedia:prefersColorScheme"] = "dark"
p["initScript"] += "\ntry { window.__expectedColorScheme__ = 'dark'; } catch (e) {}"
```
(per-context site) and
```python
"try { window.__expectedColorScheme__ = 'dark'; } catch(e) {}"
```
appended to the global-profile env-injected init string (alongside the existing `__canvasSeedSet__`/`__expectedWebRTC__` lines). Use the same profile the JSON dump targets (the one already carrying `canvas:seed`/`__expectedWebRTC__`), so one profile run exercises all three P0/P1 collectors together.

- [ ] **Step 6: build** — `cd build-tester && npm install && npm run build` → no TS errors.

- [ ] **Step 7: commit**
```bash
git add build-tester/src/lib/types.ts build-tester/src/lib/checks/collectors.ts build-tester/src/lib/checks/index.ts build-tester/scripts/grading.py build-tester/scripts/runner.py
git commit -m "test(build-tester): system-color scheme collector (Canvas/CanvasText contrast vs spoofed scheme)"
```

---

### Task 9: `patches/system-color-spoofing.patch` — new PreferenceSheet C++ patch

**This is new patch content, not an edit to an existing patch — treat it with the same discipline P0 applied to the fabricated canvas hunks: fetch and read the real FF152.0.4 source before writing a single hunk. Do not write hunks against remembered/assumed Firefox internals; P0's r3 revision exists specifically because that shortcut produced unappliable, undefined-symbol-causing patches.** No anchor table is provided here (unlike P0 Task 7's canvas table, which a prior fetch had already verified) — Step 1 below **is** the anchor-discovery work.

**Files:** Create `patches/system-color-spoofing.patch`

- [ ] **Step 1: fetch + study the real target.** Likely candidates (verify, do not assume): `layout/base/PreferenceSheet.cpp` and `layout/base/PreferenceSheet.h` at `FIREFOX_152_0_4_RELEASE`. Confirm:
  - Where Gecko resolves the *content* prefers-color-scheme (`PreferenceSheet::ContentPrefs()` / `PreferenceSheet::PrefsFor(...)`, already referenced by `patches/css-media-spoofing.patch:49` — that patch's context lines are a real, already-applied anchor, useful as a cross-check that the file/API names you find match what's already proven to compile).
  - Where/how system colors (`Canvas`, `CanvasText`, `AccentColor`, plus scrollbar and form-control colors) are populated per color-scheme (likely a per-scheme `Prefs`/color-struct built from `LookAndFeel::Color(...)` calls, keyed by `mozilla::LookAndFeel::ColorID`, or similar — **confirm the actual struct/field names in the fetched source**, do not guess).
  - The precise insertion point: after Gecko computes native OS colors for a scheme, before the values are cached/returned, so a MaskConfig override can win without disturbing surrounding control flow.

- [ ] **Step 2: write the hunk(s)** against the fetched, real source. Read `MaskConfig::GetString("cssMedia:prefersColorScheme")` (the existing key — no new config surface); when present, override the resolved `Canvas`/`CanvasText`/`AccentColor` (+ scrollbar/form-control) colors for the *matching* scheme's struct with fixed, readable-contrast values (dark scheme: dark `Canvas`, light `CanvasText`; light scheme: the reverse) — consistent with what Task 8's collector checks. Add the `#include "MaskConfig.hpp"` + `LOCAL_INCLUDES += ["/camoucfg"]` in the target's `moz.build`, matching the pattern in every other patch (`patches/screen-orientation-spoofing.patch`, `patches/media-codec-spoofing.patch`). Delete any placeholder/TODO text before committing — none should exist if Step 1 was done properly.

- [ ] **Step 3: gate** — `FETCH="curl -fsSL" bash scripts/rehearse-patch.sh system-color-spoofing.patch` → `rejects=0 skipped=0 wrongpath=0 fuzz=0 max|offset|<=2`, exit 0. Iterate Steps 1–2 until clean — a `wrongpath` result means the guessed file path was wrong; re-derive it from the fetched directory listing, don't retry the same wrong path with different content.

- [ ] **Step 4: identifier check**:
```bash
T=.rehearse/system-color-spoofing.patch/tree
grep -n "MaskConfig::GetString(\"cssMedia:prefersColorScheme\")" "$T"/layout/base/PreferenceSheet.cpp
grep -n "camoucfg" "$T"/layout/base/moz.build
```
(paths per whatever Step 1 actually confirmed — update this grep to match).

- [ ] **Step 5: commit**
```bash
git add patches/system-color-spoofing.patch
git commit -m "feat(patches): system-color spoofing — repaint Canvas/CanvasText/AccentColor to match prefers-color-scheme"
```

---

### Task 10: Track B CI gate

**Files:** none (dispatch + evidence)

- [ ] **Step 1: push + dispatch**
```bash
git push -u origin <track-b-branch>
gh workflow run "Build and Release" --repo lang315/camoufox -f build_target=linux-x86_64 --ref <track-b-branch>
```

- [ ] **Step 2: confirm clean apply + successful build** (same pattern as Task 7 Step 3).

- [ ] **Step 3: build-tester assertion**
```bash
gh run download <id> --repo lang315/camoufox --name CamoufoxBuilds-linux-x86_64 -D /tmp/cf-p1b
cd build-tester && python scripts/run_tests.py /tmp/cf-p1b/<bin> --json /tmp/p1b.json
python - <<'PY'
import json
r = json.load(open("/tmp/p1b.json"))
prof = [p for p in r["profiles"] if "systemColorScheme" in p.get("results", {})]
assert prof, "no profile ran the systemColorScheme collector"
res = prof[0]["results"]["systemColorScheme"]
assert res["passed"] and not res.get("skipped"), res   # must be a real pass, not skipped
print("P1.3 system-color PASS")
PY
```

- [ ] **Step 4: service-tester** — `cd service-tester && python run_tests.py`; capture pass output.

- [ ] **Step 5: PR**
```bash
gh pr create --title "P1.3: system-color spoofing (Canvas/CanvasText/AccentColor <-> prefers-color-scheme)" --body "$(cat <<'EOF'
## Summary
- New patches/system-color-spoofing.patch: Gecko's repainted system colors (Canvas/CanvasText/AccentColor + scrollbars/form controls) now follow the spoofed cssMedia:prefersColorScheme, closing a leak where matchMedia() was spoofed but native form-control/system-color rendering still leaked the host OS theme.
- No new CAMOU_CONFIG key — reuses the existing cssMedia:prefersColorScheme key already read by css-media-spoofing.patch.

## Test plan
- [x] scripts/rehearse-patch.sh system-color-spoofing.patch — all-zero, exit 0
- [x] CI Linux build — clean apply + green
- [x] build-tester systemColorScheme collector — passed=true, skipped=false (attach /tmp/p1b.json excerpt)
- [x] service-tester — attach pass output

Closes #NB
EOF
)"
```

---

## Self-Review

**Spec coverage (P1 slice):** orientation chokepoint derive-from-type, both keys retained → Task 3; generator angle fix (0/180 for primary/secondary) → Task 2; orientation coherence test → Task 6 (via `Validate()` reuse, design decision #2); media-codec chokepoint unified table → Task 5; generator regen-guard `&&`→`||` fix → Task 4; media-codec coherence test (canPlayType != "" <=> decodingInfo.supported) → Tasks 1 (unit) + 6 (property); new system-color PreferenceSheet patch, own PR, P0 rehearsal method → Tasks 8–10; system-color collector asserting Canvas/CanvasText contrast → Task 8; `Config.Validate()` fail-fast, non-authoritative, wired into `leakWarnings`/`Launch` flow → Tasks 1, 6. P2–P4 excluded.

**Design decisions surfaced (not silently picked):** (1) mapping logic centralized in `pkg/config` since `fingerprint` already depends on `config`, with an explicit "C++ can't share this, keep in sync by hand" callout as a residual risk, not a silent gap. (2) the item-1/2 coherence test reuses `Validate()` rather than duplicating iff-logic — flagged as property-style, not RED-first, so it isn't mistaken for a failing-first test. (3) the spec's literal "CanvasText/AccentColor render dark when scheme=dark" is interpreted as a Canvas-dark/CanvasText-light contrast pair (physically correct for readability) rather than both rendering dark — stated explicitly in Task 8 Step 2 rather than guessed silently.

**Placeholder scan:** Tasks 1–8 write concrete, complete code against files read in full during planning (`generator.go`, `config.go`, `MaskConfig.hpp`, `warnings.go`, `launch.go`, `screen-orientation-spoofing.patch`, `coherence_test.go`, `fingerprint_test.go`, `build-tester/src/lib/types.ts` and sibling collectors) — no `<verify>`/TBD placeholders. Task 9 is the one deliberate exception: it names no anchor table because none has been verified yet (unlike P0's canvas task, which had a prior fetch behind it) — Task 9 Step 1 is explicitly scoped as the anchor-discovery step, and Steps 2–4 are gated exactly like P0's re-anchor tasks so an unverified guess cannot silently ship.

**Type consistency:** `SystemColorResult` (Task 8) matches the shape asserted in Task 10's JSON check (`passed`, `skipped`, `colors`); `Config.Validate()` (Task 1) is the single implementation consumed identically by Task 6's property test and Task 6's `Launch` wiring; `OrientationAngleForType`/`AspectMatchesOrientation` (Task 1) are consumed identically by Task 2's generator default and by `Validate()` itself.

**Known limitations (out of scope for P1, not gaps in this plan):** mobile/portrait-natural orientation (90°/270° angles) needs a natural-orientation field not modeled here — explicitly deferred to a future phase per the spec; Track A ships without a new *runtime* build-tester collector for orientation/media-codec (the spec's P1 exit criteria names a build-tester collector only for item 3/system-color) — Track A's C++ proof is compile-only (Task 7) plus the Go-side coherence tests, a real but narrower guarantee than Track B gets; `forced-colors`/`prefers-contrast` coherence with the new system-color repaint is explicitly P2 scope per the spec (schedule with P1's css-media/system-color edits to avoid a rebase) — not addressed here.

**Residual risk to flag at execution:** the Go/C++ orientation-angle mapping (Task 1's `OrientationAngleForType` vs Task 3's inline C++ mapping) is duplicated logic with no compiler or test to catch drift across the two languages — if this mapping ever needs a third value (e.g. when mobile/portrait-natural support lands), both sides must be updated together; consider a generated-constant or a shared test fixture at that point. Task 9 (system-color patch) is the one task in this plan without a pre-verified anchor — budget real fetch+read time for it, do not compress Step 1.
