# Sync `lang315/camoufox` with upstream `daijro/camoufox` — strategy & runbook

**Status:** APPROVED 2026-07-18 — D1=**C curated**, D2=**upstream-wins**, D3=**hold #30, fold into sync**.
Executing Phase 0–3 on branch `sync/daijro-beta.28` (safe, no `main` touch). Phase 4–5 (`make dir`
rejects=0 + build) and the merge-to-`main` PR remain gated.
**Author:** campaign, 2026-07-18. Advisor unavailable this session.

---

## 1. Situation (measured, not assumed)

| Fact | Value |
|---|---|
| Firefox base | **Same** — both `152.0.4`. Not an FF-version bump. |
| Release delta | lang315 `beta.25` → daijro `beta.28` (3 releases) |
| merge-base | `f342c20` "Version 152.0.2 Upgrade (#658)", 2026-07-05 |
| lang315/main ahead | **+115 commits**, 212 files |
| daijro/main ahead | **+40 commits**, 47 files |
| Dual-touched files | **21** |
| Hard conflicts (`git merge-tree`) | **13** |
| Clean auto-merges but both touched (semantic-dup risk) | 8 |

Because the FF base is identical, patches still target the same source — this is a
**reconciliation of divergent work**, not a rebase onto a new Firefox tree.

### The core problem: duplicate fixes
The fork's campaign and upstream **independently fixed many of the same bugs**. A naive
`git merge` produces 13 conflicts precisely where both sides fixed the same thing:

```
.github/workflows/build.yml            patches/timezone-spoofing.patch
additions/juggler/TargetRegistry.js    patches/webrtc-ip-spoofing.patch
additions/juggler/content/PageAgent.js pythonlib/camoufox/async_api.py
additions/juggler/protocol/PageHandler.js  pythonlib/camoufox/server.py
assets/macos.mozconfig                 pythonlib/camoufox/sync_api.py
patches/playwright/0-playwright.patch  scripts/copy-additions.sh
patches/screen-spoofing.patch
```
Clean-but-both-touched (semantic audit needed — text merges, logic may duplicate):
`fingerprints.py`, `utils.py`, `virtdisplay.py`, `MaskConfig.hpp`, `Makefile`,
`scripts/patch.py`, `settings/camoufox.cfg`, `settings/properties.json`.

---

## 2. What upstream brings that we genuinely want (net-new, no dup)

- `c37a899` **FF152 juggler API-drift**: screenshots, popups, touch, popup-window close.
- `patches/font-system-fonts-css2.patch` — **new** (292 lines).
- `patches/webrtc-ip-spoofing.patch` — major rework (+412).
- `patches/screen-spoofing.patch` — rework (−376 simplified).
- `15f2912` restore **humanized mouse trajectory** dropped in FF146 migration (#677) + regression test.
- `94ed8c7` **getResponseBody** on ORB-decompressed responses (#648).
- `patches/sessionstore-popup-close-crash.patch` — **new** crash fix.
- `5bf8081` **server launch on Playwright 1.60** (#656) + `test_server.py`.
- `0e4151f` **new_page() hang under spoofed window dims (#666)** — removes the browser-init
  documentElement pin (see §5, entangled with our #192).
- `fbf3196` `disableInstantAnimations` opt-out flag; `voices.json` +134; GUI/version-pin fixes.
- CI: `26ec23a`+`d577d7f` ccache-as-optional-dep + OOM/source-wipe fixes; pypi publish workflow.
- Drop Linux i686 (future); pythonlib → 0.5.4.

---

## 3. Duplicate-fix matrix — dedupe decision (recommend **upstream-wins** for shared)

| Bug | Our work | Upstream | Recommendation |
|---|---|---|---|
| #657 timezone RangeCache | PR #25 `timezone-spoofing.patch` | `a39cf9f` | **take upstream**, drop our patch edit (same root cause, theirs is canonical) |
| ccache CI | PR #24 `build.yml` | `26ec23a`+`d577d7f` | **take upstream** (also fixes OOM + source-wipe) |
| Xvfb leak on launch-fail | PR #28 `#363` async/sync | `71fe028` | **take upstream** (SIGKILL + X11 lock/socket cleanup — more complete) |
| server launch guard | PR #27 `#161` | `5bf8081`+`ab20eca` | **reconcile both** — ours = persistent_context ValueError; theirs = PW1.60 + exit-code |
| fingerprint clamp #118 | PR #28 | 1 commit touches `clamp_window` | **reconcile** per-fix |
| fingerprints #141/#287/#328 | PR #28 | `fingerprints.py` +300 rework | **reconcile** — audit for dup/contradiction |
| window dims #192 | PR #30 (in-flight) | `0e4151f` (#666) | **complementary** — combine (see §5) |

---

## 4. Fork-unique work to PRESERVE (upstream does NOT have)

- **tracking-observer feature** — the fork's own dev (observer hooks in `TargetRegistry.js` /
  `PageAgent.js`, navigator/screen/fonts/audio/webrtc surfaces). *The reason the fork exists.*
  ⚠ May have unmerged commits on local `feat/tracking-observer` beyond origin/main — verify.
- **#29 EventWatcher/awaitTopic timeout** (`Helper.js`) — upstream untouched → **no conflict**, keep.
- **#148 occlusion prefs** (`camoufox.cfg`) — upstream added none → **unique**, keep.
- **#192 resizeTo stale-read** (single authoritative resizeTo) — combine with upstream pin-removal.
- **#473 Accept-Encoding**, **#589 merge_geo** — upstream untouched → keep.

---

## 5. The #192 / #666 entanglement (browser-init.patch)

Both sides edit the same resizeTo block, for **different bugs**:
- **Upstream `0e4151f`**: removes `documentElement.style.setProperty('width'/'height')` +
  `browser.style...` **pinning** → fixes the `new_page()` **hang** (#666: pin caps content
  viewport → Juggler `awaitViewportDimensions` deadlocks, no timeout). Keeps the two
  stale-reading `resizeTo` calls.
- **Ours (#192)**: resolves both dims up front + **single** `resizeTo` → fixes stale-read
  (chrome cut off). **Keeps the pin** upstream identified as the hang's root cause.

**Correct merged form = upstream's pin-removal + our single-resizeTo:**
```js
// outerWidth/Height already spoofed in C++ (fingerprint-injection.patch) — only resize, no pin.
let outerWidth = ChromeUtils.camouGetInt("window.outerWidth"),
    outerHeight = ChromeUtils.camouGetInt("window.outerHeight");
window.resizeTo(outerWidth || 1280, outerHeight || 1040);   // single call, no window.outer* read-back
browser.style.setProperty('box-sizing', 'content-box');
```
→ fixes **both** #666 (no pin) and #192 (no stale-read).

---

## 6. Strategy options

**A. Direct merge** `upstream/main → main`, resolve 13 conflicts in place.
- + standard, full history. − ties 115+40 divergent histories in one commit; semantic-dup risk in the 8 clean files goes unreviewed; patch files may text-merge yet fail `git apply`.

**B. Rebase fork-unique onto upstream/main** (reset base to daijro, cherry-pick only unique).
- + cleanest linear "upstream + our delta"; drops all dup work. − must classify all 115 commits; rewrites history; heaviest.

**C. Curated integration on a branch (RECOMMENDED).**
- Integration branch; `git merge upstream/main`; resolve each conflict by a **per-file policy**
  (patches → upstream; juggler → hand-merge observer+drift; CI → upstream; pythonlib → reconcile;
  cfg → union); **audit the 8 clean-merge files for semantic dup**; gate on `make dir` rejects=0 +
  both suites + a build; PR to main with evidence.
- + keeps fork-unique, adopts upstream-canonical, dedupes, reviewable. − most per-file judgment.

**Recommendation: C.** daijro is the upstream maintainer — their shared-fix versions are canonical
and will keep being maintained; carrying our parallel versions guarantees perpetual conflict. C
preserves the observer feature and dedupes correctly.

---

## 7. Runbook (Option C)

- **Phase 0 — prep.** `upstream` remote + fetch: **done**. Create `sync/daijro-beta.28` off `origin/main`.
- **Phase 1 — merge.** `git merge upstream/main` → expect 13 conflicts. Do NOT commit yet.
- **Phase 2 — resolve conflicts** per §3/§4/§5 policy:
  - Patches (`timezone`, `screen`, `webrtc`, `playwright/0-playwright`): **take upstream** (`--theirs`), then re-apply fork-unique patch deltas only if upstream lacks them.
  - `browser-init.patch`: hand-merge to §5 combined form.
  - juggler (`TargetRegistry`, `PageAgent`, `PageHandler`): **hand-merge** — upstream FF152 drift + our observer hooks. Highest care.
  - `build.yml`: **take upstream**; drop our #24.
  - pythonlib (`server`, `async_api`, `sync_api`): reconcile (ours ValueError guard + Xvfb-on-fail vs their PW1.60 + SIGKILL cleanup).
  - `copy-additions.sh`, `macos.mozconfig`: take upstream unless it drops a fork-unique input.
- **Phase 3 — semantic audit** of clean-merge files: `fingerprints.py`, `utils.py`, `MaskConfig.hpp`,
  `camoufox.cfg`, `properties.json`, `patch.py`, `Makefile`, `virtdisplay.py`. Look for duplicated or
  contradictory logic a text-merge silently accepted (esp. `fingerprints.py` +300 vs our #118/#141/#287/#328).
- **Phase 4 — `make dir` → rejects=0** (CRITICAL). A textually-merged `.patch` can still fail to
  apply to FF152 source. Any reject → regenerate that patch via the developer workspace.
- **Phase 5 — verify.** build-tester ≥1000 (needs `playwright==1.55.0`) + `PYTHONPATH=pythonlib
  python3 -m pytest` green + one CI build. Confirm #29/#148/#192/#473/#589 fixes survive; confirm
  observer feature still works.
- **Phase 6 — version.** Bump `upstream.sh` to `beta.28` (or one past, e.g. `beta.29`, to mark the
  fork's post-sync line). Reconcile `pyproject.toml` pythonlib version.
- **Phase 7 — PR** `sync/daijro-beta.28 → main` with the full evidence bundle. Large, but a sync PR
  is one where the reviewer verifies intent + gates, not every line.

---

## 8. Decisions needed (finalize the plan)

- **D1 — Go-forward posture.** Track upstream (adopt canonical fixes, contribute unique work back) vs
  stay independently diverged. *Recommend: track upstream.*
- **D2 — Dedup policy.** Upstream-wins for shared fixes (retire our redundant campaign patches
  #24/#25/#363), keep only fork-unique. *Recommend: yes.*
- **D3 — In-flight PR #30 (#192/#148).** Let the running build finish (evidence that both work on
  FF152), then **hold the merge** and fold #192 into the §5 browser-init reconciliation; #148 is
  pure-additive and survives either path. *Recommend: hold #30, fold into sync.*

---

## 10. Per-conflict resolution map (measured fork-Δ vs upstream-Δ)

13 conflicts on `sync/daijro-beta.28` (merge materialized, main untouched). `Δ = added+deleted since base`.

| File | fork-Δ | upstr-Δ | Resolution |
|---|---|---|---|
| `patches/timezone-spoofing.patch` | 8+1 | 10+2 | **take upstream** — pure #657 dup, our edit superseded. ✅ done |
| `.github/workflows/build.yml` | **205**+30 | 12+3 | **keep FORK** (campaign CI rewrite: ccache job env, cache step, `build_target` input, macos leg) + graft upstream's OOM/ccache-as-optional bits. *(plan §3 said take-upstream — WRONG, corrected here.)* |
| `patches/screen-spoofing.patch` | 12+3 | 24+**352** | take upstream (big rework) + re-graft fork's 12 if unique (check observer screen-hook). |
| `patches/webrtc-ip-spoofing.patch` | 7+2 | **353**+59 | take upstream (big rework) + re-graft fork's 9 if unique. Fork webrtc-patch delta is small (most fork webrtc work is elsewhere). |
| `patches/playwright/0-playwright.patch` | 21+3 | 53+3 | reconcile — upstream PW1.60 server fix + fork's 21 (juggler). |
| `additions/juggler/TargetRegistry.js` | 2+1 | 58+4 | take upstream + graft fork's 2-line observer hook. |
| `additions/juggler/protocol/PageHandler.js` | 2+1 | 61+9 | take upstream (FF152 drift) + graft fork's 2 lines. |
| `additions/juggler/content/PageAgent.js` | 13+11 | 51+13 | **hand-merge** — observer hooks (13) + upstream FF152 drift (51). |
| `pythonlib/camoufox/server.py` | 38+0 | 12+9 | **reconcile** — our #161 ValueError guard + upstream PW1.60/exit-code. |
| `pythonlib/camoufox/async_api.py` | 28+14 | 14+1 | **reconcile** — keep our AsyncCamoufox teardown + #363; take upstream Xvfb refinement. |
| `pythonlib/camoufox/sync_api.py` | 22+11 | 14+1 | reconcile (mirror async). |
| `assets/macos.mozconfig` | 25+2 | 3+2 | keep fork (25) + graft upstream's 3 (macos SDK). |
| `scripts/copy-additions.sh` | 15+3 | 9+1 | reconcile (ensure no fork input dropped). |

Only 1/13 is blind-mechanical. The rest need the actual hunks read — a focused pass, gated by
`make dir` rejects=0 (patch re-grafts must still `git apply`). Merge is abortable/reproducible anytime
(`git merge --abort` / re-`merge upstream/main`).

## 9. Risks

- **Patch text-merges but fails `git apply`** → `make dir` rejects. Mitigation: Phase 4 gate; regenerate via developer UI.
- **Semantic dup in clean-merged `fingerprints.py`** → duplicate/contradictory fingerprint logic passing tests by luck. Mitigation: Phase 3 audit.
- **Observer feature vs upstream juggler drift** → runtime breakage invisible to text-merge. Mitigation: juggler hand-merge + build-tester + observer smoke.
- **Scope**: this is days of careful work across ~21 files, not a quick merge. Sequence it; don't rush Phase 4/5.
- **Local unmerged observer commits** on `feat/tracking-observer` beyond origin/main could be missed. Mitigation: classify local branch vs origin/main before Phase 1.
