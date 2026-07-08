# Spoofing-patch hardening — P2 (coverage gaps) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Revision:** r1 — grounded in a direct fetch of real FF152.0.4 source
(`hg.mozilla.org/.../FIREFOX_152_0_4_RELEASE`): `layout/style/nsMediaFeatures.cpp`,
`servo/components/style/gecko/media_features.rs`, `servo/components/style/device/{mod,gecko}.rs`,
`layout/base/nsPresContext.cpp`, `mfbt/HashFunctions.h`. Four findings reshape the spec's literal
task list — real anchors, not assumptions:

1. **`update` has no per-host backing at all.** `eval_update`
   (`media_features.rs:371-386`) is pure Rust keyed only on print-vs-screen
   (`context.device().media_type() != MediaType::print()`), calling no `Gecko_MediaFeatures_*`
   function. There is nothing to spoof — real Firefox reports `fast` regardless of host/OS. Dropped
   from Task 2's key list (documented, not silently omitted; shipping a dead key would itself look
   like a fabricated spoof).
2. **`forced-colors` has no `Gecko_MediaFeatures_*` hook either.** `eval_forced_colors`
   (`media_features.rs:276-282`) reads `context.device().forced_colors()` →
   (`servo/components/style/device/gecko.rs:387-389`) `self.pres_context().mForcedColors` — a raw
   struct-field read, not a bindgen'd C++ function call. `mForcedColors` is computed by
   `nsPresContext::UpdateForcedColors` (`layout/base/nsPresContext.cpp:737-770`) straight from
   `PreferenceSheet::PrefsFor().mUseDocumentColors`/`mUseAccessibilityTheme` — P1.3's file
   (`patches/system-color-spoofing.patch`, per the design's Architecture section), not this one.
   Task 3 schedules it there instead of writing a dead `nsMediaFeatures.cpp` hunk.
3. **The three *existing* `cssMedia:*` keys are unregistered today.** `cssMedia:colorGamut`,
   `cssMedia:dynamicRange`, `cssMedia:prefersColorScheme` already ship in `css-media-spoofing.patch`
   + `config.go`, but grep confirms they appear in **neither** `settings/camoucfg.jvv` nor
   `settings/properties.json` — `goapi/pkg/config/drift_test.go`'s own `knownConfigOnlyKeys`
   allowlist documents this as a known lag ("When properties.json is updated to register a key,
   remove it from this set"). Task 2 closes that lag for the whole `cssMedia:*` family in the same
   PR that adds the new P2 keys.
4. **`FabricateLinkLocalIPv6` has a latent bit-width bug**, independent of the spec's ask:
   `mozilla::HashGeneric` returns `HashNumber = uint32_t` (`mfbt/HashFunctions.h:58`), assigned to a
   `uint64_t h` in `patches/webrtc-ip-spoofing2.patch` — `(h>>48)`/`(h>>32)` are always zero, so
   every fabricated fe80 address today has the form `fe80::0000:0000:XXXX:YYYY`, a fixed, detectable
   pattern. Task 4 fixes this as part of the OS-policy reshape.

**Goal:** Close the four coverage gaps in the design's Phase 2, scoped to what Gecko actually lets a
C++ patch control (verified against real FF152.0.4 source, not assumed): a `dynamic-range` spoof
block (confirmed separate from `video-dynamic-range`); config-gated spoof blocks for
`prefers-contrast`/`inverted-colors`/`monochrome`/the pointer-family features; explicit,
non-fabricated scheduling for the one feature (`forced-colors`) that has no C++ hook of its own; and
an OS-policy-aware, globally-coherent fe80 link-local IID. Every new key registered in both
`settings/camoucfg.jvv` and `settings/properties.json`.

**Architecture:** Same chokepoint discipline as P0/P1 — every new spoof is an early-return inside the
existing `Gecko_MediaFeatures_*` C++ function (`layout/style/nsMediaFeatures.cpp`, patched via
`patches/css-media-spoofing.patch`) gated by `MaskConfig::GetString`/`GetBool`/`GetUint32` — no new
`MaskConfig.hpp` functions are needed; the generic accessors already exist and the current patch
already calls them inline with no wrapper (Task 2 finding). `goapi/pkg/config/config.go` gains the
typed fields; `goapi/pkg/fingerprint/generator.go` gains coherent low-entropy defaults.
`settings/camoucfg.jvv` + `settings/properties.json` gain the schema entries (both the pre-existing
lag and the new P2 keys); `goapi/pkg/config/drift_test.go`'s `knownConfigOnlyKeys` shrinks to match.
`patches/webrtc-ip-spoofing2.patch`'s `FabricateLinkLocalIPv6` is reshaped to prefer the interface
identifier of the configured global `webrtc:ipv6` for the same context, and to fall back to an
OS-policy-shaped fabrication keyed off the already-spoofed `navigator.platform`.

**Tech Stack:** Same as P0/P1 — Firefox C++ patches (unified diff, `gpatch`), Go (`goapi`), TypeScript
(`build-tester`), Python (`jsonvv` schema, `scripts/patch.py`), `scripts/rehearse-patch.sh` (built in
P0 Task 1, already merged, reused here unmodified).

## Global Constraints

- Firefox pinned: `version=152.0.4`, `release=beta.25`. Every hunk in this plan is checked against
  real source fetched from `https://hg.mozilla.org/releases/mozilla-release/raw-file/FIREFOX_152_0_4_RELEASE/<path>`
  during planning — re-fetch during implementation in case the tree drifted since.
- Reuse `scripts/rehearse-patch.sh` from P0 (already merged) for every patch edit in this plan:
  `FETCH="curl -fsSL" bash scripts/rehearse-patch.sh <patch-basename>` → exit 0 iff
  `rejects==0 skipped==0 wrongpath==0 fuzz==0 max|offset|<=2`. `css-media-spoofing.patch` and
  `webrtc-ip-spoofing2.patch` both currently pass this gate at 0/0/0/0/0 — every new hunk added here
  must keep them there.
- **jvv rejects unregistered keys at the point of use**: `jsonvv/jsonvv/validator.py:154` raises
  `UnknownProperty` for any CAMOU_CONFIG key not present in the schema handed to `JsonValidator`. A
  key that lives only in `config.go` is a silent no-op the moment jvv validation runs against it —
  exactly the bug class `goapi/pkg/config/drift_test.go`'s `TestProducerSchemaDrift` catches on the
  Go-producer side. `settings/camoucfg.jvv` has no automated drift check today, so registration there
  is verified by hand (Task 2 Step 12's jvv smoke test).
- Every new/changed `cssMedia:*` key needs: `settings/camoucfg.jvv` AND `settings/properties.json`
  AND `goapi/pkg/config/config.go`, AND (if it should ship with a default) `goapi/pkg/fingerprint/generator.go`.
  Skipping any one reproduces the exact lag this phase exists to close.
- Tooling floor: `gpatch`, bash ≥ 4, `FETCH` env for hg fetches (per P0's Global Constraints).
- Every PR: tied to a GitHub issue; **both** `build-tester/` and `service-tester/` pass; PR body
  carries concrete evidence (command output + exit status).
- Surgical: `git add` exact files, never a whole directory.

---

### Task 0: Tracking issue

**Files:** none

- [ ] **Step 1:** `gh issue create --repo lang315/camoufox --title "P2: coverage gaps — dynamic-range, color/display + form-factor media features, fe80 IID shaping" --body "Correctness/coverage — Phase 2 of the spoofing-patch hardening design. Spec: docs/superpowers/specs/2026-07-08-spoofing-patch-hardening-design.md (Phase 2). Plan: docs/superpowers/plans/2026-07-08-spoofing-patch-hardening-p2.md"` — record issue number `N`.

---

### Task 1: `dynamic-range` — confirm separate backing fn, add spoof block

Real source (`layout/style/nsMediaFeatures.cpp`, FIREFOX_152_0_4_RELEASE) confirms `dynamic-range`
and `video-dynamic-range` are **separate** C++ functions, both called from Rust
(`servo/components/style/gecko/media_features.rs:417-433`, `eval_dynamic_range`/
`eval_video_dynamic_range`) via `bindings::Gecko_MediaFeatures_DynamicRange`/
`bindings::Gecko_MediaFeatures_VideoDynamicRange` respectively. Only the latter is patched today
(`css-media-spoofing.patch`, `cssMedia:dynamicRange` key). The former is a 4-line stub, unconditional:

```cpp
StyleDynamicRange Gecko_MediaFeatures_DynamicRange(const Document* aDocument) {
  // Bug 1759772: Once HDR color is available, update each platform
  // LookAndFeel implementation to return StyleDynamicRange::High when
  // appropriate.
  return StyleDynamicRange::Standard;
}
```

Per the spec's "bounded spike — result is add-one-block or nothing": it's separate, so add one block.
**Naming note:** the existing key `cssMedia:dynamicRange` already means "video-dynamic-range" (do not
rename — that would break a shipped key); the new key for the actual `dynamic-range` feature is
`cssMedia:displayDynamicRange`.

**Files:** Modify `patches/css-media-spoofing.patch`, `goapi/pkg/config/config.go`,
`goapi/pkg/fingerprint/generator.go`, `settings/camoucfg.jvv`, `settings/properties.json`

**Interfaces:** New config key `cssMedia:displayDynamicRange` (`"standard"|"high"`), new
`config.Config.CSSDisplayDynamicRange` field.

- [ ] **Step 1:** In `patches/css-media-spoofing.patch`, add a new hunk to
  `layout/style/nsMediaFeatures.cpp` for `Gecko_MediaFeatures_DynamicRange` (adjacent, real context —
  this patch already applies at 0 fuzz, no fresh fetch needed for this function):
```diff
 StyleDynamicRange Gecko_MediaFeatures_DynamicRange(const Document* aDocument) {
+  // camoufox: spoof dynamic-range (display capability) — kept separate from
+  // video-dynamic-range's cssMedia:dynamicRange key below. (#P2.1)
+  if (auto v = MaskConfig::GetString("cssMedia:displayDynamicRange")) {
+    return *v == "high" ? StyleDynamicRange::High : StyleDynamicRange::Standard;
+  }
   // Bug 1759772: Once HDR color is available, update each platform
   // LookAndFeel implementation to return StyleDynamicRange::High when
   // appropriate.
   return StyleDynamicRange::Standard;
 }
```
- [ ] **Step 2:** `config.go` — add `CSSDisplayDynamicRange string \`json:"cssMedia:displayDynamicRange,omitempty"\``
  next to `CSSDynamicRange`, with a doc comment: distinct from `CSSDynamicRange`
  (`cssMedia:dynamicRange`), which despite the name backs `video-dynamic-range` — kept as-is for
  backward compat, do not rename.
- [ ] **Step 3:** `generator.go` — next to the existing default block (`cfg.CSSDynamicRange == ""` →
  `"standard"`, lines 113-115), add: `if cfg.CSSDisplayDynamicRange == "" { cfg.CSSDisplayDynamicRange = "standard" }`.
- [ ] **Step 4:** `settings/camoucfg.jvv` — add a new `cssMedia:*` block:
  `"cssMedia:displayDynamicRange": "str[standard, high]",` (Task 2 appends the remaining `cssMedia:*`
  keys to this same block, including registering the three pre-existing lagging keys).
- [ ] **Step 5:** `settings/properties.json` — add `{ "property": "cssMedia:displayDynamicRange", "type": "str" }`.
- [ ] **Step 6: Gate** — `FETCH="curl -fsSL" bash scripts/rehearse-patch.sh css-media-spoofing.patch` → `rejects=0 skipped=0 wrongpath=0 fuzz=0 max|offset|=0`, exit 0.
- [ ] **Step 7:** `cd goapi && go test ./pkg/config/... ./pkg/fingerprint/...` green.
- [ ] **Step 8: Commit** — `git commit -m "feat(patches): spoof dynamic-range separately from video-dynamic-range"`.

---

### Task 2: color/display + form-factor spoof blocks (prefers-contrast, inverted-colors, monochrome, pointer family) + schema registration

Real source confirms three of the four remaining color/display features **do** have a patchable
`Gecko_MediaFeatures_*` C++ function (`forced-colors` does not — Task 3):

| Feature | Backing fn (`layout/style/nsMediaFeatures.cpp`) | Native fallback reads |
|---|---|---|
| `prefers-contrast` | `Gecko_MediaFeatures_PrefersContrast` | `PreferenceSheet::PrefsFor()` — coherence-laden, see Task 3 |
| `inverted-colors` | `Gecko_MediaFeatures_InvertedColors` | `LookAndFeel::GetInt(IntID::InvertedColors)` — standalone OS toggle |
| `monochrome` | `Gecko_MediaFeatures_GetMonochromeBitsPerPixel` | `nsIPrintSettings::GetPrintInColor` (print-only; 0 on screen) |
| `pointer`/`any-pointer`/`hover`/`any-hover` | shared static `GetPointerCapabilities(aDocument, aID)`, called by `Gecko_MediaFeatures_PrimaryPointerCapabilities`/`...AllPointerCapabilities` | `LookAndFeel::GetInt(Primary\|AllPointerCapabilities)` |

`update` is dropped (Revision note 1 — no C++ hook, doesn't vary by host in real Firefox; a config key
for it would be a dead spoof, not a coverage gap).

**`screen.colorDepth` is untouched by this task.** It's already spoofed at a different site
(`patches/fingerprint-injection.patch:206`, `MaskConfig::GetUint32("screen.colorDepth")`, feeding the
DOM `Screen` interface) — unrelated to `Gecko_MediaFeatures_GetColorDepth` (the CSS `color`/
`color-index` media-feature backer, which derives its zero case from
`GetMonochromeBitsPerPixel` — the function this task patches). Spoofing `monochrome` to non-zero will
naturally zero `Gecko_MediaFeatures_GetColorDepth` too via that existing native call — that's expected
native behavior, not something to special-case or suppress.

**MaskConfig.hpp finding:** no new functions needed. `GetString`/`GetBool`/`GetUint32` already exist
and are generic; the existing `colorGamut`/`prefersColorScheme` hunks already call them inline with no
wrapper. Mirror that shape exactly — adding wrapper functions here would be unrequested abstraction
for single-call-site code.

**Files:** Modify `patches/css-media-spoofing.patch`, `goapi/pkg/config/config.go`,
`goapi/pkg/fingerprint/generator.go`, `settings/camoucfg.jvv`, `settings/properties.json`,
`goapi/pkg/config/drift_test.go`, `goapi/pkg/fingerprint/fingerprint_test.go`

**Interfaces:** New keys `cssMedia:prefersContrast` (`"no-preference"|"less"|"more"|"custom"`),
`cssMedia:invertedColors` (bool), `cssMedia:monochrome` (uint, bits-per-pixel; 0 = color),
`cssMedia:pointerCapabilities` (`"fine+hover"|"coarse"|"none"`, applied identically to
primary and all-pointer capabilities — see Step 4 note).

- [ ] **Step 1: `prefers-contrast` hunk** (fresh real context — this function is untouched by the
  current patch):
```diff
 StylePrefersContrast Gecko_MediaFeatures_PrefersContrast(
     const Document* aDocument) {
+  // camoufox: direct override. Coherence with forced-colors and P1.3's
+  // repainted system colors is scheduled, not enforced, here — see Task 3.
+  // COHERENCE (P1.3): when forced-colors is spoofed active/requested,
+  // prefers-contrast should read "more" — enforce in Config.Validate()
+  // once P1 lands it (goapi/warnings.go), not here.
+  if (auto v = MaskConfig::GetString("cssMedia:prefersContrast")) {
+    if (*v == "less") return StylePrefersContrast::Less;
+    if (*v == "more") return StylePrefersContrast::More;
+    if (*v == "custom") return StylePrefersContrast::Custom;
+    return StylePrefersContrast::NoPreference;
+  }
   if (aDocument->ShouldResistFingerprinting(RFPTarget::CSSPrefersContrast)) {
     return StylePrefersContrast::NoPreference;
   }
```
- [ ] **Step 2: `inverted-colors` hunk**:
```diff
 bool Gecko_MediaFeatures_InvertedColors(const Document* aDocument) {
+  if (auto v = MaskConfig::GetBool("cssMedia:invertedColors")) {
+    return *v;
+  }
   if (aDocument->ShouldResistFingerprinting(RFPTarget::CSSInvertedColors)) {
     return false;
   }
```
- [ ] **Step 3: `monochrome` hunk**:
```diff
 int32_t Gecko_MediaFeatures_GetMonochromeBitsPerPixel(
     const Document* aDocument) {
+  if (auto v = MaskConfig::GetUint32("cssMedia:monochrome")) {
+    return static_cast<int32_t>(*v);
+  }
   // The default bits per pixel for a monochrome device. We could propagate this
```
- [ ] **Step 4: pointer-family hunk** — one insertion point in the shared helper covers all four
  media features:
```diff
 static PointerCapabilities GetPointerCapabilities(const Document* aDocument,
                                                    LookAndFeel::IntID aID) {
   MOZ_ASSERT(aID == LookAndFeel::IntID::PrimaryPointerCapabilities ||
              aID == LookAndFeel::IntID::AllPointerCapabilities);
   MOZ_ASSERT(aDocument);
 
+  if (auto v = MaskConfig::GetString("cssMedia:pointerCapabilities")) {
+    if (*v == "coarse") return PointerCapabilities::Coarse;
+    if (*v == "none") return PointerCapabilities(0);
+    return PointerCapabilities::Fine | PointerCapabilities::Hover;
+  }
   if (dom::BrowsingContext* bc = aDocument->GetBrowsingContext()) {
```
  One key drives `pointer`, `any-pointer`, `hover`, and `any-hover` identically — both `aID` values
  hit the same override. Deliberate: Camoufox has no multi-pointer-device preset today, so
  primary == all is the coherent choice, not a shortcut to revisit later. `PointerCapabilities(0)` is
  a best guess for the "empty" spelling of this bitflags-shaped type at FF152 — verify it during the
  rehearsal's identifier check (Step 10); if the real header spells it differently
  (e.g. `PointerCapabilities::None`), use that instead.
- [ ] **Step 5:** `config.go` — add under a `// cssMedia:* (P2)` comment block: `CSSPrefersContrast string`,
  `CSSInvertedColors *bool`, `CSSMonochrome *uint32`, `CSSPointerCapabilities string` with json tags
  `cssMedia:prefersContrast`, `cssMedia:invertedColors`, `cssMedia:monochrome`,
  `cssMedia:pointerCapabilities` (all `omitempty`).
- [ ] **Step 6:** `generator.go` — extend the existing CSS-media default block (lines 107-122):
  `cfg.CSSPrefersContrast` → `"no-preference"` if empty; `cfg.CSSInvertedColors` → `config.Bool(false)`
  if nil; `cfg.CSSMonochrome` → `config.Uint32(0)` if nil; `cfg.CSSPointerCapabilities` →
  `"fine+hover"` if empty (matches the desktop-only preset set — same "desktop is the only shipped
  preset" assumption the `landscape-primary` default two blocks down already makes). No default for
  `cssMedia:forcedColors` here — Task 3 leaves it unset/native.
- [ ] **Step 7: Schema — register the new keys AND the three pre-existing unregistered ones.**
  `goapi/pkg/config/drift_test.go:20-22` documents `cssMedia:colorGamut`/`cssMedia:dynamicRange`/
  `cssMedia:prefersColorScheme` as a known lag; close it here, in the same PR that adds more
  `cssMedia:*` keys, so the family is registered in one pass. `settings/camoucfg.jvv` — extend the
  block Task 1 started:
```json
"cssMedia:colorGamut": "str[srgb, p3, rec2020]",
"cssMedia:dynamicRange": "str[standard, high]",
"cssMedia:prefersColorScheme": "str[light, dark]",
"cssMedia:prefersContrast": "str[no-preference, less, more, custom]",
"cssMedia:invertedColors": "bool",
"cssMedia:monochrome": "int[>=0]",
"cssMedia:pointerCapabilities": "str[fine+hover, coarse, none]",
```
  `settings/properties.json` — matching `{ "property": "...", "type": "str"/"bool"/"uint" }` entries
  for all seven.
- [ ] **Step 8:** `goapi/pkg/config/drift_test.go` — remove `cssMedia:colorGamut`,
  `cssMedia:dynamicRange`, `cssMedia:prefersColorScheme` from `knownConfigOnlyKeys` (now registered —
  the allowlist should shrink, not just grow). `cssMedia:forcedColors` and
  `cssMedia:displayDynamicRange` never enter `knownConfigOnlyKeys` at all — both are registered
  everywhere they're emitted, from the commit that adds them (Task 1 Step 4-5, Task 3 Step 1).
- [ ] **Step 9:** `fingerprint_test.go` — next to the existing `CSSColorGamut`/`CSSDynamicRange`
  assertions (lines 131-138): add default-value assertions for the four new fields, plus a
  "generator doesn't clobber user-set values" case mirroring lines 142-147.
- [ ] **Step 10: Gate** — `FETCH="curl -fsSL" bash scripts/rehearse-patch.sh css-media-spoofing.patch`
  → `rejects=0 skipped=0 wrongpath=0 fuzz=0 max|offset|=0`. Identifier check:
```bash
T=.rehearse/css-media-spoofing.patch/tree
grep -n "PointerCapabilities\|GetMonochromeBitsPerPixel\|PrefersContrast\|InvertedColors" "$T"/layout/style/nsMediaFeatures.cpp
```
  Expected: each `MaskConfig` block sits inside its real function; `PointerCapabilities(0)` compiles
  (or is corrected per Step 4's note) — full proof is the compile gate (Task 6).
- [ ] **Step 11:** `cd goapi && go test ./...` green, including `TestProducerSchemaDrift`.
- [ ] **Step 12: jvv smoke test** — validate a sample config carrying every new key parses, and an
  unregistered key is rejected (proves "jvv rejects unregistered keys" empirically, not by assertion):
```bash
python3 - <<'PY'
import json, sys
sys.path.insert(0, "jsonvv")
from jsonvv import JsonValidator, JvvRuntimeException
schema = json.load(open("settings/camoucfg.jvv"))
good = {"cssMedia:prefersContrast": "more", "cssMedia:invertedColors": True,
        "cssMedia:monochrome": 0, "cssMedia:pointerCapabilities": "coarse",
        "cssMedia:displayDynamicRange": "high"}
JsonValidator(schema).validate(good)
print("registered keys: OK")
try:
    JsonValidator(schema).validate({"cssMedia:notRegistered": "x"})
    print("FAIL: unregistered key was not rejected"); sys.exit(1)
except JvvRuntimeException:
    print("unregistered key correctly rejected")
PY
```
- [ ] **Step 13: Commit** —
  `git commit -m "feat(patches): spoof prefers-contrast/inverted-colors/monochrome/pointer family; register cssMedia:* schema (incl. pre-existing lag)"`.

---

### Task 3: `forced-colors` — schema now, C++ scheduled with P1.3 (coherence + rebase-risk note)

Confirmed no `Gecko_MediaFeatures_*` hook exists for `forced-colors`. `eval_forced_colors`
(`servo/components/style/gecko/media_features.rs:276-282`) reads `context.device().forced_colors()`,
which (`servo/components/style/device/gecko.rs:387-389`) returns
`self.pres_context().mForcedColors` — a raw struct-field read, no C++ function call, so there is no
chokepoint for a `nsMediaFeatures.cpp` patch to intercept. `mForcedColors` is computed by
`nsPresContext::UpdateForcedColors` (`layout/base/nsPresContext.cpp:737-770`):

```cpp
void nsPresContext::UpdateForcedColors(bool aNotify) {
  ...
  const auto& prefs = PrefSheetPrefs();
  if (!prefs.mUseDocumentColors) { return StyleForcedColors::Active; }
#ifdef XP_WIN
  if (prefs.mUseAccessibilityTheme && prefs.mIsChrome) { return StyleForcedColors::Requested; }
#endif
  return StyleForcedColors::None;
  ...
}
```

This is `PreferenceSheet` state — the exact file P1.3's (not-yet-written) `patches/system-color-spoofing.patch`
owns per the design's Architecture section. Writing a `forced-colors` patch in this phase would either
do nothing (targeting `nsMediaFeatures.cpp`, which nothing reads for this feature) or collide with
P1.3's edits to the same `PreferenceSheet`/`nsPresContext` state. Per spec Phase 2 point 3, this task
**schedules, it does not implement**.

**Files:** Modify `settings/camoucfg.jvv`, `settings/properties.json`, `goapi/pkg/config/config.go`
(schema-only — no `generator.go` default, no C++ hunk)

- [ ] **Step 1:** Register `cssMedia:forcedColors` in `settings/camoucfg.jvv`
  (`"cssMedia:forcedColors": "str[none, active, requested]",`) and `settings/properties.json`
  (`{ "property": "cssMedia:forcedColors", "type": "str" }`), and add
  `CSSForcedColors string \`json:"cssMedia:forcedColors,omitempty"\`` to `config.go` — so the key
  exists, end-to-end schema-valid, ahead of the C++ wiring. `TestProducerSchemaDrift` passes normally
  (schema entry exists) with no `knownConfigOnlyKeys` entry needed. Doc comment on the field:
  `// cssMedia:forcedColors — schema-registered, NOT yet read by any patch. Wiring is P1.3's`
  `// PreferenceSheet patch (nsPresContext::UpdateForcedColors); see the design doc, Phase 2.3.`
- [ ] **Step 2: Coherence contract (written now, wired when P1 lands).** The matching comment already
  landed at the `cssMedia:prefersContrast` hunk in Task 2 Step 1
  (`// COHERENCE (P1.3): ... enforce in Config.Validate() once P1 lands it`). Confirmed intentional:
  `config.go` has no `Validate()` today (P1 not implemented in this branch) — this task does not
  fabricate a Go test against a function that doesn't exist. The contract lives at both ends (the
  C++ hunk's comment and this task's schema comment) so whoever lands P1.3 has the rule ready instead
  of rediscovering it.
- [ ] **Step 3: Rebase-risk note for the PR body.** `patches/css-media-spoofing.patch` is edited by
  both this phase (Task 2's `prefers-contrast`/`inverted-colors`/`monochrome`/pointer hunks) and,
  later, P1.3 if it needs to touch the same file for scheme/system-color coherence. Land P2's
  `css-media-spoofing.patch` hunks and P1.3's system-color patch in sequence, not in parallel, and
  rebase whichever lands second across the other's diff — do not merge both without reviewing the
  shared hunks. State this explicitly in the P2 PR description as a heads-up for whoever picks up P1.3.
- [ ] **Step 4:** `cd goapi && go test ./pkg/config/...` green.
- [ ] **Step 5: Commit** —
  `git commit -m "docs(config): register cssMedia:forcedColors schema; defer C++ wiring + coherence to P1.3"`.

---

### Task 4: fe80 IID — shape to spoofed OS policy, match the global IPv6 IID

Current `FabricateLinkLocalIPv6` (`patches/webrtc-ip-spoofing2.patch`, landed via the B1 fix):

```cpp
std::string FabricateLinkLocalIPv6(uint32_t userContextId) {
  uint64_t h = mozilla::HashGeneric(userContextId, 0xDEADBEEFu);
  char buf[40];
  snprintf(buf, sizeof(buf), "fe80::%04x:%04x:%04x:%04x",
           static_cast<unsigned>((h >> 48) & 0xFFFF),
           static_cast<unsigned>((h >> 32) & 0xFFFF),
           static_cast<unsigned>((h >> 16) & 0xFFFF),
           static_cast<unsigned>(h & 0xFFFF));
  return std::string(buf);
}
```

Two real problems, one from the spec and one found during research (Revision note 4): **(a)** no
OS-policy shape — real hosts derive the link-local IID either via modified EUI-64 from a MAC
(`aa:bb:cc:dd:ee:ff` → `a8bb:ccff:fedd:eeff`, U/L bit flipped, `ff:fe` inserted) or via an opaque
RFC 7217-style value with no such structure; which one a real host shows correlates with its OS
(Windows has randomized interface identifiers on by default since Vista; macOS/Linux more commonly
still show EUI-64-derived link-local addresses). **(b)** `mozilla::HashGeneric` returns
`HashNumber = uint32_t` (`mfbt/HashFunctions.h:58`) — assigning it to `uint64_t h` zero-extends, so
`(h>>48)`/`(h>>32)` are always `0000`, making every fabricated address
`fe80::0000:0000:XXXX:YYYY` — a fixed, detectable pattern.

**Design:** (1) prefer deriving the fe80 IID from the *configured global* `webrtc:ipv6` for the same
`userContextId`, when one is set — SLAAC hosts share one interface identifier between their
link-local and global addresses, so reusing it is strictly more coherent than fabricating a second,
unrelated one. `@IPV6`'s jvv regex (`settings/camoucfg.jvv`,
`^(([0-9a-fA-F]{0,4}:){1,7}[0-9a-fA-F]{0,4})$`) requires the fully `:`-delimited form with **no `::`
compression** — so "the last 4 groups" is a plain split on `:`, no NSPR/`PRNetAddr` IPv6 parser
needed. (2) When no global IPv6 is configured for the context, fall back to fabrication, shaped by
`navigator.platform` (already an existing, generic `MaskConfig::GetString` key — reusing it for OS
policy keeps this coherent with the rest of the fingerprint by construction, no new config key), and
fix the truncation bug by combining two 32-bit `HashGeneric` calls into 48 bits of fake-MAC entropy.

**Files:** Modify `patches/webrtc-ip-spoofing2.patch`

**Interfaces:** `FabricateLinkLocalIPv6(uint32_t userContextId) -> std::string` — signature unchanged,
call site in `getMaskForIP` unchanged.

- [ ] **Step 1: Rewrite `FabricateLinkLocalIPv6`**:
```cpp
// Modified-EUI-64: given 6 fake MAC bytes m[0..5], IID = (m0^0x02):m1 | m2:ff | fe:m3 | m4:m5.
static void Eui64Hextets(const uint8_t m[6], uint16_t out[4]) {
  out[0] = ((m[0] ^ 0x02) << 8) | m[1];
  out[1] = (m[2] << 8) | 0xff;
  out[2] = (0xfe << 8) | m[3];
  out[3] = (m[4] << 8) | m[5];
}

// Last 4 ':'-delimited groups of a jvv-validated (no "::" compression)
// IPv6 string — the interface identifier a SLAAC host shares between its
// global and link-local addresses. Returns false if aIpv6 has < 4 groups.
static bool LastFourGroups(const nsAString& aIpv6, uint16_t out[4]) {
  // <split aIpv6 on ':' via nsCharSeparatedTokenizer or manual FindChar,
  //  reject empty groups, require >= 4 parts — see Step 1 note>
  if (parts.Length() < 4) return false;
  for (size_t i = 0; i < 4; ++i) {
    out[i] = static_cast<uint16_t>(
        strtoul(NS_ConvertUTF16toUTF8(parts[parts.Length() - 4 + i]).get(),
                nullptr, 16));
  }
  return true;
}

std::string FabricateLinkLocalIPv6(uint32_t userContextId) {
  uint16_t hex[4];
  nsString globalIpv6;
  // Prefer the configured global IID — SLAAC hosts share one IID between
  // fe80:: and their global address.
  if (WebRTCIPManager::GetIPv6(userContextId, globalIpv6) &&
      LastFourGroups(globalIpv6, hex)) {
    // fall through to snprintf below
  } else {
    // Fabricate: combine two 32-bit hashes into 48 bits of fake-MAC
    // entropy. mozilla::HashGeneric returns HashNumber = uint32_t, NOT
    // uint64_t — a single call truncates, which is the bug this replaces.
    uint32_t h1 = mozilla::HashGeneric(userContextId, 0xC0FFEEu);
    uint32_t h2 = mozilla::HashGeneric(userContextId, 0xFACADEu);
    uint8_t mac[6] = {
        static_cast<uint8_t>(h1 >> 24), static_cast<uint8_t>(h1 >> 16),
        static_cast<uint8_t>(h1 >> 8),  static_cast<uint8_t>(h2 >> 24),
        static_cast<uint8_t>(h2 >> 16), static_cast<uint8_t>(h2 >> 8)};

    bool windows = false;
    if (auto plat = MaskConfig::GetString("navigator.platform")) {
      windows = plat->rfind("Win", 0) == 0;  // "Win32"/"Win64" prefix
    }
    if (windows) {
      // Windows: randomized interface identifiers by default since
      // Vista — opaque, no EUI-64 structure. Use the two hashes directly.
      hex[0] = static_cast<uint16_t>(h1 >> 16); hex[1] = static_cast<uint16_t>(h1);
      hex[2] = static_cast<uint16_t>(h2 >> 16); hex[3] = static_cast<uint16_t>(h2);
    } else {
      // macOS/Linux default: EUI-64-derived from a (fake) MAC.
      Eui64Hextets(mac, hex);
    }
  }
  char buf[40];
  snprintf(buf, sizeof(buf), "fe80::%04x:%04x:%04x:%04x", hex[0], hex[1], hex[2], hex[3]);
  return std::string(buf);
}
```
  `LastFourGroups`'s split is real work, not a placeholder to ship as-is — implement it against the
  real `nsAString`/`nsTArray` API available in this translation unit (`nsCharSeparatedTokenizer` or a
  manual `FindChar`-based loop, both already reachable without new `#include`s). Resolve the exact
  call during Step 3's rehearsal + Step 4's identifier check, mirroring P0's "reimplement against real
  anchors, verify by rehearsal + grep + compile" discipline rather than hand-guessing an unverified API.
- [ ] **Step 2:** `getMaskForIP`'s call site
  (`if (isLinkLocalIPv6(ip)) { return FabricateLinkLocalIPv6(userContextId); }`) is unchanged —
  `FabricateLinkLocalIPv6` now internally calls `WebRTCIPManager::GetIPv6`, already declared/visible
  at this point in the file via the existing `#include`.
- [ ] **Step 3: Gate** — `FETCH="curl -fsSL" bash scripts/rehearse-patch.sh webrtc-ip-spoofing2.patch`
  → `rejects=0 skipped=0 wrongpath=0 fuzz=0 max|offset|=0`.
- [ ] **Step 4: Identifier check**:
```bash
T=.rehearse/webrtc-ip-spoofing2.patch/tree
grep -n "Eui64Hextets\|LastFourGroups\|HashGeneric\|navigator.platform" "$T"/dom/media/webrtc/jsapi/PeerConnectionImpl.cpp
```
  Expected: no reference to the removed truncating single-`HashGeneric`-to-`uint64_t` pattern remains;
  both new helpers present. Full linkage proven by compile (Task 6).
- [ ] **Step 5: build-tester regression guard** (`build-tester/src/lib/checks/collectors.ts`,
  `checkWebRTCLinkLocal`) — when a future test profile sets `webrtc:localipv6` (fe80 case; not
  required for the existing RFC1918/`webrtc:localipv4` case this collector already covers), assert
  the emitted candidate does **not** contain the literal `0000:0000` mid-pattern the old code always
  produced. Gate this on IPv6 ICE gathering actually working on the CI runner, same
  `skipped=true`-not-fail discipline `checkWebRTCLinkLocal` already uses for the RFC1918 case
  (`build-tester/scripts/runner.py` Step 1's default-route caveat applies identically to IPv6) — do
  not force this to a hard pass if the runner has no IPv6 connectivity.
- [ ] **Step 6: Commit** —
  `git commit -m "fix(patches): shape fe80 IID to spoofed OS policy, match fabricated global IPv6 IID"`.

---

### Task 5: New build-tester CSS-media collector (in-phase deliverable)

Mirrors the P0 `checkCanvasPerturbation`/`checkWebRTCLinkLocal` shape: a typed collector, wired into
`index.ts`, counted in `grading.py`, with expected values injected in `runner.py`.

**Files:** Modify `build-tester/src/lib/types.ts`, `build-tester/src/lib/checks/collectors.ts`,
`build-tester/src/lib/checks/index.ts`, `build-tester/scripts/runner.py`,
`build-tester/scripts/grading.py`

**Interfaces:** `checkCssMediaSpoofing(): Promise<CssMediaSpoofingResult>`,
`CssMediaSpoofingResult = { passed: boolean; checks: Record<string, {expected:string; actual:string; passed:boolean}>; detail: string }`.

- [ ] **Step 1: Type** (`types.ts`):
```typescript
export interface CssMediaSpoofingResult {
  passed: boolean;
  checks: Record<string, { expected: string; actual: string; passed: boolean }>;
  detail: string;
}
```
  Add `cssMediaSpoofing: CssMediaSpoofingResult;` to `TestResults`.
- [ ] **Step 2: Collector** (`collectors.ts`) — reads `window.__expectedCssMedia__` (mirrors
  `__expectedWebRTC__`), runs `matchMedia` per configured feature, skips-as-pass when unset (same
  discipline as `checkWebRTCLinkLocal`, so `count_all_checks` doesn't false-negative untouched
  profiles):
```typescript
import type { CssMediaSpoofingResult } from "../types";
const CSS_MEDIA_QUERIES: Record<string, (v: string) => string> = {
  displayDynamicRange: (v) => `(dynamic-range: ${v})`,
  prefersContrast: (v) => `(prefers-contrast: ${v})`,
  invertedColors: (v) => `(inverted-colors: ${v === "true" ? "inverted" : "none"})`,
  monochrome: (v) => `(monochrome: ${v})`,
  pointerCapabilities: (v) => `(pointer: ${v === "coarse" ? "coarse" : v === "none" ? "none" : "fine"})`,
};
export async function checkCssMediaSpoofing(): Promise<CssMediaSpoofingResult> {
  const exp = (window as any).__expectedCssMedia__ as Record<string, string> | undefined;
  const res: CssMediaSpoofingResult = { passed: true, checks: {}, detail: "" };
  if (!exp) { res.detail = "skipped (no __expectedCssMedia__)"; return res; }
  for (const [key, value] of Object.entries(exp)) {
    const buildQuery = CSS_MEDIA_QUERIES[key];
    if (!buildQuery) continue;
    const matches = matchMedia(buildQuery(value)).matches;
    res.checks[key] = { expected: value, actual: String(matches), passed: matches };
    if (!matches) res.passed = false;
  }
  res.detail = res.passed ? "all cssMedia keys matched" : JSON.stringify(res.checks);
  return res;
}
```
  Note: `pointer`/`hover` structural checks already exist in `extended.ts` (`pointerType`/
  `hoverCapability`, asserting real-desktop plausibility) — this collector is additive, asserting the
  *configured spoof value* is what `matchMedia` reports, not re-deriving desktop-plausibility.
- [ ] **Step 3: Wire** in `index.ts` — mirror the `webrtcLinkLocal`/`canvasPerturbation` phase pattern
  (e.g. "Phase 5c"): import + call `checkCssMediaSpoofing`, add to the returned `TestResults`.
- [ ] **Step 4: Inject expected config in `runner.py`** — mirror the `canvas:seed`/
  `__expectedWebRTC__` injection pattern (lines 197-206 per-context, 315-324 global). For one test
  profile, set `cssMedia:prefersContrast=more`, `cssMedia:invertedColors=true`,
  `cssMedia:monochrome=0`, `cssMedia:pointerCapabilities=coarse`, `cssMedia:displayDynamicRange=high`
  in `camouConfig`, and expose `window.__expectedCssMedia__` via `initScript`/`add_init_script` with
  the same key names.
- [ ] **Step 5:** `grading.py` — after the `webrtcLinkLocal` block (`count_all_checks`, line ~52-54):
```python
    total_checks += 1
    if results.get("cssMediaSpoofing", {}).get("passed"):
        pass_count += 1
```
- [ ] **Step 6: Build** — `cd build-tester && npm install && npm run build` → no TS errors.
- [ ] **Step 7: Commit** —
  `git commit -m "test(build-tester): CSS-media spoofing collector (prefers-contrast/inverted-colors/monochrome/pointer/dynamic-range)"`.

---

### Task 6: CI gate — both patches rehearsed, both test suites, PR

**Files:** none (dispatch + evidence)

- [ ] **Step 1:**
```bash
FETCH="curl -fsSL" bash scripts/rehearse-patch.sh css-media-spoofing.patch
FETCH="curl -fsSL" bash scripts/rehearse-patch.sh webrtc-ip-spoofing2.patch
```
  Both → `rejects=0 skipped=0 wrongpath=0 fuzz=0 max|offset|=0`, exit 0.
- [ ] **Step 2:** `cd goapi && go test ./...` → green, `TestProducerSchemaDrift` included.
- [ ] **Step 3: Push + dispatch**
```bash
git push -u origin spec/spoofing-patch-hardening
gh workflow run "Build and Release" --repo lang315/camoufox -f build_target=linux-x86_64 --ref spec/spoofing-patch-hardening
```
  Confirm clean apply: `gh run view <id> --repo lang315/camoufox --log | grep -iE "FAILED|\.rej|can.?t find file|ignored" || echo "clean apply"` → `clean apply`.
- [ ] **Step 4:**
```bash
gh run download <id> --repo lang315/camoufox --name CamoufoxBuilds-linux-x86_64 -D /tmp/cf
cd build-tester && python scripts/run_tests.py /tmp/cf/<bin> --json /tmp/p2.json
python - <<'PY'
import json
r = json.load(open("/tmp/p2.json"))
prof = [p for p in r["profiles"] if "cssMediaSpoofing" in p.get("results", {})]
assert prof, "no profile ran the cssMediaSpoofing collector"
res = prof[0]["results"]["cssMediaSpoofing"]
assert res["passed"], res
print("P2 cssMediaSpoofing PASS:", res["detail"])
PY
```
- [ ] **Step 5:** `service-tester` — run, capture pass output.
- [ ] **Step 6: PR** — `gh pr create ... --body` with: rehearse-patch output (both patches,
  all-zero), CI clean-apply link, `go test` output (incl. `TestProducerSchemaDrift`), jvv smoke-test
  output (Task 2 Step 12), `/tmp/p2.json` excerpt (`cssMediaSpoofing.passed=true`), service-tester
  pass. Note the Task 3 rebase-risk flag for P1.3 in the description. `Closes #N`.

---

## Self-Review

**Spec coverage (P2 slice):** dynamic-range confirm + spoof block → Task 1; color/display +
form-factor blocks → Task 2 (`update` dropped with cause; `screen.colorDepth` confirmed
already-separate and untouched); forced-colors/prefers-contrast coherence + P1 scheduling +
shared-patch-file rebase-risk note → Task 3; fe80 OS-policy shaping + global-IID match → Task 4; new
build-tester CSS-media collector → Task 5; jvv/properties registration (new + pre-existing lag) +
both suites + PR evidence → Tasks 2, 6.

**Deviations from the spec's literal task list, with cause:** (1) `update` gets no config key —
`eval_update` has no per-host C++ hook in real FF152 (`media_features.rs:371-386`); shipping a key no
code path reads would itself be a fabricated-looking spoof, the exact class of defect this whole
hardening effort exists to remove. (2) `forced-colors` gets schema only in this phase, not a patch
hunk — no `Gecko_MediaFeatures_ForcedColors` exists to patch; the real state
(`nsPresContext::mForcedColors`) is P1.3's file. Both are source-verified findings, not scope-cutting.

**Placeholder scan:** Task 1/2 hunks are real-context insertions against either (a) the already
0-fuzz `css-media-spoofing.patch`'s own file (Task 1's `DynamicRange`, adjacent to the existing
`VideoDynamicRange` hunk) or (b) freshly hg-fetched FIREFOX_152_0_4_RELEASE source (Task 2's
`PrefersContrast`/`InvertedColors`/`GetMonochromeBitsPerPixel`/`GetPointerCapabilities`; Task 3's
`nsPresContext::UpdateForcedColors` citation) — no `<verify>`/fabricated context in the P0 sense. Task
4's `LastFourGroups` split-helper body is intentionally left as "real work, implement against the
existing translation unit's real `nsAString` API" rather than a hand-specified, unverified call —
flagged explicitly in Step 1, resolved by the same rehearsal + identifier-grep + compile gate as
everything else, not asserted as already-correct.

**Type consistency:** `CssMediaSpoofingResult` (Task 5) follows the `WebRTCLinkLocalResult`/
`CanvasPerturbationResult` shape from P0 (skip-not-fail on missing expectation, typed `checks`/
`surfaces` map, `passed` boolean); counted in `grading.py` identically to the existing collectors.

**Known limitations (later phases, not P2 gaps):** `Config.Validate()` doesn't exist yet in this
branch (P1 not implemented) — Task 3's coherence rule is documented at both hunks, not enforced in
Go, until P1 lands it. Multi-pointer-device profiles (primary != all pointer capabilities) are out of
scope — Task 2's single `cssMedia:pointerCapabilities` key is a deliberate simplification tied to the
existing desktop-only preset set, not a placeholder. The fe80 "fake MAC" (Task 4) is not
vendor-OUI-realistic (random bytes, not a real NIC vendor prefix) — acceptable for this phase's goal
(structural correctness + global-IID coherence), same spirit as P0's Phase 4 deferral of full
canvas-noise realism.

**Residual risk to flag at execution:** Task 4's fe80 regression assertion (Step 5) depends on the CI
runner actually gathering IPv6 ICE candidates — P0's own local-branch collector already found
runner-environment-dependent (`build-tester/scripts/runner.py`'s default-route caveat). If the runner
has no IPv6 connectivity, that sub-check must `skip`, not fail, mirroring the existing
`webrtcLinkLocal` skip discipline — do not weaken it to force green. Task 2's
`PointerCapabilities(0)` spelling is a best guess pending the real FF152 header (Step 10's identifier
check is the actual verification, not this plan).
