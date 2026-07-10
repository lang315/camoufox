# Spoofing-patch hardening — P3 (persistence + worker) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Revision:** r1.

**Goal:** Define the profile-identity concept Camoufox's Go launcher does not have today (`WithProfileID`/`WithUserDataDir`), derive the canvas/audio/font-spacing noise seeds from it so they are stable across relaunches of the same identity and distinct across identities, and perturb the offscreen/worker WebGL readback path that currently stays un-noised. Prove all three with build-tester ground-truth collectors against a built binary, not just goapi unit tests.

**Architecture:** This phase is almost entirely a **goapi-side** change: `canvas:seed` / `audio:seed` / `fonts:spacing_seed` are already registered CAMOU_CONFIG keys (`settings/camoucfg.jvv:79-81`, `settings/properties.json:58-60`) and are already read by three separate, already-real (not P0-fabricated) C++ consumers — `CanvasSeedManager::GetSeed` (`patches/canvas-spoofing.patch`), `audio-fingerprint-manager.patch:50`, and `anti-font-fingerprinting.patch:53` — all via `MaskConfig::GetUint32`. The gap is entirely upstream of the C++: goapi has no notion of a persistent identity, so `fingerprint.Generate` (`goapi/pkg/fingerprint/generator.go:78-86`) draws a fresh random seed on every call, and `make run` wipes `~/.camoufox` on every launch (`Makefile:186-190`) so there is no persistent Firefox profile either. Only one piece requires a C++ patch edit: `ClientWebGLContext::ReadPixels`'s perturbation hunk in `patches/canvas-spoofing.patch` explicitly no-ops for OffscreenCanvas/worker contexts today ("Offscreen/worker contexts have no owner document and stay unperturbed for now") — extending that is blocked on P0 Task 7 (see Global Constraints).

**Design decision (stated explicitly, not silently picked):** canvas/audio/fonts-spacing seeds are derived from the **same** profile ID but through **domain-separated** hashes (`hash(id, "canvas")`, `hash(id, "audio")`, `hash(id, "fonts")`), not one shared value reused verbatim. A single shared seed across three otherwise-independent noise generators would itself be a coherence anti-pattern — three fingerprint surfaces reporting a correlated seed is a signal a sophisticated fingerprinter can exploit, whereas three independently-derived-but-each-stable values match what a real persistent browser profile looks like (each subsystem keeps its own state).

**Tech Stack:** Go 1.2x (`goapi`), `hash/fnv` (stdlib, no new dependency), Firefox source patch (`patches/canvas-spoofing.patch`) via P0's `scripts/rehearse-patch.sh` harness, TypeScript/Playwright (`build-tester`).

## Global Constraints

- **HARD DEPENDENCY (Task 6 only):** `patches/canvas-spoofing.patch` still contains the fabricated `OffscreenCanvas::GetDocument()` accessor, the wrong `dom/canvas/HTMLCanvasElement.cpp` path, and `<verify …>` placeholders as of this writing (verified directly, not taken on the P0 doc's word — `grep -n "GetDocument\|<verify" patches/canvas-spoofing.patch` is non-empty on this branch today). Task 6 (the C++ worker/offscreen extension) cannot start until P0 Task 7 reimplements this patch against real FF152 source. **Tasks 0–5 and 7 have no such dependency** — the profile-identity option surface, the seed-derivation logic, and two of the three build-tester collector legs (audio, fonts) are testable today because their C++ consumers (`audio-fingerprint-manager.patch`, `anti-font-fingerprinting.patch`) are not part of P0's fabrication findings.
- Task 6 also depends on `scripts/rehearse-patch.sh` (P0 Task 1) — already present on this branch (`scripts/rehearse-patch.sh` exists).
- Do not fabricate C++ identifiers. This is the exact defect class P0 exists to fix (`OffscreenCanvas::GetDocument()`, `WorkerPrivate::GetOriginAttributes()` as used by the current unmerged patch, are both unverified against real FF152 source). Task 6 must fetch and grep real source via the rehearsal harness before writing any hunk — never assume a name because it already appears in the draft patch.
- No new CAMOU_CONFIG keys: `canvas:seed`, `audio:seed`, `fonts:spacing_seed` are already registered in both `settings/camoucfg.jvv` and `settings/properties.json` (confirmed by grep). Unlike P1/P2, P3 needs no schema task.
- Every PR: tied to a GitHub issue; **both** `build-tester/` and `service-tester/` pass; PR body carries concrete evidence (command output + exit status).
- Surgical: `git add` exact files, never a whole directory.
- **Sequencing:** Tasks 1–5 can land as one PR now (no P0 dependency). Task 6 must ship as its own follow-up PR once P0 Task 7 merges. Task 7 (CI gate) runs once against the Tasks-1–5 PR (asserting the audio/fonts legs pass and the canvas/worker legs are the *expected* red — see Task 4/7) and again once Task 6 lands (asserting everything passes).

---

### Task 0: Tracking issue

**Files:** none.

- [ ] **Step 1: Open the tracking issue**

```bash
gh issue create --repo lang315/camoufox --title "P3: persistence + worker canvas/audio/font-spacing seed coverage" --body "Profile-identity source (WithProfileID/WithUserDataDir), deterministic canvas/audio/fonts-spacing seed derivation, and offscreen/worker WebGL perturbation. Tasks 1-5 and 7 are independent; Task 6 (C++ worker/offscreen patch) is BLOCKED on P0 Task 7 (canvas-spoofing.patch reimplementation) landing first. Spec: docs/superpowers/specs/2026-07-08-spoofing-patch-hardening-design.md (Phase 3)."
```
Record issue number `N`. No commit — no files changed.

---

### Task 1: Profile-identity option surface — `WithProfileID` / `WithUserDataDir`

Neither option exists today: `goapi/options.go`'s `launchConfig` has no profile-identity or user-data-dir field, and `goapi/launch.go`'s arg-building block (`--juggler-pipe --no-remote` + optional `--headless` + `lc.args`) never emits `-profile`. `make run` wipes `~/.camoufox` and `obj-*/tmp/profile-default` on every invocation (`Makefile:186-190`), confirming there is no persistence path today.

**Files:** Modify `goapi/options.go`, `goapi/launch.go`.

**Interfaces:** `WithProfileID(id string) Option`, `WithUserDataDir(dir string) Option`.

- [ ] **Step 1: Add the two fields to `launchConfig`** (`goapi/options.go`, next to the existing `virtualDisplay string` field):
```go
	virtualDisplay  string

	profileID   string // stable identity used to derive noise seeds (Task 2)
	userDataDir string // -profile <dir>; empty = throwaway profile (today's default)
```

- [ ] **Step 2: Add the two `Option` functions** (append after `WithWebRTCLocalIP` at the end of the file):
```go
// WithProfileID pins the fingerprint noise seeds (canvas:seed, audio:seed,
// fonts:spacing_seed) to a deterministic hash of id instead of a fresh
// random value on every launch. The same id always produces the same
// seeds — drawing a new random seed on every relaunch is itself an
// anti-persistence signal (a real returning visitor's canvas/audio/font
// noise does not drift) — while two different ids stay distinct. Pass
// alongside WithUserDataDir for full session persistence (cookies,
// localStorage); id alone only stabilizes the noise seeds.
func WithProfileID(id string) Option {
	return func(c *launchConfig) { c.profileID = id }
}

// WithUserDataDir points the browser at a persistent profile directory
// (-profile dir) instead of the throwaway profile `make run` wipes on
// every launch. Firefox creates the directory if it does not already
// exist.
func WithUserDataDir(dir string) Option {
	return func(c *launchConfig) { c.userDataDir = dir }
}
```

- [ ] **Step 3: Wire `-profile` into the Firefox CLI args** (`goapi/launch.go`, in the arg-building block right after the `lc.headless` branch, before `args = append(args, lc.args...)`):
```go
	args := []string{"--juggler-pipe", "--no-remote"}
	if lc.headless {
		args = append(args, "--headless")
	}
	if lc.userDataDir != "" {
		args = append(args, "-profile", lc.userDataDir)
	}
	args = append(args, lc.args...)
```

- [ ] **Step 4: Verify** — `cd goapi && go build ./... && go vet ./...` → no errors. `lc.profileID` is stored but not yet consumed (Task 2 wires it into fingerprint generation); an unused *struct field* is not a Go compile error, so this step leaves the tree in a clean, buildable state on its own.

- [ ] **Step 5: Manual smoke (documented, not automated here)** — launch twice with the same `WithUserDataDir(dir)` pointed at a real path and confirm Firefox does not error on the second launch (a stale profile lock would show as `-no-remote`/profile-in-use errors); this is folded into Task 7's CI gate as the authoritative check, not repeated as a separate manual gate.

- [ ] **Step 6: Commit**
```bash
git add goapi/options.go goapi/launch.go
git commit -m "feat(goapi): add WithProfileID/WithUserDataDir profile-identity options"
```

---

### Task 2: Deterministic per-signal seed derivation (canvas + audio + fonts-spacing)

Covers spec items 1 and 2 together, in one task/commit, deliberately: `generator.go:78-86` is a single contiguous block (`FontsSpacingSeed`, `AudioSeed`, `CanvasSeed`, in that order) that already treats all three identically ("Per-launch fingerprint noise seeds"); pinning only `CanvasSeed` while leaving `AudioSeed`/`FontsSpacingSeed` on the old random path would recreate exactly the incoherence the design doc calls out ("pinning only canvas is itself incoherent under a multi-signal revisit oracle") — a detector could persistence-fingerprint via audio/fonts even after canvas stops drifting. Splitting this into two commits would just be busywork with a moment of shipped-incoherent state in between.

**Files:** Modify `goapi/pkg/fingerprint/generator.go`, `goapi/launch.go`.

**Interfaces:** `fingerprint.Options.ProfileID string` (new field); `deriveProfileSeed(profileID string, domain byte) uint32` (unexported helper).

- [ ] **Step 1: Add `ProfileID` to `Options`** (`generator.go`, in the `Options` struct doc block):
```go
type Options struct {
	// OS restricts presets to one of "windows" | "macos" | "linux".
	// Empty means "any".
	OS string
	// FirefoxVersion, if non-empty, is patched into the preset UA
	// (replaces Firefox/<n> and rv:<n>) — matches from_preset() in
	// pythonlib/camoufox/fingerprints.py.
	FirefoxVersion string
	// Rand controls all sampling. Pass nil for a fresh PRNG seeded
	// from the global source.
	Rand *rand.Rand
	// ProfileID, if non-empty, pins CanvasSeed/AudioSeed/FontsSpacingSeed
	// to a deterministic hash of this string (see deriveProfileSeed)
	// instead of a fresh random value. Empty preserves today's random
	// per-launch behavior.
	ProfileID string
}
```

- [ ] **Step 2: Add the domain-separated hash helper** (`generator.go`, new code near the top, below the package-level regexes):
```go
// Domain-separation tags for deriveProfileSeed. The values themselves are
// arbitrary; they exist only so the same profileID yields three different
// (but each individually stable) seeds — see "Design decision" in the P3
// plan for why canvas/audio/fonts must not share one seed.
const (
	seedDomainCanvas byte = 1
	seedDomainAudio  byte = 2
	seedDomainFonts  byte = 3
)

// deriveProfileSeed hashes (profileID, domain) into a stable, non-zero
// uint32 noise seed: same inputs always produce the same output (stability
// across relaunches of one profile), different domains for the same
// profileID diverge (canvas/audio/fonts don't correlate), and different
// profileIDs diverge with the ordinary avalanche properties of FNV-1a
// (non-cryptographic — profileID is caller-supplied, not adversarial
// input, so collision-resistance beyond "good enough to not accidentally
// alias two different callers' ids" is not a requirement here).
func deriveProfileSeed(profileID string, domain byte) uint32 {
	h := fnv.New32a()
	_, _ = h.Write([]byte(profileID))
	_, _ = h.Write([]byte{domain})
	sum := h.Sum32()
	return 1 + sum%0xFFFFFFFE // keep in [1, 2^32-1]; 0 is the C++-side no-op signal
}
```
Add `"hash/fnv"` to the import block.

- [ ] **Step 3: Replace the three seed-default blocks** (`generator.go:78-86`):
```go
	// Per-launch fingerprint noise seeds (1..2^32-1; 0 is a no-op
	// signal in the C++ side). ProfileID pins them to a deterministic
	// hash so a persistent identity's noise doesn't drift across
	// relaunches (see deriveProfileSeed).
	if cfg.FontsSpacingSeed == nil {
		if opts.ProfileID != "" {
			cfg.FontsSpacingSeed = config.Uint32(deriveProfileSeed(opts.ProfileID, seedDomainFonts))
		} else {
			cfg.FontsSpacingSeed = config.Uint32(uint32(1 + rng.Uint32N(0xFFFFFFFE)))
		}
	}
	if cfg.AudioSeed == nil {
		if opts.ProfileID != "" {
			cfg.AudioSeed = config.Uint32(deriveProfileSeed(opts.ProfileID, seedDomainAudio))
		} else {
			cfg.AudioSeed = config.Uint32(uint32(1 + rng.Uint32N(0xFFFFFFFE)))
		}
	}
	if cfg.CanvasSeed == nil {
		if opts.ProfileID != "" {
			cfg.CanvasSeed = config.Uint32(deriveProfileSeed(opts.ProfileID, seedDomainCanvas))
		} else {
			cfg.CanvasSeed = config.Uint32(uint32(1 + rng.Uint32N(0xFFFFFFFE)))
		}
	}
```
Fields already populated on `cfg` (caller override) are still left untouched — the `if cfg.X == nil` guards are unchanged, so this is purely a default-selection change, not a new override path.

- [ ] **Step 4: Wire `ProfileID` through `Launch`** (`goapi/launch.go`, in the `fpOpts` construction inside the `if !lc.skipFingerprint` block):
```go
		fpOpts := fingerprint.Options{
			OS:             lc.os,
			FirefoxVersion: lc.firefoxVersion,
			Rand:           lc.rand,
			ProfileID:      lc.profileID,
		}
```

- [ ] **Step 5: Verify** — `cd goapi && go build ./... && go vet ./...` → no errors.

- [ ] **Step 6: Commit**
```bash
git add goapi/pkg/fingerprint/generator.go goapi/launch.go
git commit -m "feat(fingerprint): derive canvas/audio/fonts-spacing seeds from profile ID"
```

---

### Task 3: Go tests — stability, distinctness, domain separation, backward compatibility

**Files:** Create `goapi/pkg/fingerprint/profile_seed_test.go`.

- [ ] **Step 1: Write the table-driven tests**
```go
package fingerprint

import (
	"math/rand/v2"
	"testing"

	"github.com/lang315/camoufox/goapi/pkg/config"
)

func TestDeriveProfileSeedStable(t *testing.T) {
	a := deriveProfileSeed("alpha", seedDomainCanvas)
	b := deriveProfileSeed("alpha", seedDomainCanvas)
	if a != b {
		t.Fatalf("same (id, domain) diverged: %d != %d", a, b)
	}
	if a == 0 {
		t.Fatal("derived seed must never be 0 (0 is the C++ no-op signal)")
	}
}

func TestDeriveProfileSeedDomainSeparation(t *testing.T) {
	canvas := deriveProfileSeed("alpha", seedDomainCanvas)
	audio := deriveProfileSeed("alpha", seedDomainAudio)
	fonts := deriveProfileSeed("alpha", seedDomainFonts)
	if canvas == audio || canvas == fonts || audio == fonts {
		t.Fatalf("same profileID must diverge across domains: canvas=%d audio=%d fonts=%d", canvas, audio, fonts)
	}
}

func TestDeriveProfileSeedDistinctAcrossProfiles(t *testing.T) {
	ids := []string{"alpha", "beta", "gamma", "profile-1", "profile-2"}
	for _, domain := range []byte{seedDomainCanvas, seedDomainAudio, seedDomainFonts} {
		seen := map[uint32]string{}
		for _, id := range ids {
			s := deriveProfileSeed(id, domain)
			if prev, ok := seen[s]; ok {
				t.Fatalf("domain %d: ids %q and %q collided on seed %d", domain, prev, id, s)
			}
			seen[s] = id
		}
	}
}

func TestGenerateWithProfileIDIsStableAcrossCalls(t *testing.T) {
	cfg1, cfg2 := &config.Config{}, &config.Config{}
	// Deliberately do NOT pin Rand: proves the seeds are stable because of
	// ProfileID, not because the caller happened to reuse a PRNG (the
	// preset itself is free to differ between the two calls).
	if err := Generate(cfg1, Options{OS: "windows", ProfileID: "same-profile"}); err != nil {
		t.Fatal(err)
	}
	if err := Generate(cfg2, Options{OS: "windows", ProfileID: "same-profile"}); err != nil {
		t.Fatal(err)
	}
	if *cfg1.CanvasSeed != *cfg2.CanvasSeed {
		t.Errorf("canvas seed drifted across relaunches: %d != %d", *cfg1.CanvasSeed, *cfg2.CanvasSeed)
	}
	if *cfg1.AudioSeed != *cfg2.AudioSeed {
		t.Errorf("audio seed drifted across relaunches: %d != %d", *cfg1.AudioSeed, *cfg2.AudioSeed)
	}
	if *cfg1.FontsSpacingSeed != *cfg2.FontsSpacingSeed {
		t.Errorf("fonts-spacing seed drifted across relaunches: %d != %d", *cfg1.FontsSpacingSeed, *cfg2.FontsSpacingSeed)
	}
	if *cfg1.CanvasSeed == *cfg1.AudioSeed || *cfg1.CanvasSeed == *cfg1.FontsSpacingSeed || *cfg1.AudioSeed == *cfg1.FontsSpacingSeed {
		t.Error("canvas/audio/fonts seeds must not collide for one profile (domain separation)")
	}
}

func TestGenerateDifferentProfileIDsDiverge(t *testing.T) {
	cfgA, cfgB := &config.Config{}, &config.Config{}
	if err := Generate(cfgA, Options{OS: "windows", ProfileID: "profile-a"}); err != nil {
		t.Fatal(err)
	}
	if err := Generate(cfgB, Options{OS: "windows", ProfileID: "profile-b"}); err != nil {
		t.Fatal(err)
	}
	if *cfgA.CanvasSeed == *cfgB.CanvasSeed {
		t.Error("different profile IDs must not share a canvas seed")
	}
	if *cfgA.AudioSeed == *cfgB.AudioSeed {
		t.Error("different profile IDs must not share an audio seed")
	}
	if *cfgA.FontsSpacingSeed == *cfgB.FontsSpacingSeed {
		t.Error("different profile IDs must not share a fonts-spacing seed")
	}
}

// Regression guard: empty ProfileID (today's default) must keep drawing
// from Rand exactly as before — P3 must not change behavior for callers
// who never opt in.
func TestGenerateEmptyProfileIDPreservesRandomBehavior(t *testing.T) {
	cfgA := &config.Config{}
	if err := Generate(cfgA, Options{OS: "windows", Rand: rand.New(rand.NewPCG(1, 2))}); err != nil {
		t.Fatal(err)
	}
	cfgB := &config.Config{}
	if err := Generate(cfgB, Options{OS: "windows", Rand: rand.New(rand.NewPCG(3, 4))}); err != nil {
		t.Fatal(err)
	}
	if *cfgA.CanvasSeed == *cfgB.CanvasSeed {
		t.Error("two different PRNG seeds with no ProfileID should not coincidentally match (flaky only in the astronomically unlikely case — if this ever fires, check the RNG wiring, not the test)")
	}
}
```

- [ ] **Step 2: Run** — `cd goapi && go test ./pkg/fingerprint/...` → all green.

- [ ] **Step 3: Commit**
```bash
git add goapi/pkg/fingerprint/profile_seed_test.go
git commit -m "test(fingerprint): stability/distinctness/domain-separation for profile seeds"
```

---

### Task 4: build-tester — cross-session hash stability + cross-profile distinctness collector

Scope boundary (stated explicitly): this collector validates the **binary's** contract — "same `CAMOU_CONFIG` seed across two independent process launches ⇒ same fingerprint hash; different seed ⇒ different hash." It does **not** re-derive `deriveProfileSeed` in Python — that Go function's own contract (`profileID → seed`) is already proven by Task 3's unit tests. The two layers together prove the full chain end to end without duplicating the hash algorithm in two languages.

Reuses the existing `collectFingerprints()` output (`build-tester/src/lib/checks/collectors.ts:24-` — `fingerprints.canvas.hash`, `fingerprints.audio.hash`, `fingerprints.fonts.hash`, already collected by every profile today); no new page-side JS is needed for this task.

**Files:** Modify `build-tester/scripts/runner.py`.

**Interfaces:** new `async def run_persistence_phase(firefox, binary_path, test_page_url) -> dict`, called from `run_tests()`; new top-level `full_result["persistence"]` key (parallel to the existing `full_result["crossProfile"]`).

- [ ] **Step 1: Write the phase** — two seed triples, three launches (A, A-again, B), each a full independent `firefox.launch()`/`browser.close()` cycle (mirrors the existing "Global phase" pattern at `runner.py:289-353`, not the shared-browser per-context phase — persistence must be proven across separate OS processes, not separate `userContextId`s in one process):
```python
# P3 persistence: canvas:seed/audio:seed/fonts:spacing_seed carried directly
# (not derived from a Go ProfileID — see Task 4 scope-boundary note in the
# P3 plan) so this collector tests the C++ seed->hash contract independent
# of goapi's hash function.
PERSISTENCE_SEED_A = {"canvas:seed": 111111, "audio:seed": 222222, "fonts:spacing_seed": 333333}
PERSISTENCE_SEED_B = {"canvas:seed": 444444, "audio:seed": 555555, "fonts:spacing_seed": 666666}


async def _launch_and_collect_hashes(firefox, binary_path: str, test_page_url: str, seeds: dict) -> dict:
    env = {**dict(os.environ), "CAMOU_CONFIG": json.dumps(seeds)}
    browser = await firefox.launch(
        executable_path=binary_path, headless=True, env=env,
        firefox_user_prefs=FIREFOX_WEBGL_PREFS,
    )
    try:
        context = await browser.new_context(viewport={"width": 1920, "height": 1080})
        await context.add_init_script("try { window.__canvasSeedSet__ = true; } catch (e) {}")
        page = await context.new_page()
        await page.goto(test_page_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_function("!!window.__testComplete__", timeout=120000)
        r = await page.evaluate("window.__testResults__")
        fp = (r or {}).get("fingerprints", {})
        return {
            "canvas": fp.get("canvas", {}).get("hash"),
            "audio": fp.get("audio", {}).get("hash"),
            "fonts": fp.get("fonts", {}).get("hash"),
        }
    finally:
        await browser.close()


async def run_persistence_phase(firefox, binary_path: str, test_page_url: str) -> dict:
    print(f"\n{'─' * 60}\nPersistence phase: same-seed relaunch + cross-seed distinctness\n{'─' * 60}")
    a1 = await _launch_and_collect_hashes(firefox, binary_path, test_page_url, PERSISTENCE_SEED_A)
    a2 = await _launch_and_collect_hashes(firefox, binary_path, test_page_url, PERSISTENCE_SEED_A)
    b1 = await _launch_and_collect_hashes(firefox, binary_path, test_page_url, PERSISTENCE_SEED_B)

    per_signal = {}
    for sig in ("canvas", "audio", "fonts"):
        stable = bool(a1.get(sig)) and a1.get(sig) == a2.get(sig)
        distinct = bool(a1.get(sig)) and bool(b1.get(sig)) and a1.get(sig) != b1.get(sig)
        per_signal[sig] = {"stable": stable, "distinct": distinct}

    passed = all(v["stable"] and v["distinct"] for v in per_signal.values())
    return {
        "passed": passed,
        "perSignal": per_signal,
        "runA1": a1, "runA2": a2, "runB1": b1,
    }
```
`os` and `json` are already imported at the top of `runner.py` (used elsewhere in the file); no new imports needed.

- [ ] **Step 2: Call it from `run_tests()`** — after the existing global-phase `for entry in global_entries:` loop, before `cross_profile = compute_cross_profile(profile_results)`:
```python
    persistence_result = await run_persistence_phase(firefox, binary_path, test_page_url)
```
Note this must run inside the existing `async with async_playwright() as pw:` block (`firefox = pw.firefox` is already bound there).

- [ ] **Step 3: Fold into the final tally and JSON** — next to where `total_passed`/`total_checks_sum`/`full_result` are built:
```python
    total_passed += 1 if persistence_result["passed"] else 0
    total_checks_sum += 1

    full_result = {
        "profiles": profile_results,
        "crossProfile": cross_profile,
        "persistence": persistence_result,
        "overallGrade": overall_grade,
        ...
    }
```
(keep the existing `overallGrade = compute_grade(total_passed, total_checks_sum)` call **after** this so the persistence check is folded into the grade, not just reported).

- [ ] **Step 4: Expected state today** — `perSignal.audio` and `perSignal.fonts` should already pass (their C++ consumers are not P0-fabricated). `perSignal.canvas` is expected **red** until P0 Task 7 lands (canvas-spoofing.patch's edit hunks are currently fabricated and may not even apply/compile) — this is the signal that task isn't done, not a bug in this collector. Do not weaken `per_signal["canvas"]` to force green.

- [ ] **Step 5: Smoke** — `cd build-tester && python -c "import scripts.runner"` → no import error. Full validation happens against a built binary in Task 7.

- [ ] **Step 6: Commit**
```bash
git add build-tester/scripts/runner.py
git commit -m "test(build-tester): cross-session hash stability + cross-profile distinctness collector"
```

---

### Task 5: build-tester — worker-canvas-hash collector

Extends the existing `runWorkerChecks()` worker-check pattern (`build-tester/src/lib/checks/workers.ts`, already has `createWorkerAndGetValue` and the analogous `offscreenCanvasWebGL` check at lines 196-239) with a check that a solid-fill `OffscreenCanvas` readback **inside an actual `Worker`** is perturbed — the direct proof that canvas-seed resolution reaches the worker thread, not just the main thread. Because worker code runs from a `Blob` string, the non-uniformity check must be inlined (same constraint the existing `offscreenCanvasWebGL` check already lives with) rather than importing `nonUniform` from `collectors.ts`.

**Files:** Modify `build-tester/src/lib/checks/workers.ts`.

- [ ] **Step 1: Add the check** — inside `runWorkerChecks()`, after the existing `offscreenCanvasWebGL` block (before `serviceWorkerUA`):
```typescript
  // workerCanvasHash — P3: proves the canvas-perturbation seed resolves off
  // the main thread (the worker branch of GetCanvasSeed / Task 6's
  // ClientWebGLContext::ReadPixels extension). Expect RED until P0 Task 7
  // and P3 Task 6 both land — that is the signal those tasks aren't done
  // yet, not a bug in this check. Do not weaken the assertion to force green.
  try {
    const code = `self.onmessage = () => {
  try {
    const c = new OffscreenCanvas(64, 64);
    const ctx = c.getContext('2d');
    ctx.fillStyle = 'rgb(128,128,128)';
    ctx.fillRect(0, 0, 64, 64);
    const d = ctx.getImageData(0, 0, 64, 64).data;
    let ref = -1, nonUniform = false;
    for (let i = 0; i < d.length; i++) {
      if ((i & 3) === 3) continue;
      if (ref < 0) { ref = d[i]; } else if (d[i] !== ref) { nonUniform = true; break; }
    }
    self.postMessage({ nonUniform });
  } catch (e) { self.postMessage({ nonUniform: false, error: e.message }); }
}`;
    const data = await createWorkerAndGetValue<{ nonUniform: boolean; error?: string }>(code);
    if (data.error) {
      workerConsistency.workerCanvasHash = {
        passed: true,
        detail: "Worker OffscreenCanvas 2D unavailable: " + data.error,
      };
    } else {
      workerConsistency.workerCanvasHash = {
        passed: data.nonUniform,
        detail: data.nonUniform
          ? "worker OffscreenCanvas readback is perturbed (non-uniform)"
          : "worker OffscreenCanvas readback is UNIFORM — seed not resolved off main thread (expected until P0 Task 7 + P3 Task 6 land)",
      };
    }
  } catch (e: any) {
    workerConsistency.workerCanvasHash = {
      passed: true,
      detail: "Worker canvas hash test unavailable: " + (e?.message || String(e)),
    };
  }
```

- [ ] **Step 2: No grading.py change needed** — `count_all_checks` already generically sums every `{passed, detail}` entry under `results["workers"]` (`grading.py:39-42`, `count_checks`), so `workerCanvasHash` is counted automatically once it exists.

- [ ] **Step 3: Build** — `cd build-tester && npm install && npm run build` → no TS errors.

- [ ] **Step 4: Commit**
```bash
git add build-tester/src/lib/checks/workers.ts
git commit -m "test(build-tester): worker-canvas-hash collector (off-main-thread seed resolution)"
```

---

### Task 6: Perturb offscreen/worker WebGL readback — BLOCKED on P0 Task 7

`patches/canvas-spoofing.patch`'s `ClientWebGLContext::ReadPixels` hunk is, per P0's own anchor map, the **one** canvas surface that's already real (not fabricated) — P0 Task 7 leaves it untouched. Its current gate is:
```cpp
if (dom::Document* seedDoc = GetOwnerDoc()) {
  const uint32_t seed = dom::CanvasSeedManager::SeedFromDocument(seedDoc);
  ...
}
```
with the comment "Offscreen/worker contexts have no owner document and stay unperturbed for now" — `GetOwnerDoc()` is null for an `OffscreenCanvas`/worker-owned WebGL context, so that branch simply never fires there. This task closes that gap. It does **not** touch the other three surfaces (`GetImageData`, `ExtractData`, `ConvertToBlob`) — those are P0 Task 7's responsibility.

**Files:** Modify `patches/canvas-spoofing.patch` (the `ClientWebGLContext::ReadPixels` hunk only, plus whatever shared seed-resolution helper P0 Task 7 lands for the offscreen/worker case — see Step 2).

- [ ] **Step 0: Re-verify the dependency before starting** — do not trust this plan's snapshot; re-check at execution time:
```bash
grep -n "GetDocument\|<verify" patches/canvas-spoofing.patch
```
Must be **empty** (proves P0 Task 7 landed and removed the fabricated markers). If non-empty, **stop** — do not build worker/offscreen logic on top of code that doesn't compile yet.

- [ ] **Step 1: Confirm the post-P0 baseline gates clean**
```bash
FETCH="curl -fsSL" bash scripts/rehearse-patch.sh canvas-spoofing.patch
```
→ `rejects=0 skipped=0 wrongpath=0 fuzz=0 max|offset|<=2`, exit 0. This must pass *before* any edit in this task — it is P0 Task 7's exit bar, not this task's.

- [ ] **Step 2: Study the real, post-P0 seed-resolution path** — read the applied tree at `.rehearse/canvas-spoofing.patch/tree`:
  - `dom/canvas/OffscreenCanvas.cpp` — P0 Task 7's anchor map specifies the reimplemented seed resolution walks `GetOwnerGlobal()`/`GetRelevantGlobal()` → window → `GetExtantDoc()` for the main-thread case, plus the existing `GetCurrentThreadWorkerPrivate()` call for the worker case. Read what P0 Task 7 actually landed (not what this plan predicts) and locate the exact function/method name it exposes.
  - `dom/workers/WorkerPrivate.h` (fetch fresh from `FIREFOX_152_0_4_RELEASE` via the same `FETCH` mechanism `rehearse-patch.sh` uses) — the current unmerged patch calls `WorkerPrivate::GetOriginAttributes()` in the worker branch. This has **never been verified** against real FF152 source; it is exactly the class of claim P0 exists to catch. Grep the fetched header for the real accessor name (it may be `GetOriginAttributes()`, `OriginAttributesRef()`, or something else) and use whatever is actually there.
  - `dom/canvas/ClientWebGLContext.h`/`.cpp` — grep for how the class references its owning canvas (`HTMLCanvasElement` vs `OffscreenCanvas`); do not assume a member name.

- [ ] **Step 3: Extend the `ReadPixels` hunk** — replace the `GetOwnerDoc()`-only branch with a resolution that also covers the OffscreenCanvas/worker case, delegating to the real accessor found in Step 2 rather than duplicating the walk inline (share one seed-resolution implementation with the 2D/OffscreenCanvas-encode surfaces P0 Task 7 already lands). Delete the now-stale "stay unperturbed for now" comment.

- [ ] **Step 4: Gate**
```bash
FETCH="curl -fsSL" bash scripts/rehearse-patch.sh canvas-spoofing.patch
```
→ `rejects=0 skipped=0 wrongpath=0 fuzz=0 max|offset|<=2`, exit 0.

- [ ] **Step 5: Identifier check** (mirrors P0 Task 7 Step 4 — pre-build, catches fabricated names):
```bash
T=.rehearse/canvas-spoofing.patch/tree
grep -n "CanvasSeedManager::Perturb" "$T"/dom/canvas/ClientWebGLContext.cpp
grep -n "GetCurrentThreadWorkerPrivate\|WorkerPrivate" "$T"/dom/canvas/ClientWebGLContext.cpp "$T"/dom/canvas/OffscreenCanvas.cpp
```
Expected: every new identifier traces to something actually present in the fetched FF152 source from Step 2, not to prose in this plan or the pre-P0 draft patch. Full linkage is proven by compile (Task 7), not by this grep.

- [ ] **Step 6: Commit**
```bash
git add patches/canvas-spoofing.patch
git commit -m "feat(patches): perturb offscreen/worker WebGL canvas readback"
```

---

### Task 7: CI gate — build + prove end-to-end (both suites, evidence)

**Files:** none (dispatch + evidence).

- [ ] **Step 1: Push + dispatch**
```bash
git push -u origin spec/spoofing-patch-hardening
gh workflow run "Build and Release" --repo lang315/camoufox -f build_target=linux-x86_64 --ref spec/spoofing-patch-hardening
```

- [ ] **Step 2: Confirm clean apply** — `gh run view <id> --repo lang315/camoufox --log | grep -iE "FAILED|\.rej|can.?t find file|ignored" || echo "clean apply"` → `clean apply`.

- [ ] **Step 3: build-tester with JSON evidence**
```bash
gh run download <id> --repo lang315/camoufox --name CamoufoxBuilds-linux-x86_64 -D /tmp/cf
cd build-tester && python scripts/run_tests.py /tmp/cf/<bin> --json /tmp/p3.json
python - <<'PY'
import json
r = json.load(open("/tmp/p3.json"))
p = r["persistence"]
assert p["perSignal"]["audio"]["stable"] and p["perSignal"]["audio"]["distinct"], p
assert p["perSignal"]["fonts"]["stable"] and p["perSignal"]["fonts"]["distinct"], p
# Canvas + worker legs only once Task 6 has landed (see Global Constraints sequencing note):
canvas_ready = p["perSignal"]["canvas"]["stable"] and p["perSignal"]["canvas"]["distinct"]
prof = [x for x in r["profiles"] if "results" in x and x["results"]]
worker_checks = (prof[0]["results"].get("workers", {}) if prof else {})
worker_ready = worker_checks.get("workerCanvasHash", {}).get("passed", False)
print(f"audio/fonts persistence PASS; canvas persistence ready={canvas_ready}; worker canvas hash ready={worker_ready}")
if canvas_ready and worker_ready:
    print("P3 ground-truth PASS (full)")
else:
    print("P3 ground-truth PARTIAL — expected if this run predates Task 6 landing")
PY
```

- [ ] **Step 4: service-tester** — `cd service-tester && <documented run command>`; capture pass output.

- [ ] **Step 5: PR** — if Tasks 1–5 ship ahead of Task 6 (see Global Constraints sequencing note), open the PR now with: `go test ./pkg/fingerprint/...` output, rehearse-patch output N/A (no patch touched), CI clean-apply link, `/tmp/p3.json` excerpt showing `persistence.perSignal.audio/fonts` both `{stable:true, distinct:true}` and the *expected* red for canvas/worker with a one-line note why, service-tester pass, `Closes #N` (partial — re-open or follow up once Task 6 lands). Once Task 6 lands, re-run Steps 1–3 and open the follow-up PR with `persistence.passed=true` and `workerCanvasHash.passed=true` plus the same evidence set — `Closes` whatever tracking issue Task 6's PR references.

---

## Self-Review

**Spec coverage (P3 slice):** profile-identity source (`WithProfileID`/`WithUserDataDir`, does not exist today) → Task 1; `canvas:seed = hash(id)` stable across launches, distinct across profiles → Task 2 Step 3 (canvas branch) + Task 3; same derivation extended to `audio:seed`/`fonts:spacing_seed` (generator.go:78-86, drift identically today) → Task 2 Step 3 (all three branches, same commit, rationale stated); offscreen/worker WebGL perturbation via `WorkerPrivate` origin attributes → Task 6, explicitly gated on P0 Task 7 per the spec's own dependency note; build-tester persistence/worker deliverables (cross-session hash stability, cross-profile distinctness, worker-canvas-hash) → Tasks 4 and 5; both suites + evidence PR + issue → Tasks 0, 7.

**Dependency handling:** the P0→P3 dependency is scoped precisely, not blanket-applied — only Task 6 (C++) and the canvas/worker legs of Tasks 4/5's collectors are blocked; the goapi option surface, seed derivation, Go tests, and the audio/fonts legs of the persistence collector are independently shippable today because `audio-fingerprint-manager.patch` and `anti-font-fingerprinting.patch` were never part of P0's fabrication findings (verified by grep, not assumed). Task 6 re-verifies the dependency at execution time (Step 0) rather than trusting this plan's point-in-time snapshot.

**No fabrication:** Task 6 is written as an investigate-then-implement task (fetch real FF152 source via P0's harness, grep for real identifiers, gate on rehearsal + compile) rather than literal C++ hunks, because the target file's post-P0 real content does not exist yet to quote. Tasks 1–5 (Go/TS) contain literal, committable code because those target files were read in full and verified against the actual repo state on this branch.

**No new schema surface:** `canvas:seed`, `audio:seed`, `fonts:spacing_seed` are already registered in `settings/camoucfg.jvv` and `settings/properties.json` (verified by grep) — confirmed no P3 task needs to touch either schema file, unlike P1/P2.

**Known limitations (out of scope for P3):** real Firefox-profile-level persistence of cookies/history via `WithUserDataDir` is wired (the CLI arg) but not itself proven by a dedicated automated check beyond Task 1 Step 5's manual smoke note and Task 7's overall build/launch success — a full cookie-survives-relaunch test is a reasonable P4-or-later addition, not required by this phase's exit criteria (which are about noise-seed stability, not full session state). `WithFingerprintOverride` is not updated to carry `ProfileID` — a caller combining both options will not get deterministic seeds; flagged here, not silently fixed, since the spec's Task 1 scope names only `WithProfileID`/`WithUserDataDir`.
