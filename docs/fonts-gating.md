# Font gating: status and measurements

Moved out of `CLAUDE.md` so it loads only when font work needs it. Lesson
numbers refer to `CLAUDE.md`'s "Verifying spoofing claims" section. `CLAUDE.md`
keeps a short lesson 5; the first section below is its full text, which is what
code comments citing "CLAUDE.md lesson 5" (smoke.yml, probe_windows_fonts.py)
lean on.

## The per-context gate fails open (lesson 5)

`gfxFontGroup` caches its user context id once in its constructor, through
`mFontVisibilityProvider->GetDocument()` → inner window → `BrowsingContext` —
four hops, each failing silently to 0. `CamouIsFontAllowed` treats context 0 as
"no per-context list" and **returns `true`, allowing every family**. It never
consults the launch-level `fonts` key: that question is answered separately by
`MaskedFontListBlocks` / `MaskConfig::IsFontAllowed`, at the sites that carry a
`FontVisibilityProvider`. So a failed context id is not caught further down —
nothing re-asks the question this gate could not answer. Two separate hops of
that chain have already been found failing
(`OffscreenCanvas::GetDocument()` off-main-thread; #83 turned out to be a cache,
not a hop). Fixing individual hops does not close the class — but the class is
narrower than this paragraph first read (#105, smoke run 34698688879 on build
34578327006, arm `(ctx105)`). Five sites ask this gate with no
`MaskedFontListBlocks` beside it — `LookupInSharedFaceNameList`
(`gfxPlatformFontList.cpp:1127`), both `GetFontList` branches (`:1409`, `:1427`),
`GetFontFamilyList` (`:1450`) and `CommonFontFallback`'s non-shared branch
(`:1713`) — and under a launch mask none of them can serve a masked family to a
page: the face-name one is skipped by its caller (`gfxUserFontSet.cpp:463-469`
refuses `local()` outright when `MaskedFontListAppliesTo`), `GetFontList` is
reached only by the chrome font enumerator, and `GetFontFamilyList` and the
non-shared branch are dormant while `gfx.e10s.font-list.shared` is true (default
`true`, `StaticPrefList.yaml:7513-7516`, `mirror: once`, overridden nowhere in
`settings/`, `additions/`, `pythonlib/` or `assets/`). Every *other* live lookup
site pairs the gate with `MaskedFontListBlocks`, which answers from the document's
`FontVisibilityProvider` and never from the context id, and asks *first* —
`CamouIsFamilyAllowed` is `!MaskedFontListBlocks(...) && CamouIsFontAllowed(...)` —
so the fail-open gate is never reached for a masked family. Measured on the
codepoint-fallback path, U+1F600 → Twemoji Mozilla under a mac launch list, on the
Linux bundle conf: a bare `new_context()` and a persistent context (userContextId 0
per `TargetRegistry.js:1152`; its own `CAMOU-FL pref-fallback ctx=0` line is
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
codepoint's digits (`gfxFontMissingGlyphs.cpp:492-510`) — so refusal is read from
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
  `pref-fallback ctx=6 key=tinos allowed=0`). `AddGenericFonts`' half is
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
  class. It now takes a `step=system-ui` first (Helvetica for `MacIntel`,
  Segoe UI for `Win32`, only if the list allows it). The step asks the
  context's own `navigator.platform` (`NavigatorManager::GetPlatform`) first
  and the launch's (`MaskConfig`) second (#138), which only matters when the
  launch's `fonts` admit more than one OS; under a one-OS launch mask a
  context whose OS differs from the launch's is refused either way.
  **Measured** on Linux by probe run 35591973853 on build 35586323562, and
  the context-first read by probe run 35698448037: a macOS context in a
  Windows launch logs `step=system-ui key=helvetica` on build 35696007399
  against `step=row key=helvetica neue` on build 35586323562
  (`fix/131-system-ui-step` @ `5b0e698`, browser inputs equal to main's).
  The guard's Windows arm cannot discriminate, since Segoe UI is also the
  sans row's first choice there. The proof is the `CAMOU-FL generic-map ...
  step=system-ui` log line, not the guard's widths — on the Linux bundle
  `Sans` also measures 648, so the guard's macOS arm cannot see a leak to
  `Sans` either. A generic under a list still yields one family where
  upstream gave up to three.
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

Still ungated after round 3: `CoreTextFontList::FindSystemFontFamily`'s return
on the macOS system-font path; the DWrite non-shared substitution branch and the
non-shared `LookupInFaceNameLists` / `CommonFontFallback` `else` branches, all
dormant while `gfx.e10s.font-list.shared` is true; `LookupLocalFont` on the
macOS and Windows platform font lists, which a Linux guard cannot see; and the
**context-0 fail-open** for the per-context half only — the launch mask reaches
context 0 on the codepoint-fallback path, measured by `(ctx105)` on U+1F600 under
the Linux bundle conf, and at the remaining live sites by reading the callers
(lesson 5, above). The macOS host
was unmeasured until #148; see "macOS host (#148)" below. #82 is closed by measurement on Linux — arm (n4) GREEN
on run 34544934746 against a RED on run 34544937587, a build differing by one
statement — but arm (j2), its bare-donor variant, is still unmeasurable on this
bundle, so it rests on one arm.

## macOS host (#148)

Measured on a native macOS arm64 host against build run 35799717143 (`main` at
`b8763a2`, whose compiled inputs equal `6e1a9f8`). The build is the packaged
app, so the font universe is the one that ships: the host's fonts plus the
bundled windows and linux sets. Headless. Probe:
`build-tester/scripts/probe_macos_font_paths.py`.

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
| b | `local()` by full and PostScript name, and bundled Arial | all error | all error | all error |
| c | `system-ui`, http page | Segoe UI, but equal to `sans-serif`, so it cannot tell the hook from the row | the `sans-serif` face | Helvetica (952.92), distinct from `sans-serif` (947.83) |
| d | codepoint fallback, from `sys-fallback` / `global-fallback` lines | none resolved off the list | none resolved off the list | none resolved off the list |
| e | `allowed=1` for a family off the context's list | 0 | 0 | 0 |

`CAMOU-FL default-unfiltered` read 0 in every run. Arms (a), (a'), (b), (d) and
(e) read the same on the file page, under the launch mask.

Arm (c) is the first macOS-host reading of the #131/#138 `system-ui` step. The
mac row is the discriminating one: `system-ui` lands on Helvetica, and
`sans-serif` lands elsewhere. The windows row is equal to `sans-serif` on this
host too, which is the ambiguity `tests/patches/system-ui-font-spoofing.py`
already notes.

**`LookupLocalFont` on macOS is unreachable from content under a mask, not
gated.** `font-hijacker.patch` keeps upstream's refusal of every `local()`
source while a mask applies, so the lookup never runs. The cost is a tell:
`local()` fails even for a face the page renders by family name, while stock
Firefox Developer Edition 157 on the same host loads `local("Arial")`,
`local("Optima Regular")` and `local("JetBrainsMono-Regular")`. That is #150,
and it is inherited from upstream.

**The context-0 Helvetica line at process start is not a leak.**
`InitFontList` calls `GetDefaultFontLocked(nullptr, ...)`. On macOS that asks
CoreText for the user UI font, Helvetica, with no provider, so the per-context
gate answers at context 0. The entry this produces, `mDefaultFontEntry`, is
read only at `gfxTextRun.cpp:2213`, after the gated pass and the logged
`default-unfiltered` tail have both failed. The probe counts these lines apart,
as "startup".

**A context's list reaches only its first content process (#149).** This was
found here but is not macOS-specific. `setFontList` stores the list in a
per-process static, and its "disabled" flag goes through
`RoverfoxStorageManager` to every process. So a later page of the same context,
which Fission puts in a new process, never gets the list and is answered by
the launch mask. Measured with six pages of one context: the first refuses a
family that only the launch list holds, and the other five render it. Voices
have the same shape. Every guard above reads one page per context, so none of
them can see this.

What this cannot see: native Windows (`gfxDWriteFontList`), a headful session,
and CoreText's `FindSystemFontFamily` separately from arm (c), which reads its
result only through `system-ui`.

