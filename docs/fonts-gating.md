# Font gating: status and measurements

Moved out of `CLAUDE.md` so it loads only when font work needs it. Lesson
numbers refer to `CLAUDE.md`'s "Verifying spoofing claims" section. `CLAUDE.md`
keeps a short lesson 5; the first section below is its full text, which is what
code comments citing "CLAUDE.md lesson 5" (smoke.yml, probe_windows_fonts.py)
lean on.

> **Line numbers below are beta.31 (Firefox 152), except where labelled
> beta.32.** The tree is now Firefox 156 (beta.32) and the unlabelled ones have
> not been re-measured; re-anchor before citing one.

## The per-context gate fails open (lesson 5)

`gfxFontGroup` caches its user context id once in its constructor, through
`FontListManager::ContextIdFor`: provider → `GetDocument()` → the document's
principal (`RoverfoxStorageManager::UserContextId`), or, when the provider has
no document, the current worker's origin attributes — each hop failing silently
to 0. `CamouIsFontAllowed` treats context 0 as
"no per-context list" and **returns `true`, allowing every family**. It never
consults the launch-level `fonts` key: that question is answered separately by
`MaskedFontListBlocks` / `MaskConfig::IsFontAllowed`, at the sites that carry a
`FontVisibilityProvider`. So a failed context id is not caught further down —
nothing re-asks the question this gate could not answer. Two separate hops of
that chain have already been found failing
(`OffscreenCanvas::GetDocument()` off-main-thread; #83 turned out to be a cache,
not a hop). Fixing individual hops does not close the class — but the class is
narrower than this paragraph first read (#105, smoke run 34698688879 on build
34578327006, arm `(ctx105)`). On the beta.32 tree four sites ask this gate with
no `MaskedFontListBlocks` beside it — both `GetFontList` branches
(beta.32 `gfxPlatformFontList.cpp:1426`, `:1444`), `GetFontFamilyList`
(beta.32 `:1467`) and `CommonFontFallback`'s non-shared branch (beta.32 `:1730`) — and under a launch mask
none of them can serve a masked family to a page: `GetFontList` is reached only
by the chrome font enumerator, and `GetFontFamilyList` and the non-shared branch
are dormant while `gfx.e10s.font-list.shared` is true (default `true`, beta.32
`StaticPrefList.yaml:7770-7773`, `mirror: once`, overridden nowhere in
`browser/settings/`, `browser/additions/`, `browser/assets/`, `python/src/` or
`typescript/src/`). The fifth site of the beta.31 reading,
`LookupInSharedFaceNameList` (beta.32 `:1144`), asks both halves through
`CamouIsFamilyAllowed` since #150, which also let `local()` reach it:
beta.32 `gfxUserFontSet.cpp:483-493` drops a `local()` face whose resolved family the
launch mask blocks. Every *other* live lookup
site pairs the gate with `MaskedFontListBlocks`, which answers from the document's
`FontVisibilityProvider` and never from the context id, and asks *first* —
`CamouIsFamilyAllowed` is `!MaskedFontListBlocks(...) && CamouIsFontAllowed(...)` —
so the fail-open gate is never reached for a masked family. Measured on the
codepoint-fallback path, U+1F600 → Twemoji Mozilla under a mac launch list, on the
Linux bundle conf: a bare `new_context()` and a persistent context (userContextId 0
per `browser/additions/juggler/TargetRegistry.js:1241-1242` at HEAD; its own `CAMOU-FL pref-fallback ctx=0` line is
consistent with that, though a `ctx=0` line cannot distinguish a genuine id 0 from
a hop that failed to it) both drew a missing glyph (checksum 524399160, against
4262204629 unmasked), the browser's own system-fallback line read
`(textrun-systemfallback-global) … match: [<none>]` — so `CommonFontFallback` ran
and found nothing — and no `CAMOU-FL gate` line for Twemoji appeared under the
mask; the unmasked launch showed this gate answering `ctx=0 hasList=0 key=twemoji
mozilla allowed=1`, attributable to the emoji pref-list population at
`camouUnfiltered(0)` (the only forced-0 scope on that path; the line carries no
call-site tag), which is the fail-open doing what that scope intends. What a
listless or misresolved context loses is only its own per-context list, and
context 0 cannot carry one because chrome documents share id 0 — denying at 0
would mask the browser's own UI. What `(ctx105)` cannot see: the macOS conf, where
Apple Color Emoji serves U+1F600 legitimately and would mask a Twemoji leak; and,
because the gate line has no call-site tag, whether `CommonFontFallback`'s own gate
was reached — that half rests on the caller reading above. A pixel "tofu floor"
across codepoints does not exist — a missing glyph is a hexbox carrying its own
codepoint's digits (beta.32 `gfxFontMissingGlyphs.cpp:487-520`) — so refusal is read from
the browser's fallback and gate lines, not from pixels. The check that
generalises: before calling a fail-open gate a leak, enumerate every gate above it
and which one asks first — a short-circuited pair, or a caller that refuses the
whole lookup, can make the fail-open unreachable for the case you care about, and
a bare "the gate allows everything" reading will not show you either.

## Font read paths: gating status

**Font read paths known to be ungated** (as of the #44 review; check before
assuming a font change is complete): `SystemFindFontForChar` /
`GlobalFontFallback` / `CommonFontFallback`; `FontFaceSet::InsertRuleFontFace`;
worker + `OffscreenCanvas` (`GetDocument()` is null off-main-thread, so the
context id falls to 0); `LookupLocalFont` / `LookupInFaceNameLists` (matched by
full/PostScript name, not family key).

`fix/44-fonts-h2` (PR #84) closed four of those entries: codepoint fallback
through `CommonFontFallback` and `GlobalFontFallback`, which
`SystemFindFontForChar` reaches — smoke arm (f); the CSS `@font-face` path,
gated in `FontFaceImpl::SetStatus`, which `FontFaceSet::InsertRuleFontFace`
reaches during style flush — arm (e); the worker and `OffscreenCanvas` context
id, given a real value from `WorkerPrivate` — arm (g); and face-name lookup
through `LookupInSharedFaceNameList` — arm (h).

The `@font-face` entry is closed **in the shape arm (e) measures**, not by a
scope — `InsertRuleFontFace` still carries no `AutoFontListContext`, per lesson
2 in `CLAUDE.md`. What backs it is smoke run 34213805428, where the same three CSS rules
got opposite per-context `FontFace.status` answers: the mac context reported
`Segoe UI` error and `Helvetica Neue` loaded, the win context the reverse, both
matching arm (b)'s per-context ground truth. The arm's own discriminator in that
run named the defect a quoted family key rather than a missing context scope.
Treat any different shape as unmeasured.

PR #93 gated the two fallback caches by reading — `mCodepointsWithNoFonts` per
context, and the U+FFFD `mReplacementCharFallbackFamily` hit — and removed the
`@font-face` gate for faces that carry a `url()` source (#80).

Round 3 (`fix/fonts-round3`) closed four more, and the distinction between
"gated and measured" and "gated by reading" matters for each:

- **The pref-font memo read path (#94).** `GetPrefFontsLangGroupLocked`
  populates under `AutoFontListContext ctx(0)`, so the memo's per-context
  contents no longer depend on who missed first; the launch mask still applies
  at population. Both consumers filter at read.
  `WhichPrefFontSupportsChar` is **measured** on Linux (smoke arm (n1), run
  34544934746: the probe moves from Tinos's own 33 to its own floor 43 with
  `pref-fallback ctx=6 key=tinos allowed=0`; the Linux conf now answers
  `serif` with Noto Serif first, which arm (n1) reads). `AddGenericFonts`' half is
  **gated by reading only** — on the runner it is reached for `system-ui` and
  `x-math` alone.
- **Generic family to family map under a per-context list (#92).**
  `CamouGenericCandidate` resolves an ordered table intersected with the
  context's list, consulted by `FindGenericFamilies` before the fontconfig loop
  and by `AddGenericFonts` on the DWrite/CoreText path. **Measured** on Linux
  (arm (n2): 215/215/215 becomes 215/305/280 with one `generic-map` line per
  generic). `system-ui` (`generic=7`) went unmeasured that round and was
  broken by it (#131): the table step answered it with the sans row and
  returned before the #599 hook ran, on Linux as well, because
  `gfxFcPlatformFontList::AddGenericFonts` delegates `system-ui` to the base
  class. `system-ui` now skips the table and is answered by the pref path, as
  in stock, in two cases. For a spoofed macOS, Windows or Linux identity, the
  pref path answers from system-ui-font-spoofing's per-OS cell
  (`GetSystemUIFontFamilies`: Helvetica, Segoe UI, Ubuntu), when the list
  allows that name and the face it resolves to; a refused family falls back
  to the table. A native identity (`SystemUISpoofedOS` is `None`) always takes
  the stock path, and stock's own system-ui family is exempt from the read
  filter (#263): it is the OS's own family, which no font list names, and on a
  Mac it is the hidden `.SF NS` that the name `-apple-system` resolves to. Until
  #263 it was filtered like every pref font, so a macOS identity on a Mac got no
  family for `system-ui` and drew the default serif, while the CSS name
  `-apple-system` (answered by `CoreTextFontList::FindAndAddFamiliesLocked`
  before the mask) still drew San Francisco. The exemption has two
  sites, and exempts only what `GetSystemUIFontFamilies` names. The name lookup
  in `gfxPlatformFontList::FindAndAddFamiliesLocked` skips both refusals for
  that name (`CamouIsNativeSystemUIName`), which matters on a platform without
  CoreText's early answer, such as DirectWrite on Windows. The pref loop in
  `AddGenericFonts` then skips the read filter for the family that name resolved
  to (`CamouIsNativeSystemUIFamily`), and its `pref-fallback` line reads
  `allowed=1 exempt=native-system-ui`. Every other name and pref family still
  goes through the mask. `WhichPrefFontSupportsChar` is left as it was: a family it
  would offer for a system-ui run is the one the primary lookup already tried.
  Either way the `step=system-ui` line names the family system-ui got, or
  `none`. The OS is the context's own (`NavigatorManager::GetSpoofedOS`)
  first and the launch's second (#138). A worker asks through its own origin
  attributes (`FontListManager::ContextIdFor`). A launch's fontconfig search
  path holds only the font groups its own OS reads (`utils._generate_fontconfig`,
  `docs/FONTS.md`), so a context whose OS differs from the launch's never sees
  that OS's exclusive faces (`Helvetica`, `Helvetica Neue`, `Menlo` and `Times`
  are all in the macOS-only group, read from `groups.json` in
  `fonts-bundle-v1`), and the Windows conf rewrites `Helvetica` to `Arial`
  before the gate. In a Windows launch the macOS context's step therefore
  takes the hook only when its list also admits `Arial` (a face the Windows
  groups carry), and its `step=system-ui` line then names the family the
  rewrite produced; that is read from the code, and the guard's mixed-OS arm
  is the measurement. It reads that line, not a width. The measurements below
  predate the line naming the family got, and read `key=helvetica`.
  **Measured** on Linux by probe run 35591973853 on build 35586323562, and
  the context-first read by probe run 35698448037: a macOS context in a
  Windows launch logs `step=system-ui key=helvetica` on build 35696007399
  against `step=row key=helvetica neue` on build 35586323562
  (`fix/131-system-ui-step` @ `b07537f`, browser inputs equal to main's), in the
  whole-bundle search path that preceded per-OS grouping.
  The guard's Windows arm cannot discriminate, since Segoe UI is also the
  sans row's first choice there. The proof is the `CAMOU-FL generic-map ...
  step=system-ui` log line, not the guard's widths — on the Linux bundle
  `Sans` also measures 648, so the guard's macOS arm cannot see a leak to
  `Sans` either. A generic under a list still yields one family where
  upstream gave up to three.
- **The same table under a launch-only mask (#162).** Before #162 the table
  answered only a context with a list of its own. A context under the
  launch-level `fonts` mask alone resolved its generics through the host's
  `font.name-list.*` prefs, which the mask refuses when the spoofed OS differs
  from the host, so `monospace` fell to a proportional face. All four sites
  (`CamouGenericCandidate`, `FindGenericFamilies`, `AddGenericFonts`,
  `GetDefaultFontLocked`) now ask `CamouGenericTableApplies`: a list of its own,
  or `MaskedFontListAppliesTo` for the provider. A chrome or provider-less
  lookup is still exempt, as it is from the mask itself. The table
  answers before the launchers' own #162 prefs, so a launch-only identity now
  gets the same generic a per-context list gives it.
- **No cached miss while cmaps load (#165).** With async fallback on,
  `GlobalFontFallback` skips every family whose cmap is not loaded yet, and
  upstream cached the resulting miss in `mCodepointsWithNoFonts`. In the
  first content process of a launch, that answered every later lookup of the
  character with a hexbox until the parent had loaded every cmap, 1 to 10 s
  after launch.
  - `SystemFindFontForChar` no longer caches a miss when the scan skipped a
    family (`mCamouFallbackCmapsPending`). The next lookup scans again.
  - The first lookup still misses. The launchers close that by turning async
    fallback off for any identity except a native mac or win one.
  - Guarded by `fallback-miss-while-cmaps-load.py`, which reads the
    `global-fallback` lines.
- **`gfxFontGroup::GetDefaultFont`'s scope and shared-list walk, plus
  `GetDefaultFontLocked`'s two last resorts (#88).** What is **measured** is
  that a refusing context never reaches `GetDefaultFont` at all (arm (h3), shape
  B: no `default` line for the context, `generic-map` naming three in-list
  families). The gated walks themselves are **reasoned from the code**:
  `default` and `default-unfiltered` both read 0 run-wide.
- **`FontFaceLoadStatus` for non-local faces (#91).** **Measured**, three
  observables: the 404 face goes `loaded` to `error`, the control stays `loaded`
  at 1920, and `/nope.ttf` joins the fetched-path list.

Every gate-approved last-resort walk now has an **unfiltered tail**: if the walk
finds nothing it returns the unfiltered family upstream would have returned and
logs `CAMOU-FL default-unfiltered`. That line therefore fires only on fail-open,
so **zero is the healthy count** and a non-zero one is a finding. The tail is
deliberate: a gate that finds nothing must not turn `family.IsNull()` into a
release-build null dereference at `gfxTextRun.cpp:2207-2221`.
`GetFontFamilyList`'s existing unfiltered refill is the precedent.

**DirectWrite family substitution (#193).** `gfxDWriteFontList::FindAndAddFamiliesLocked`
swaps a requested name for its substitute (`sDirectWriteSubs`, `kFontSubstitutes`,
the registry `FontSubstitutes` key) before the base-class gates run. Its
non-shared branch returns the substitute without reaching them at all. So both
gates were asked about `Times New Roman` when a page asked for `MS Serif`.
Substitution is Windows behaviour, so the new check is scoped by the context's
spoofed OS, resolved as in system-ui (`NavigatorManager::GetSpoofedOS` of
`FontListManager::ContextIdFor`, with chrome excluded first).
- Under a macOS, Linux or other identity, both branches ask
  `CamouIsFamilyAllowed` about the requested name. If it is not allowed, they
  refuse and log `CAMOU-FL dwrite-subst os=<n> key=<name> allowed=0`.
- A Windows identity, a lookup with no identity, and chrome keep stock
  substitution exactly.
- Stock substitution is itself skipped when the original family is available.
  `AddSubstitute` returns early when the shared list already holds the name
  being substituted (`gfxDWriteFontList.cpp:2166-2174` at
  `FIREFOX_158_0_1_RELEASE`), and `GetDirectWriteSubstitutes` does the same
  (`:2222-2230`), unless `gfx.windows-font-substitutes.always` is true
  (`StaticPrefList.yaml:7872`, default false). The bundle holds `Helvetica`
  (`27__Helvetica.ttc`), `Times` (`69__Times.ttc`) and `Courier`
  (`78__Courier.ttc`), so on a bundle-active launch those names are never
  substituted. In a Windows launch the bundle is inactive
  (`mStockFilesOnly`, `font-hijacker.patch`), the early return does not apply,
  and the `kFontSubstitutes` row `Helvetica` to `Arial`
  (`StandardFonts-win10.inc:232`) can take effect (#325).

This is **gated by reading**. The measurement will be e2e `fonts_no_foreign_os`
on a Windows host.

Still ungated after round 3: `CoreTextFontList::FindSystemFontFamily`'s return
on the macOS system-font path; and the non-shared `LookupInFaceNameLists` /
`CommonFontFallback` `else` branches, both dormant while
`gfx.e10s.font-list.shared` is true; and the
**context-0 fail-open** for the per-context half only — the launch mask reaches
context 0 on the codepoint-fallback path, measured by `(ctx105)` on U+1F600 under
the Linux bundle conf, and at the remaining live sites by reading the callers
(lesson 5, above). The macOS host
was unmeasured until #148; see "macOS host (#148)" below. #82 is closed by measurement on Linux (Firefox 152) — arm (n4) GREEN
on run 34544934746 against a RED on run 34544937587, a build differing by one
statement — but arm (j2), its bare-donor variant, is still unmeasurable on this
bundle, so it rests on one arm.

## Legacy family names: first lookup (#247, #319, #321, #322)

A legacy family name (name ID 1, such as `DejaVu Sans Condensed`) is an "other family name" that Firefox loads lazily. `font-other-names-sync.patch` reads the names on a masked page's first lookup. On Windows, `FontList::FindFamily` has a branch (`SharedFontList.cpp:1234-1317`) that strips the name's last word, reads the base family's face names once, and answers an alias hit with the base family's regular face before the load; a second name with the same base then misses ("already read") and reaches `InitOtherFamilyNames`, which stock defers to an idle task. The patch computes one predicate for both the lookup and the deferral: the page is masked and the names are not yet loaded and, on `XP_WIN`, the claimed OS is Linux or macOS. A Linux or macOS claim looks up primary names only (so the miss reaches the read) and reads at once. A Windows claim on a Windows host keeps stock Firefox's lookup and deferral (#321), as real Windows gives it. Elsewhere every masked claim reads the names at once. On a macOS host the alias table holds single-face aliases published at startup, so the `XP_WIN` gate keeps primary-names-only away from it.

Known limit: `mOtherFamilyNamesInitialized` is process-wide. Once a Linux or macOS context forces the load, every later lookup in that process, a `windows` context included, gets the real face and not the base-first one. This applies to mixed-OS browsers and is not engineered around. Measured on a Linux launch with a `windows` context and a `macos` context (bug-fixes.md, #319, #321).

### Known gap: a `windows` identity on a macOS or Linux host (#322)

A `windows` identity on a non-Windows host answers a legacy name with its own face on the first lookup. Real Windows answers the base family's face (or nothing) until its loader has run, a minute later by default (`gfx.font_loader.delay` is 60000 ms on Windows, 8000 elsewhere, and Camoufox does not set it). This is a documented gap, not a fix: nothing in the code changes for it.

Both sides were measured, `DejaVu Sans Condensed`, `Light` and `Serif Condensed` as `"<name>", monospace` against `sans-serif`, widths in px:

| | first reading | at 15 s |
|---|---|---|
| Camoufox `v158.0.1-beta.34-fork.1` macOS release (BuildID `20261027060636`, `MacOS/camoufox` sha1 `955b413c46e9059ec1a452d18b517ec092118a0c`), `windows` and `linux` identity, bundled DejaVu | Condensed 468.17, Light 517.95 (both identities, monospace and sans-serif alike) | not re-read; the first reading is already the settled one |
| stock Firefox 158.0.1 on Windows (run 40677114619, job 122778294832, windows-2025; DejaVu installed per user) | Condensed 520.45 (monospace) against 468.08 (sans-serif), Light 435.42 against 468.08, Serif Condensed 475.73 against 468.08 | Condensed 468.17, Light 517.95, Serif Condensed 475.73, identical in 3 of 3 launches |

The macOS reading is the browser the user ships on a Mac; it carries launcher `camoufox` from the same release, and the binary was matched to the release asset by sha1.

**How many names this could show on.** Read from the launcher's Windows font data (`python/src/camoufox/fonts.json`, key `win`), not measured: 335 names, 72 whose base (the name minus its last word) is also listed, and 47 of those in 15 base groups of two or more. That count is an upper bound, because some of them are primary families of their own (`Segoe UI Emoji`, `Noto Sans Arabic`, `Roboto Mono`). Examples: `Segoe UI` with Black, Light, Semibold, Semilight, Historic, Symbol, Variable and Emoji; `Yu Gothic UI` with Light, Semibold and Semilight; `Yu Gothic` with Light, Medium and UI; `DejaVu Sans` with Condensed, Light and Mono; `Roboto` with Condensed, Mono and Slab.

**What would see it.** A page that measures a second legacy name of one base family before Windows's loader has run, and compares the answer with what Windows gives. One legacy name alone is not enough: the first lookup is the same on both sides.

**What would close it.** Port the Windows branch of `SharedFontList::FindFamily` and its members (`mFaceNamesRead` and the alias bookkeeping) to the macOS and Linux lists and gate it by the claimed OS. That is a large multi-file patch, measurable only through full macOS and Linux builds, and still inexact (Windows's own loader timing and the order of its face reads). It was not done, and the exposure above is why.

## A context of another OS in a host-OS launch (#320)

A launch whose OS is the host's keeps the bundled fonts of the other OSes inactive: on Windows `MaskConfig::GetSpoofedOS() == Windows` makes `BundledFontFileEnumerator` list only Firefox's own bundled font (`font-hijacker.patch:149-152`), and on macOS `camouNativeIdentity` skips `ActivateBundledFonts` (`font-hijacker.patch:18-22`). The macOS and Linux fonts are in the Windows package (`browser/Makefile`, `package-windows --fonts windows macos linux`; 1513 files in `fonts/`, among them `27__Helvetica.ttc`, `31__HelveticaNeue.ttc` and `35__Menlo.ttc`), but they are never loaded. A context of another OS in such a launch, which exists only when the launch has `canvas_noise=True` (`NewContext` raises `ValueError` for another OS otherwise, `sync_api.py` docstring), therefore has only the host's families that its list admits. Its generics resolve within that list.

Neither launcher warns when such a context is created. Python's `UserWarning` from `warn_fonts_excluded_by_launch` is about the launch font set, and the TypeScript launcher has no equivalent; no warning was added for this.

**Windows host** (issue #320). Run 40727855673 (job 122955936144) and run 40728559218 (job 122958393809), windows-2025 (10.0.26100), `v158.0.1-beta.34-fork.1` win.x86_64, launcher from `main` at 199d4b41. `Camoufox 1.2.3 mmmmmmmmmmlli` at 48px, `"<name>", <generic>`, serif / sans-serif / monospace / cursive:

| Context list | Name | Widths |
|---|---|---|
| `[Helvetica, Helvetica Neue, Menlo, Arial]` | every name, never-font included | 784.05 in all four generics |
| the same plus `Segoe UI, Courier New, Consolas` | Segoe UI | 789.12 x4 |
| | Courier New | 806.4 x4 |
| | Consolas | 738.73 x4 |
| | Arial | 784.05 x4 |
| | never-font | 784.05, 784.05, 738.73, 784.05 |

With the four-name list, only Arial has an installed face, so every generic and every absent name resolves to it, and 784.05 is Arial's width. The issue read this as "the page sees no variation at all". Segoe UI, Courier New and Consolas differ from the never-font in the larger list, so the page is not blind. The log agrees: `CAMOU-FL gate ... allowed=1` for every name (nothing is refused), no `default-unfiltered` line, and `generic-map generic=1..4 step=none key=none`, so each generic falls back within the list.

**A control that can differ (lesson 4).** The issue's never-font read 784.05 in every column and looked like "the same face everywhere". It is not a control for Arial: in a Windows identity `sans-serif` resolves to Arial, so the never-font under `sans-serif` equals Arial by construction. Arial is shown to be a resolved face by the serif, monospace and cursive columns of the Windows context in the same browser (never-font 735.97, 738.73, 764.37 against Arial 784.05 in all four). `Helvetica` is metric-compatible with Arial, so this width cannot say which face drew it (#325). `dwrite-subst` logs only a refusal, and that context's list admits both names, so the log cannot produce a line there whether or not substitution ran.

**Counterfactual, bundle active.** Run 40728559218, a macOS launch on the same Windows host: Helvetica Neue 797.13 x4, Menlo 809.2 x4, Arial 784.05 x4, never-font 797.13, 797.13, 809.2, 797.13. The faces the Windows-launch context lacks render when the bundle is active.

**macOS host, mirror.** `v158.0.1-beta.34-fork.1` macOS release (BuildID 20261027060636, `MacOS/camoufox` sha1 `955b413c46e9059ec1a452d18b517ec092118a0c`), run locally on macOS (arm64, Darwin 24.6.0) with a scratch `HOME`, launch `os="macos"` with `canvas_noise=True`, a `windows` context whose fonts are `[Segoe UI, Arial, Courier New]`. Segoe UI [784.05, 784.05, 806.4, 784.05] equals the never-font [784.05, 784.05, 806.4, 784.05] (absent: no Windows faces on a Mac); Arial 784.05 x4 and Courier New 806.4 x4 are the host's. Gate lines `allowed=1` for all three, `generic-map generic=3 step=row key=courier new` and `step=none` for the others, no `default-unfiltered`. The same shape as the Windows case, with the host's families taking the generics.

Not measured: a Linux host, Windows 10, and a context of another OS in a launch whose OS is the host's with the default launcher options (it raises). Whether a Windows context on a Mac should be able to draw Windows-only faces is a design question: the native identity keeps the bundle inactive on purpose.

## Two contexts in one content process (Firefox 156)

The cross-context cache arms (#81, #82, #83) need two contexts whose documents
are laid out by one content process, because the caches they test are
per-process. Firefox 152 gave every `web` document the bare remote type, so
`dom.ipc.processCount=1` with `fission.autostart=false` put two Playwright
contexts in one process. Firefox 156 gives `web` documents the type
`web=^userContextId=<N>` (`SharedWebRemoteType` in `dom/ipc/ProcessIsolation.cpp`),
one process pool per container, whatever those prefs say: in smoke run
36853787702 every pair of contexts, from arm (b) to arm (n5), was laid out by two
processes (read from the pid MOZ_LOG prefixes to each `CAMOU-FL group` line; the
`cfx-child.<n>` file name is shared by several processes and says nothing). The
`file` remote type carries no container and `dom.ipc.processCount.file` is 1, so
arms (b), (b2), (b2r), (i), (i2), (j), (j2), (n4) and (n5) load their two pages
from `file:` URLs and assert that both documents' group lines carry one pid (#179,
#180); a throwaway launch before them proves a `file:` page loads and otherwise
names one SETUP-INVALID. Two processes leave an arm unmeasured. Arms (i), (i2),
(j), (j2) and (n4) check this before their leak verdict. Arms (b), (b2), (b2r) and
(n5) check it after, so a leak seen across processes still counts as a verdict. The disc and pid
probes also use `file:` pages but score nothing; the step prints a non-scoring
`shared-process` line for every pair. Arm (b) closes its donor context before the
recipient exists, and the `file` process did not outlive that in smoke run
38539979038: the pid probe's donor-closed pair saw file process 14601 still listed
right after the close, gone once the recipient's page was ready, and the recipient
in a new one, 14655. So arm (b) is in `KNOWN_UNMEASURABLE` for its cross-context
claim, which (b2) measures with the donor alive. Its per-context narrowing checks
still score.

An arm that installs a one-shot setter (`setFontList`, `setSpeechVoices`) from an
init script and checks it ran on the page under test ((b2r), (n5)) must navigate
`file:` to `file:`. Going from about:blank to a `file:` page switches process, and
across that switch the setter was spent in the file process before the page under
test read it (run 38539979038: `saw=false` on both arms' pages, with the list
installed). Those arms load a first `file:` page, add the init script, then load
the page under test. Variants 1 and 2 of the arm (b)
discriminator still load `data:` pages and print without a shared-process reading.

## macOS host (#148)

Measured on a native macOS arm64 host against build run 35799717143 (`main` at
`781d9dd`, whose compiled inputs equal `72bad59`). The build is the packaged
app, so the font universe is the one that ships: the host's fonts plus the
bundled windows and linux sets. Headless. Probe:
`browser/tests/build-tester/scripts/probe_macos_font_paths.py`.

Each family is measured under two fallbacks that are checked to differ on the
page. A family that renders measures the same under both, and a refused one
tracks its fallback. A positive control that does not render voids its arm.

**Which mask a row measured.** The http page ran in the process that received
the context's list (`set=1`, every lookup `hasList=1`), so those rows measure
the per-context gate. The file page ran in a process that never received it
(`set=0`, every lookup `hasList=0`), so those rows measure the launch mask only.
That split is #149, below.

| Arm | Probe | windows spoof | linux spoof | macos spoof |
|---|---|---|---|---|
| a | `Optima`, a host font on the mac list only, not bundled | refused | refused | renders (forced onto the list as the control) |
| a' | `JetBrains Mono`, user-installed, on no list | refused | refused | refused |
| b | `local()` by full and PostScript name, and bundled Arial (before #150; see below) | all error | all error | all error |
| c | `system-ui`, http page | Segoe UI, but equal to `sans-serif`, so it cannot tell the hook from the row | the `sans-serif` face | Helvetica (952.92), distinct from `sans-serif` (947.83) |
| d | codepoint fallback, from `sys-fallback` / `global-fallback` lines | none resolved off the list | none resolved off the list | none resolved off the list |
| e | `allowed=1` for a family off the context's list | 0 | 0 | 0 |

`CAMOU-FL default-unfiltered` read 0 in every run. Arms (a), (a'), (b), (d) and
(e) read the same on the file page, under the launch mask.

Arm (c) is the first macOS-host reading of the #131/#138 `system-ui` step. The
mac row is the discriminating one: `system-ui` lands on Helvetica, and
`sans-serif` lands elsewhere. The windows row is equal to `sans-serif` on this
host too, which is the ambiguity `browser/tests/playwright/patches/system-ui-font-spoofing.py`
already notes.

**`src: local()` now follows the font-family gate (#150).** Until #150 every
`local()` source failed under a mask: `gfxUserFontSet` skipped `LookupLocalFont`
whenever `MaskedFontListAppliesTo` held, and a `local()`-only face took its
`FontFace.status` from its declared family name. So the table's row (b) above
read "all error", and a face named after an allowed family read `loaded` while
nothing rendered. Stock Firefox Developer Edition 157 on the same host loads
them all. Both were tells.

The lookup now runs, and each platform answers through the same family gate
as `font-family`:

- **macOS:** `CoreTextFontList::LookupLocalFont` resolves the matched face's
  family through `FindFamily`, which carries the launch mask and the
  per-context list. Measured on build run 35846659754.
  - Arial loads under a Windows spoof and is refused under a Linux one.
  - Optima loads only under a mac spoof that lists it.
  - A user-installed family on no list is refused under every spoof.
  - Status agrees with render on every row.
- **Linux and Windows:** the shared face-name list, `LookupInSharedFaceNameList`,
  gates the matched face's family with `CamouIsFamilyAllowed`, which asks both
  halves. Linux is measured by `browser/tests/playwright/patches/local-font-source.py`, red on
  main and green on the fix, and by smoke arms (d), (e) and (h) on run
  35952837490. Native Windows is measured by the same guard, which PASSes on
  every row (see "Native Windows after #149 and #150" below).

`browser/tests/playwright/patches/local-font-source.py` guards all of it. It covers both the
`FontFace` and the CSS `@font-face` rule paths, and it fails when a status
disagrees with what renders.

**The context-0 Helvetica line at process start is not a leak.**
`InitFontList` calls `GetDefaultFontLocked(nullptr, ...)`. On macOS that asks
CoreText for the user UI font, Helvetica, with no provider, so the per-context
gate answers at context 0. The entry this produces, `mDefaultFontEntry`, is
read only at `gfxTextRun.cpp:2213`, after the gated pass and the logged
`default-unfiltered` tail have both failed. The probe counts these lines apart,
as "startup": a context-0 `allowed=1` line counts as a fail-open only after a
list has reached that process, which the setter's process logs as `CAMOU-FL set`
and every other process as `CAMOU-FL flush`.

**A context's list reached only its first content process (#149, fixed).**
This was found here but is not macOS-specific. `setFontList` stores the list in a
per-process static, while its "already called" flag went through
`RoverfoxStorageManager` to every process. So a later page of the same context,
which Fission puts in a new process, never got the list and was answered by the
launch mask. Measured with six pages of one context: the first refused a family
that only the launch list holds, and the other five rendered it. Voices had the
same shape. The fork first fixed it by keeping the flag per process. Since the
upstream sync (#188), both lists live in the same shared store as the flag,
and each process parses them on first use. When a font list reaches a process
that already exists, RoverfoxStorageManager's pref callback flushes that
process's platform font-list memos (`CAMOU-FL flush`): the codepoint cache and
the font-name caches, which may hold answers made before the list arrived.
Font groups that had already resolved their fonts are not flushed. A list over
4 KiB never reached the callback in another process until #231: Firefox syncs
no longer string pref, so the store now writes such a value in chunks and fires
the callback once all of them have arrived. That the
callback fires before the lists are needed is established by reading the code;
the measurement is pending CI.
`browser/tests/playwright/patches/context-list-every-process.py` guards it: every page of one
context, across two origins, must refuse a family that only the launch holds.
It was red on main's browser and is green on the fix, both on Linux CI. Every
other guard reads one page per context, so none of them can see this.

What this cannot see: native Windows (`gfxDWriteFontList`), a headful session,
and CoreText's `FindSystemFontFamily` separately from arm (c), which reads its
result only through `system-ui`.

## Native Windows after #149 and #150

Measured on the user's Windows build PC: Windows 10.0.19045, native Python
3.12.14, Playwright 1.55.0, headless. The build is build.yml run 35968080353,
of `main` at `d558cd3`. Its `BuildID` is `20260924072039` and its `xul.dll`
SHA-256 starts `899ECA649CBA961F`. On Windows the win-list families (Arial,
Georgia, Comic Sans MS) are the host's own fonts, so these rows go through
`gfxDWriteFontList` and its shared face-name list, not through a bundle.

| Check | Result |
|---|---|
| `browser/tests/playwright/patches/local-font-source.py` (#150) | PASS. Arial and an alias load and render, a CSS alias loads and renders, and Georgia (launch only), Comic Sans MS (no list) and a CSS rule on Georgia are refused. Status agrees with render on every row. |
| `browser/tests/playwright/patches/context-list-every-process.py` (#149) | PASS. Three pages of one context on two origins all refuse Georgia; the parent isolates both origins as `WebContent`, and all three content logs installed the list. `getVoices()` reads 50 on every page. |
| `browser/tests/build-tester/scripts/probe_windows_fonts.py` (#87) | 11 of 11 `pass`, `leaked` and `unmeasured` empty. The family-name half matches #87 (absent 817.8834, bare 1261.35, 84 host-only families collapsed). The codepoint half matches too: U+05EF 26.0167 bare, 21.18 and 21.12 under the two masks. |

Neither fix regressed the #87 Windows readings, and the DWrite face-name path
that #150 opened is gated as the code reads.

## A Windows identity's font set against a real Windows 10 machine

Measured on the user's Windows build PC (Windows 10.0.19045, no Office), against
`v156.0.1-beta.32-fork.4` on macOS arm64 with `os="windows"`. Sources: the host's
`System.Drawing.Text.InstalledFontCollection` (GDI families, read-only) for the
real machine; `launch_options(os="windows")`'s `fonts` key, 60 draws, for the
identities; `python/src/camoufox/fonts.json` for the `win` list. This compares
family names only. It does not compare rendering, metrics or codepoint fallback,
and one machine is not a population: it has no Office and no LibreOffice.

| Reading | Result |
|---|---|
| Families the real machine has (118; 3 OEM or developer-tool installs left out) | 115 |
| Of those, not in the `win` list | 22: 11 `Bahnschrift` and 8 `Cascadia` weight and width names that GDI lists as families (DirectWrite groups them under one family), `SimSun-ExtG`, `Wingdings 2` and `Wingdings 3` |
| Fonts per Windows identity | 125 to 282 |
| Families in 40 identities' union that this machine lacks | 207 (Office families such as `Century Gothic`, `Book Antiqua`, `Garamond`; Windows 11 families such as `Segoe UI Variable`; and open-source families) |
| Identities listing at least one open-source family (`DejaVu`, `Liberation`, `Noto`, `Roboto`, `Open Sans`, `Source`, `Meslo` and similar) | 13 of 60, up to 41 families in one identity |
| `win` list entries matching that pattern | 55 of 335 |
| Measured in the browser (macOS host, one identity, 240 families configured) | 214 render, none outside the configured set, 0 of 637 macOS- or Linux-only names present. The 26 not measured are weight names (`Calibri Light`, `Sitka *`, `Segoe UI Variable *`) and the four bitmap fonts (`MS Sans Serif`, `MS Serif`, `Roman`, `Small Fonts`); whether they are absent or only share a baseline's width is not established. |

Where the open-source families come from: four addition units of the per-launch
draw in [`FONTS.md`](FONTS.md) (`libreoffice` 0.066, `web` 0.088, `dev` 0.038 and
`meslo` 0.040 on Windows), each at a probability measured on the fpgen corpus. The
chance of at least one of them is 1 - 0.934 x 0.912 x 0.962 x 0.960 = 0.21, and 13
of 60 draws is 0.22. So the identities carry those families at the rate the corpus
gives. What stays open is whether that rate is right for the traffic a detector
sees, whether the units are really independent (an identity can draw `office` and
`libreoffice` together), and whether the fonts render as the real files do.
A stock Windows 10 has none of them, so this machine says nothing about the rate.
The `Bahnschrift` and `Cascadia` rows are an artefact of GDI enumeration, not gaps.

### Is it a tell? Two checks (#244)

**Against the fpgen model's Windows samples** (4000 draws of `fpgen.generate(os="Windows")`, its `allFonts` node; 10000 draws of the fork's `_generate_random_font_subset("windows")` after #249 re-measured the unit rates). Each unit is detected by the fonts only that unit carries, restricted to the fonts the model probes at all. Units share members (`Roboto` is in both `libreoffice` and `web`), so counting a unit by all its fonts overstates the joint rate by 7x.

| Unit | Model | Fork draw |
|---|---|---|
| `libreoffice` | 0.069 | 0.075 |
| `pan-euro` | 0.027 | 0.023 |
| `office` | 0.527 | 0.511 |
| `hololens` | 0.288 | 0.289 |
| `web` | 0.123 | 0.138 |
| `dev` | 0.014 | 0.015 |

The open-source units that a Windows identity carries are `libreoffice`, `web` and `dev` (on 8 probed fonts); every unit is within 0.016 of the model. `meslo` and `cascadia` have no font the model probes. Before #249 the fork drew `hololens` at 0.595, twice the model's 0.288 (and `office` 0.607, `web` 0.075, `dev` 0.029); #249 measured the rates from the model. Pairs: the fork draws every pair independently, as its ratios of joint to product (0.66 to 1.04) show; the model has `office` with `web` at 1.40 and `web` with `dev` at 4.2, so identities pair web and developer fonts about five times less often than the model does (0.0014 against 0.0073).

**Against the font files** (`Resources/fonts` in the fork.4 macOS build; 69 of 86 open-source families have a regular, upright, Latin-complete face; width of `HxmW0 .8Qgy` at 72 px with kerning off, from `hmtx` and from `measureText`): 63 agree within 0.6 px. Six differ. Four have two files for one family in the bundle (a variable face with an optical-size axis and a static one: `Source Serif 4`, `Inter`, `Noto Sans Armenian`) so the file read may not be the file the browser chose; `Amiri` and `Noto Naskh Arabic` have one file each and the gap is the measurement, not the browser: a sum of `hmtx` advances ignores shaping, and the font's default features replace the glyph of `.` (`Noto Naskh Arabic` swaps `period` for `period.locl` through `locl`). HarfBuzz with only `kern` off gives 433.51 and 490.68 for the string, the browser 433.47 and 490.63; with `calt`, `ccmp`, `liga` and `locl` off as well, it gives back the file sums, 441.79 and 486.22. `DejaVu Sans Condensed`, `DejaVu Sans Light` and `DejaVu Serif Condensed` are the browser, and a timing effect: macOS registers them under the typographic families `DejaVu Sans` and `DejaVu Serif` (name ID 16), Firefox finds a legacy name (name ID 1) through "other family names" that it loads lazily, and the first lookup in a fresh browser answered "no such family". On the fork.4 macOS build 8 launches in 8 drew the fallback for all three (473.52 under both `monospace` and `sans-serif`), and a measurement a few seconds later gave the files' own advances (468.17, 517.95, 475.73). `font-other-names-sync.patch` reads the names on a masked page's first lookup (#247). Measured on macOS only: Windows and Linux are open. This shows the browser draws what the bundle holds. It does not show that the bundle's file versions match the ones a real LibreOffice or Google Fonts install puts on a machine.

What follows: no single family or unit is a signature. Each appears on real machines at a rate near the model's. The residue is pairing, not rates: `web` and `dev` are not co-drawn as often as in the model. A page can only use a rate difference statistically, across many visits.
