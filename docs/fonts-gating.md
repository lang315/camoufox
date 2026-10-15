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
  the stock path, with stock's own system-ui family gated by the read filter.
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
