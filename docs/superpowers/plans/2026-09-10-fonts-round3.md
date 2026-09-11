# Fonts round 3 (#82, #87, #88, #90, #91, #92, #94) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close #94 (the process-global pref-font memo answers every context from the first miss at context 0), #92 (a generic under a per-context list resolves by fontconfig distance, not by the generic), #88 (`gfxFontGroup::GetDefaultFont`'s last-resort walk and `GetDefaultFontLocked`'s two last resorts are ungated and unscoped) and #91 (`FontFaceLoadStatus` is invented rather than read for non-local faces); measure #90 (per-context speech voices) and fix it only if the arm goes RED; supply #82's missing measurement plus, if needed, its RED control; and close #87 with both halves of its ask on a native Windows host — on one branch, `fix/fonts-round3`, in one PR, one commit per issue.

**Architecture:** Two phases with the build as the boundary. **Phase 0** touches `.github/workflows/smoke.yml` only and runs twice against binaries that already exist: run 1 re-baselines every existing numeric expectation under a new `FONTCONFIG_FILE` launch and settles the recon's three open questions; run 2 scores six new arms RED-first. **Phase 1** makes the C++ changes as patch edits through the round-2 workspace flow — `patches/font-list-spoofing.patch` for #94 and #88/#92, `patches/font-hijacker.patch` for #91, conditionally `patches/speech-voices-spoofing.patch` for #90 — then builds Linux and Windows at one sha, re-runs the smoke, runs the native Windows probe, and opens the PR.

**Tech Stack:** GNU patch (`/opt/homebrew/bin/gpatch`), `make revert` / `make dir` over the Firefox 152.0.4 tree in `camoufox-152.0.4-beta.31/`, `.superpowers/sdd-44/apply_upto.py` for the workspace flow, a fonts3 splice script for the two header-carrying patches, GitHub Actions (`build.yml`, `smoke.yml`, both `workflow_dispatch`), Playwright 1.55.0, fontTools, `gh`, and an SSH session to the Windows build PC.

**Design spec:** `docs/superpowers/specs/2026-09-10-fonts-round3-design.md` at commit `3798c59`.
**Recon and spec review (untracked):** `.superpowers/sdd-fonts3/recon.md`, `.superpowers/sdd-fonts3/spec-review.md`.

---

## Global Constraints

Every task inherits this section. Values are copied verbatim from the spec, from
`CLAUDE.md`, or from a command whose output is quoted beside them.

**Patch flow.** Patches are edited through the workspace flow, never by hand:
`make revert` → `python3 .superpowers/sdd-44/apply_upto.py` (applies every patch that
sorts before the target by basename, tags `first-checkpoint`, then applies the target)
→ edit the tree → regenerate with `git -C camoufox-152.0.4-beta.31 add -A && git -C
camoufox-152.0.4-beta.31 diff --cached first-checkpoint`. Hand-written hunks must have
balanced leading/trailing context (`CLAUDE.md`, "Working with patches"). Dry-run with
the invocation the build uses — `patch -p1 --forward -l --binary --dry-run` — never
`git apply --check`, which accepts hunks GNU patch rejects. `0 FAILED` is not a
placement proof: read the applied tree afterwards.

**Which patches need a splice.** `patches/font-list-spoofing.patch` starts at
`diff --git` on line 1 and its sections are already in git-diff (path-sorted) order, so
a regenerated diff can replace it wholesale after a section-list guard. `patches/font-hijacker.patch`
carries a 38-line prose header before its first section, and
`patches/speech-voices-spoofing.patch` has sections in a non-path-sorted order
(`nsGlobalWindowInner.h` before `.cpp`, `dom/media/…` after `dom/webidl/…`). Both must
be spliced section-by-section, never `cp`-ed, or the header or the order is lost.
`.superpowers/sdd-fonts2/splice_fh.py` has **no CLI** — `OLD`, `NEW`, `OUT` and
`TARGETS` are module-level constants. Task 5 Step 1 creates an argv-driven variant.

**Git hygiene.** Never `git add -A` at the repo root. Never commit `_READY`,
`camoufox-*/`, `.venv`, `.superpowers/`, `firefox-*.tar.xz`,
`service-tester/proxies.txt`. Never print `service-tester/proxies.txt` or any log line
containing a proxy host. No force-push. Every commit message ends with
`Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. One commit per issue on
`fix/fonts-round3`, plus the conditional B6 diagnostic commit that is reverted before
merge and never reaches `main`.

**Read the state back before naming it (CLAUDE.md lesson 6).** Every sha, run id, count
and output tail that goes into a commit message, an issue comment or the PR body is
read back from the actual state first, not recalled.

**Controls (CLAUDE.md lesson 4).** A reference is a control only if something
guarantees it differs from the value under test. Every new or changed arm carries a
comment naming what would produce its GREEN *wrongly* and how the arm rules that out.
Cross-thread, cross-process, cross-world and cross-context references are not controls
without that argument.

**Context 0 stays fail-open (CLAUDE.md lesson 5, spec §D).** `CamouIsFontAllowed`
answers `true` when the thread-local context id is 0. Nothing in this round changes
that; it is restated in the PR as NOT-fixed.

**CI.** Build: `gh workflow run build.yml -R lang315/camoufox --ref fix/fonts-round3 -f
build_target=linux-x86_64` (and `windows-x86_64`), ~95 minutes. Smoke:
`gh workflow run smoke.yml -R lang315/camoufox --ref fix/fonts-round3 -f run_id=<build
run id>`, ~15 minutes. Read a run id back with
`gh run list -w build.yml -R lang315/camoufox -L 3 --json databaseId,headSha,status`.
In the `#44` step's log, runtime lines are the ones that do **not** contain the ANSI
marker `36;1m`; the rest are the workflow echoing its own source.

**Binaries this plan runs against**, each with the property that makes it usable, to be
re-read from `gh run list` before it is quoted anywhere (spec §B0):

| id | target | head sha | property |
|---|---|---|---|
| `34432908522` | linux-x86_64 | `163ee25` | `git diff 163ee25..c8c42ef -- patches additions settings bundle` is empty, so its patches are identical to `main`. Phase 0 baseline. |
| `34236331658` | linux-x86_64 | `8990915` | PR #84 artifact, pre-#93. `git show 8990915:patches/font-list-spoofing.patch \| grep -c CAMOU-FL` = **0** — this binary emits no `CAMOU-FL` line of any kind. |
| `34450188525` | windows-x86_64 | `c8c42ef` | Windows baseline on `main`, pre-fix. Task 8's control. |

**Evidence.** `.superpowers/sdd-fonts3/` (git-ignored). Ledger
`.superpowers/sdd-fonts3/progress.md`; append one line per completed step.

**Repo facts.** Repo root `/Users/lang/GolandProjects/github.com/lang315/camoufox`;
source tree `camoufox-152.0.4-beta.31/`; branch `fix/fonts-round3` checked out at the
repo root, no worktree, one implementer at a time. `/usr/bin/patch` on macOS is Apple
patch 2.0 and must not be used — use `/opt/homebrew/bin/gpatch`, and pass it to the
build as `CAMOU_PATCH=/opt/homebrew/bin/gpatch`.

---

## Log line contract

Four new `CAMOU-FL` kinds. Tasks 3 and 4 emit exactly these format strings; Task 2's
arms parse exactly these. Getting one character wrong here silently converts an arm's
verdict into "unmeasured", which is the failure mode `CLAUDE.md` lesson 4's last bullet
describes.

| kind | format string | emitted at | consumed by |
|---|---|---|---|
| `pref-fallback` | `CAMOU-FL pref-fallback ctx=%u key=%s allowed=%d` | Task 3: `gfxFontGroup::WhichPrefFontSupportsChar` and `gfxPlatformFontList::AddGenericFonts` | B1, B4 |
| `fontlist` | `CAMOU-FL fontlist ctx=%u n=%u families=%s` | Task 3: end of `gfxFontGroup::EnsureFontList` | B1, B2, B4 |
| `generic-map` | `CAMOU-FL generic-map ctx=%u generic=%d step=%s key=%s` | Task 4: `gfxFcPlatformFontList::FindGenericFamilies`, `gfxPlatformFontList::AddGenericFonts`, `gfxPlatformFontList::GetDefaultFontLocked` | B2 |
| `default-unfiltered` | `CAMOU-FL default-unfiltered ctx=%u` | Task 4: both last-resort tails | B2, B3 |

`step` is one of `row`, `rows`, `list`, `none`. `key` is `none` when the helper
declined. `families` is a comma-separated list of lowercased family keys; an **empty**
`families=` field is a child-process read failure of `fontlist::String::AsString`
(`SharedFontList.h:142-148`), not an empty list, and every arm treats it as unmeasured
rather than as a verdict.

**Each new kind must be registered in TWO places.** The guard step's own counters
(Task 1 Step 4) and the dump step's `KINDS` list (`.github/workflows/smoke.yml:4412`).
The dump step is a separate `python3` process with its own hardcoded list; adding a
kind to one and not the other produces a run whose counter table silently omits it.

The ten kinds that already exist, from `git show 163ee25:patches/font-list-spoofing.patch
| grep -o 'CAMOU-FL [a-z-]*' | sort -u`: `default`, `facename`, `fc-subst`,
`fffd-cache`, `gate`, `global-fallback`, `group`, `scope-switch`, `set`, `sys-fallback`.
`CAMOU-FL fffd-cache ctx=%u key=%s allowed=%d` has **no `hit=` field** and prints only
on a cache hit (`gfxPlatformFontList.cpp:1417-1419`).

---

## Fixture constants (measured, not invented)

**B1's codepoint is U+1C80** (CYRILLIC SMALL LETTER ROUNDED VE). Scanned over every
`.ttf/.otf/.ttc/.otc` in `bundle/fonts/{macos,windows,linux}`, every TTC member, every
cmap subtable, family names from name IDs 1 and 16, with `build-tester/.venv/bin/python`
plus fontTools. Result: among all bundled families whose name does not begin with `.`,
**only `Tinos` and `Arimo` cover U+1C80**. Both are `lin`-only in
`pythonlib/camoufox/fonts.json`, so both gates refuse them under any mac per-context
list. `Cousine` does **not** cover it. No macOS-bundle family covers it except
`.LastResort`, which covers all of Unicode by construction and is excluded from B1's
fixture list.

U+1C80 is in `UBLOCK_CYRILLIC_EXTENDED_C`, which has a `case` in
`gfxPlatformFontList::GetFontPrefLangFor(uint32_t)`, so it maps to `x-cyrillic`, and the
Unix block of `modules/libpref/init/all.js:2746-2748` sets
`font.name-list.serif.x-cyrillic` to the literal `"serif"` — which fontconfig, under the
bundle's own `fonts.conf`, answers with `Tinos`. That is the ungated pref-path family
B1 is trying to catch.

The scan command, to be pasted into the arm as a comment:

```bash
# build-tester/.venv/bin/python - <<'PY'   # run from the repo root
# import os
# from fontTools.ttLib import TTFont, TTCollection
# per={}
# for osn in ("macos","windows","linux"):
#     for dp,_dn,fns in os.walk(os.path.join("bundle/fonts",osn)):
#         for fn in fns:
#             if not fn.lower().endswith((".ttf",".otf",".ttc",".otc")): continue
#             p=os.path.join(dp,fn)
#             try:
#                 fs=list(TTCollection(p).fonts) if fn.lower().endswith((".ttc",".otc")) \
#                    else [TTFont(p,fontNumber=0,lazy=True)]
#             except Exception: continue
#             for f in fs:
#                 cps=set()
#                 for t in f["cmap"].tables:
#                     try: cps|=set(t.cmap.keys())
#                     except Exception: pass
#                 for r in f["name"].names:
#                     if r.nameID in (1,16):
#                         per.setdefault(r.toUnicode().casefold(),set()).update(cps)
# print(sorted(k for k,v in per.items() if 0x1C80 in v and not k.startswith(".")))
# PY
# -> ['arimo', 'tinos']
```

**Bundle U+FFFD coverage** (recon §5, independently reproduced in the spec review,
table rows 12–14). macOS bundle, U+FFFD **absent** from every face of: `Helvetica Neue`,
`Helvetica`, `Geneva`, `Courier`, `Avenir Next`, `Times`; **present** in `Menlo`,
`Lucida Grande`. Windows bundle, absent from `Arial`, `Calibri`, `Consolas`,
`Courier New`, `Times New Roman`; present in `Segoe UI`, `Tahoma`, `Verdana`. `DejaVu`
is in no bundle.

**Fixture family lists**, all checked against `pythonlib/camoufox/fonts.json`
(`mac` 574 entries, `win` 107, `lin` 134):

| arm | list | every entry mac-only? |
|---|---|---|
| B1 | `["Geneva"]` | yes |
| B2 | `["Menlo", "Helvetica Neue", "Times"]` | yes |
| B4 donor | `["Times", "Menlo"]`; recovery `["Times", "Lucida Grande"]` | yes |
| B4 victim | `["Times", "Geneva"]` | yes |

`Tinos`, `Arimo` and `Cousine` are `lin`-only, so no fixture list contains a family
the fontconfig generics can reach.

---

## File Structure

| File | Task | Responsibility |
|---|---|---|
| `.github/workflows/smoke.yml` | 1, 2, 7 | Every Linux measurement. `FONTCONFIG_FILE` launch env, triage routing, kind counters, arms (n1)…(n7), `EXPECTED_RED`/`EXPECTED_GREEN`. |
| `patches/font-list-spoofing.patch` | 3, 4 | #94 (A1) and #88/#92 (A2). Sections for `gfxPlatformFontList.{cpp,h}`, `gfxTextRun.cpp` and `gfxFcPlatformFontList.cpp` already exist. |
| `patches/font-hijacker.patch` | 5 | #91 (A3), `layout/style/` only. Header-carrying — splice. |
| `patches/speech-voices-spoofing.patch` | 6 (conditional) | #90 (A4). Section order not git-canonical — splice. |
| `build-tester/scripts/probe_windows_fonts.py` | 8 | #87's codepoint arm, added beside the existing family-name arms. |
| `.superpowers/sdd-fonts3/splice.py` | 5 | New, untracked. argv-driven section splicer. |
| `.superpowers/sdd-fonts3/*.md`, `*.log`, `*.json` | all | Untracked evidence: `progress.md`, `phase0-run1.md`, `gate-b5.md`, `gate-b4.md`, smoke logs, PR body, issue comments. |
| `CLAUDE.md` | 9 | "Still ungated" paragraph and the ungated-paths list. |
| `docs/superpowers/specs/2026-09-10-fonts-round3-design.md` | 9 | Outcome section. |
| `docs/superpowers/plans/2026-09-10-fonts-round3.md` | 9 | Outcome section (this file). |

Not touched by any task: `Makefile`, `upstream.sh`, `additions/`, `settings/`,
`pythonlib/`, every other file under `patches/`.

---

### Task 1: B0 — launch under `FONTCONFIG_FILE`, triage routing, kind counters, Phase 0 run 1

Workflow only. No patch, no build. This task makes every later measurement mean
something: today the smoke launches the raw binary with the runner's host fontconfig,
so host fonts are in every font list and no shipped Camoufox ever sees that font
universe (recon open question 4).

**Files:**
- Modify: `.github/workflows/smoke.yml`
- Create: `.superpowers/sdd-fonts3/progress.md`, `.superpowers/sdd-fonts3/phase0-run1.md`,
  `.superpowers/sdd-fonts3/smoke-p0r1-<id>.log`, `.superpowers/sdd-fonts3/smoke-p0r1-arms.txt` (all untracked)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces, all used by Task 2:
  - `kind_total(kind) -> int`, module-level in the guard step: how many `CAMOU-FL
    <kind>` lines the **whole run** has emitted since the step's own start mark.
    An arm calls it to tell "this binary predates the kind" from "the kind exists but
    not for my context".
  - `LOG_START`, the `log_mark()` taken immediately after `MOZ_LOG_FILE` is set.
  - `KNOWN_UNMEASURABLE` re-shaped to `{tag: (run_id, signature, why)}` with `signature`
    left `None`, so absorption behaves exactly as it does today. Task 2 Step 1 fills the
    signatures in from run 1's own text and turns the match on; nothing before that point
    may depend on a signature matching.
  - `.superpowers/sdd-fonts3/phase0-run1.md`, whose named outputs Task 2's fixtures
    depend on — in particular Q4's `J_SIG` and `J2_SIG`.

- [ ] **Step 1: Start the ledger**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
git rev-parse --abbrev-ref HEAD
git rev-parse HEAD
mkdir -p .superpowers/sdd-fonts3
cat >> .superpowers/sdd-fonts3/progress.md <<'EOF'
# fonts round 3 ledger
EOF
```
Expected: `fix/fonts-round3` and `3798c59…`. If the branch differs, stop. A later head is
fine as long as `git log --oneline 3798c59..HEAD` shows only docs commits; anything
touching `patches/` or `.github/` means someone else has started, and this plan assumes
one implementer at a time.

- [ ] **Step 2: Find where the extracted artifact puts its fonts and its `fonts.conf`**

The launch helper needs absolute paths inside the runner's extracted package, and this
plan must not guess them. Add a read-back to the "Unpack + locate firefox binary" step
(`.github/workflows/smoke.yml:47-59`). Immediately before the final
`echo "--- binary ---"` line, insert:

```bash
          # Camoufox (#44 round 3): the fonts step now launches with
          # FONTCONFIG_FILE pointing at the bundle's own fonts.conf, the way
          # pythonlib/camoufox/utils.py:238 ships it, so the measurement is of
          # the font universe a shipped Camoufox has rather than of the
          # runner's host fontconfig. Export both paths from here rather than
          # deriving them in Python: the package layout is a property of
          # scripts/package.py, not of the guard.
          # The path is PINNED to the linux directory, never `-name fonts.conf
          # | head -1`. scripts/package.py copytrees the whole
          # bundle/fontconfig directory, so the artifact carries THREE
          # fonts.conf files and `head -1` would pick one by directory order:
          #   linux/   sans-serif=Arimo  serif=Tinos            monospace=Cousine
          #   macos/   sans-serif=Helvetica serif=Times         monospace=Menlo
          #   windows/ sans-serif=Arial  serif=Times New Roman  monospace=Consolas
          # All three contain the `<dir prefix="cwd">fonts</dir>` needle, so the
          # substitution guard below cannot catch a wrong pick. Picking the
          # macOS file would silently make three arms mean something else: (n1)
          # would resolve serif to Times, which does not cover U+1C80, so the
          # ungated pref path produces no leak and the arm reads GREEN for the
          # wrong reason; (n2)'s monospace would resolve to Menlo, which is IN
          # its fixture list, so #92 would look fixed with no A2 at all; and
          # (n4)'s donor would get Menlo into the ctx-0 memo, which is its own
          # SETUP-INVALID branch.
          fdir=$(find cf -maxdepth 4 -type d -name fonts | head -1)
          fconf=$(find cf -maxdepth 6 -type f -path '*/fontconfig/linux/fonts.conf' | head -1)
          if [ -z "$fconf" ]; then
            echo "::error::no fontconfig/linux/fonts.conf in the package"
            find cf -maxdepth 6 -type f -name fonts.conf; exit 1
          fi
          echo "fonts_dir=$GITHUB_WORKSPACE/dist/$fdir" >> "$GITHUB_OUTPUT"
          echo "fonts_conf=$GITHUB_WORKSPACE/dist/$fconf" >> "$GITHUB_OUTPUT"
          echo "--- fonts ---"; echo "dir=$fdir conf=$fconf"
          ls "$fdir" | head -5
```

Then add the two outputs to the guard step's `env:` block, which today ends at
`.github/workflows/smoke.yml:4392-4394` with `CAMOUFOX_BIN` and
`LIBGL_ALWAYS_SOFTWARE`:

```yaml
        env:
          CAMOUFOX_BIN: ${{ steps.bin.outputs.bin }}
          LIBGL_ALWAYS_SOFTWARE: "1"
          CAMOU_FONTS_DIR: ${{ steps.bin.outputs.fonts_dir }}
          CAMOU_FONTS_CONF: ${{ steps.bin.outputs.fonts_conf }}
```

If `find` prints nothing for either path, run 1 will say so in Step 3's guard and the
step fails loudly rather than launching without the substitution.

- [ ] **Step 3: Generate the runtime fontconfig and put it in `os.environ`**

Spec §B0, verbatim, because this step implements it clause for clause:

> The smoke pins the **Linux** conf (`bundle/fontconfig/linux/fonts.conf`; the artifact
> carries all three OS confs and `find | head -1` is not a choice) and asserts its text
> names `Tinos`, `Arimo` and `Cousine`. Consequence stated up front: that file aliases
> `serif`/`sans-serif`/`monospace` to `Tinos`/`Arimo`/`Cousine`, all refused under a mac
> or win per-context list, so every generic under such a list is decided by A2, not by
> fontconfig. What the guard cannot see (lesson 3): `pythonlib/camoufox/utils.py:215-238`
> selects the conf by the **spoofed** OS, so a shipped mac-fingerprinted session runs with
> the macOS conf (`Helvetica`/`Times`/`Menlo` — all allowed under a mac list) and
> fontconfig answers its generics itself; B2's RED is partly an artifact of the Linux
> conf, and A2 is what answers when the conf's aliases are refused. Written into the PR's
> NOT-verified list.

The pin is in Step 2's `find`; the assertion and the blind-spot comment are below; the
NOT-verified entry is Task 9 Step 4.

`pythonlib/camoufox/utils.py:58-92` (`_generate_fontconfig`) replaces
`<dir prefix="cwd">fonts</dir>` with an **absolute** `<dir>…</dir>` and writes the
result to a cache dir; after that substitution the process's cwd is irrelevant. The
file's `<cachedir prefix="xdg">fontconfig</cachedir>` resolves against
`XDG_CACHE_HOME`. Mirror both.

Every launch in the guard step already passes `env={**os.environ, "CAMOU_CONFIG": …}`,
so **one** `os.environ` assignment instruments all ~25 of them and adds no launch of
its own — the same mechanism the `MOZ_LOG` block at `.github/workflows/smoke.yml:648-649`
already uses. Insert immediately after the
`os.environ["MOZ_LOG_FILE"] = os.path.join(LOG_DIR, "cfx%PID")` line:

```python
          # ---- #44 round 3 (B0): confine fontconfig to the bundle ----------
          # Until now every launch here ran the raw binary with the runner's
          # host fontconfig, so ubuntu-24.04's fonts -- DejaVu among them --
          # were in every font list and every arm measured a font universe no
          # shipped Camoufox has (recon open question 4). pythonlib/camoufox/
          # utils.py:238 sets FONTCONFIG_FILE for exactly this reason; this is
          # the same substitution _generate_fontconfig (utils.py:58-92) makes.
          #
          # CONSEQUENCE, stated up front because it decides three arms:
          # bundle/fontconfig/linux/fonts.conf aliases serif/sans-serif/
          # monospace to Tinos/Arimo/Cousine -- all `lin`-only in fonts.json,
          # so all refused under any mac or win per-context list. Every generic
          # under such a list is therefore decided by A2's table, not by
          # fontconfig. The file also carries ZERO <include> elements, so the
          # host's /etc/fonts/conf.d/30-metric-aliases.conf is absent and
          # `Times` is not silently aliased to `Tinos`.
          #
          # WHAT THIS GUARD CANNOT SEE (CLAUDE.md lesson 3). It measures the
          # LINUX conf. A shipped Camoufox picks the conf by the SPOOFED os:
          # pythonlib/camoufox/utils.py:213-231 maps user_agent_os through
          # {'lin':'linux','mac':'macos','win':'windows'} and reads
          # fontconfig/<os_dir>/fonts.conf. So a real mac-fingerprinted session
          # runs with sans-serif/serif/monospace aliased to
          # Helvetica/Times/Menlo -- all mac families, all ALLOWED under a mac
          # list -- and fontconfig answers its generics correctly there without
          # A2 ever being consulted. #92 is still real (the refusal case is
          # reachable whenever the per-context list and the spoofed OS disagree,
          # which is the whole point of a per-context list), but arm (n2)'s RED
          # is partly an artifact of the conf this guard chose. Stated here and
          # in the PR's NOT-verified section rather than discovered later.
          FONTS_DIR = os.environ.get("CAMOU_FONTS_DIR", "")
          FONTS_CONF_SRC = os.environ.get("CAMOU_FONTS_CONF", "")
          assert FONTS_DIR and os.path.isdir(FONTS_DIR), (
              f"CAMOU_FONTS_DIR is {FONTS_DIR!r}: the unpack step did not find the "
              f"artifact's fonts directory, so this run would measure the runner's "
              f"host fontconfig and every arm below would be about the wrong font "
              f"universe.")
          assert FONTS_CONF_SRC and os.path.isfile(FONTS_CONF_SRC), (
              f"CAMOU_FONTS_CONF is {FONTS_CONF_SRC!r}: no fonts.conf in the "
              f"artifact. Same consequence as above.")
          FC_DIR = os.path.join(os.environ.get("RUNNER_TEMP", "/tmp"), "camou-fc")
          os.makedirs(os.path.join(FC_DIR, "cache"), exist_ok=True)
          _conf = open(FONTS_CONF_SRC, encoding="utf-8").read()
          _needle = '<dir prefix="cwd">fonts</dir>'
          assert _needle in _conf, (
              f"{FONTS_CONF_SRC} does not contain {_needle!r}; the bundle's fonts.conf "
              f"has changed shape and this substitution would silently do nothing.")
          # Identity check, not a path check: all three bundled fonts.conf files
          # carry the needle above, so only their alias targets tell them apart.
          # Arimo/Tinos/Cousine appear ONLY in the linux file (verified: grep -c
          # over the macos and windows files returns 0 for all three).
          _missing = [f for f in ("Arimo", "Tinos", "Cousine") if f not in _conf]
          assert not _missing, (
              f"{FONTS_CONF_SRC} does not alias to {_missing}: this is not the LINUX "
              f"fonts.conf, and arms (n1), (n2) and (n4) all rest on the Linux aliases. "
              f"See the unpack step's -path '*/fontconfig/linux/fonts.conf' pin.")
          _conf = _conf.replace(_needle, "<dir>%s</dir>" % FONTS_DIR)
          FONTCONFIG_FILE = os.path.join(FC_DIR, "fonts.conf")
          with open(FONTCONFIG_FILE, "w", encoding="utf-8") as _fh:
              _fh.write(_conf)
          os.environ["FONTCONFIG_FILE"] = FONTCONFIG_FILE
          os.environ["XDG_CACHE_HOME"] = os.path.join(FC_DIR, "cache")
          print(f"  [setup] FONTCONFIG_FILE={FONTCONFIG_FILE} "
                f"src={FONTS_CONF_SRC} fonts_dir={FONTS_DIR} "
                f"xdg_cache={os.environ['XDG_CACHE_HOME']}")
          # -------------------------------------------------------------------
```

- [ ] **Step 4: Add the whole-run kind counter**

Insert immediately after the `ctx_histogram` definition
(`.github/workflows/smoke.yml:689-696`):

```python
          # The mark for the WHOLE step, taken before any launch. kind_total()
          # below counts against it rather than against an arm's own mark,
          # because the question it answers is about the BINARY, not the arm:
          # "does this build emit `fontlist` lines at all?" An arm that cannot
          # tell "the binary predates this kind" from "the kind exists but not
          # for my context" reports SETUP-INVALID on a binary that was never
          # going to produce the line -- which under the routing fixed in Step 5
          # fails the step for a reason no re-run can change.
          LOG_START = log_mark()

          def kind_total(kind):
              """How many `CAMOU-FL <kind>` lines this RUN has emitted so far."""
              return len(camou_fl(LOG_START, f"CAMOU-FL {kind} ", limit=None))
```

`LOG_START` must sit after the `MOZ_LOG_FILE` assignment (so the dir exists) and before
the first `sync_playwright()` block in the step, which is the config launch at
`.github/workflows/smoke.yml:803-806` — **not** arm (b)'s bare launch at `:907`, which is
the second. The `ctx_histogram` definition ends at `:696`, well before either, so placing
`LOG_START` directly after it satisfies both constraints.

Then register the four new kinds in the dump step's list. Replace
`.github/workflows/smoke.yml:4412-4417`:

```python
          KINDS = ["gate", "set", "group", "scope-switch", "fffd-cache",
                   "global-fallback", "sys-fallback", "default", "facename",
                   # #83's mechanism site, added with the mFcSubstituteCache
                   # fix: a hit here answers a direct-named family before the
                   # gate is ever asked.
                   "fc-subst"]
```
with:
```python
          KINDS = ["gate", "set", "group", "scope-switch", "fffd-cache",
                   "global-fallback", "sys-fallback", "default", "facename",
                   # #83's mechanism site, added with the mFcSubstituteCache
                   # fix: a hit here answers a direct-named family before the
                   # gate is ever asked.
                   "fc-subst",
                   # Round 3. This list is DUPLICATED state: the guard step is a
                   # different python3 process and cannot import from here, so a
                   # kind added to one and not the other silently drops out of
                   # the counter table. See the plan's "Log line contract".
                   "pref-fallback",     # #94, the pref-memo read filter
                   "fontlist",          # #94, what EnsureFontList resolved
                   "generic-map",       # #92, which step answered a generic
                   "default-unfiltered"]  # #88, the last-resort tail fired
```

The `for k in sorted(set(counts) - set(KINDS) - {OTHER})` loop just below already
prints any kind that is *not* in the list under `<-- kind not in Task 5's nine`, so a
future kind is visible even when this edit is forgotten. That is a backstop, not the
mechanism.

- [ ] **Step 5: Fix the triage routing so a broken fixture cannot hide in `KNOWN_UNMEASURABLE`**

Today (`.github/workflows/smoke.yml:4320-4325`) an arm listed in `KNOWN_UNMEASURABLE`
that is *also* in `unmeasured_arms` is absorbed into `unmeasurable` and never reaches
the `assert not (unexpected or unmeasured)`. Arms (j) and (j2) each have five and four
absorbed branches — a process split, an unreadable process table, a control-invalid
signature — and none of those is the standing bundle limitation the entry describes.
A broken fixture is therefore indistinguishable from the structural reason.

**This step lands the SHAPE, not the signature match.** The signature has to be the
first ~40 characters of each arm's own `unmeasured_arms` text, which is
`failures[0][:220]` (`smoke.yml:864-869`) — and no such string can be written before it
has been read. Worse, run `34428270062`, which established the standing reason, predates
`FONTCONFIG_FILE`: under the new launch the host's DejaVu is gone and `monospace` aliases
to `Cousine`, which carries no U+FFFD, so these arms may take a **different** branch and a
signature copied from the old run would be right for that run and wrong for run 1. Step 8
reads run 1's actual text; Task 2 Step 1 turns the match on. Until then the absorb
condition stays exactly as it is today, so this step cannot fail a run.

Replace the `KNOWN_UNMEASURABLE` dict:

```python
          KNOWN_UNMEASURABLE = {
              "(j)": "#82: U+FFFD never reaches SystemFindFontForChar on this bundle -- "
                     "the default font (DejaVu Sans) covers it; fffd-cache lines = 0 in "
                     "run 34428270062",
              "(j2)": "#82: U+FFFD never reaches SystemFindFontForChar on this bundle -- "
                      "the default font (DejaVu Sans) covers it; fffd-cache lines = 0 in "
                      "run 34428270062",
          }
```
with:
```python
          # (run_id, signature, why). `run_id` is the run that ESTABLISHED the
          # structural reason -- an entry without one is a guess, and the assert
          # below refuses it. `signature` is a substring that must appear in the
          # arm's OWN recorded unmeasured text when it failed for THAT reason,
          # so that an arm going unmeasured for any other reason (a process
          # split, an unreadable pid table, an invalid control) falls through to
          # SETUP-INVALID and fails the step instead of absorbing silently.
          #
          # signature is None until Phase 0 run 1 has been READ. It cannot be
          # written before then: note_unmeasured stores failures[0][:220], and
          # which of arm (j)'s five branches fires under FONTCONFIG_FILE is not
          # knowable from run 34428270062, which predates that launch. While it
          # is None the absorb below behaves exactly as it does today, so this
          # reshape alone cannot fail a run. Task 2 Step 1 fills both in from
          # run 1's own text and turns the match on.
          KNOWN_UNMEASURABLE = {
              "(j)": ("34428270062", None,
                      "#82: U+FFFD never reaches SystemFindFontForChar on this bundle -- "
                      "the default font covers it; fffd-cache lines = 0 in run "
                      "34428270062. Re-check under FONTCONFIG_FILE: with the host's "
                      "DejaVu gone and monospace aliased to Cousine (no U+FFFD), this "
                      "may have become measurable."),
              "(j2)": ("34428270062", None,
                       "#82: same, bare-donor variant."),
          }
          for _k, _v in KNOWN_UNMEASURABLE.items():
              assert isinstance(_v, tuple) and len(_v) == 3 and _v[0].isdigit(), (
                  f"KNOWN_UNMEASURABLE[{_k}] must be (run_id, signature, why) with a "
                  f"real run id: an arm may only be excused by a run someone can read.")
```

Then replace the absorb condition (`.github/workflows/smoke.yml:4321-4325`):

```python
              tag = next((k for k in KNOWN_UNMEASURABLE if t.startswith(k)), None)
              if tag and tag in unmeasured_arms:
                  unmeasurable.append(t)
                  continue
```
with:
```python
              tag = next((k for k in KNOWN_UNMEASURABLE if t.startswith(k)), None)
              _sig = KNOWN_UNMEASURABLE[tag][1] if tag else None
              if (tag and tag in unmeasured_arms
                      and (_sig is None or _sig in unmeasured_arms[tag])):
                  unmeasurable.append(t)
                  continue
```

And **one** print loop — the only one that indexes `KNOWN_UNMEASURABLE`, at
`.github/workflows/smoke.yml:4350`. The loops at `:4328` and `:4341` index `EXPECTED_RED`
and `EXPECTED_GREEN` and must not change. Replace
`for k, why in KNOWN_UNMEASURABLE.items():` with
`for k, (_run, _sig, why) in KNOWN_UNMEASURABLE.items():`, then change the condition on
**line `:4352` only** — the one that picks the `state` string — from
`if hit and k in unmeasured_arms:` to
`if hit and k in unmeasured_arms and (_sig is None or _sig in unmeasured_arms[k]):`,
so a signature mismatch prints the "RED WITH A VERDICT" branch instead of the excuse.

**Leave `:4362` alone.** That is the second `if hit and k in unmeasured_arms:`, the one
guarding `print(f"        observed this run: …")`. Narrowing it would suppress the arm's
own recorded text in exactly the mismatch case where a reader most needs it.

Finally, rename the unmeasured bucket's label so the spec's `SETUP-INVALID` string
appears in the log. Replace:
```python
          for t in unmeasured:
              print(f"  RED but UNMEASURED: {t}")
```
with:
```python
          for t in unmeasured:
              print(f"  SETUP-INVALID: {t}")
```

- [ ] **Step 6: Syntax-check and commit**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
python3 .superpowers/sdd-fonts2/check_smoke_python.py .github/workflows/smoke.yml \
  "$TMPDIR/smoke-py-t1"
uv run --with pyyaml python -c "import yaml; yaml.safe_load(open('.github/workflows/smoke.yml')); print('YAML OK')"
git diff --stat .github/workflows/smoke.yml
```
Expected: every block `OK` and `N block(s), 0 failed`; `YAML OK`; one changed file.
`check_smoke_python.py` extracts each `python - <<'MARKER'` heredoc and byte-compiles
it, so a syntax error costs a second instead of a 15-minute CI run.

```bash
git add .github/workflows/smoke.yml
git commit -m "measure(#44): launch under FONTCONFIG_FILE, fix triage routing, count four new CAMOU-FL kinds

Phase 0 groundwork for fonts round 3. Workflow only -- no patch, no rebuild.

Every launch in the #44 guard ran the raw binary with the runner's host
fontconfig, so ubuntu-24.04's fonts were in every font list and every arm
measured a font universe no shipped Camoufox has. pythonlib/camoufox/utils.py
sets FONTCONFIG_FILE for exactly this reason; the same substitution now runs
once beside the MOZ_LOG block, and every launch picks it up because they all
spread os.environ. The consequence is stated in the code: the bundle's
fonts.conf aliases serif/sans-serif/monospace to Tinos/Arimo/Cousine, all
lin-only in fonts.json, so every generic under a mac or win per-context list is
decided by the fork, not by fontconfig.

An arm listed in KNOWN_UNMEASURABLE whose SETUP broke was absorbed into the
'known unmeasurable' bucket and never reached the step's assert. Arms (j) and
(j2) have five and four absorbed branches between them and the standing entry
describes none of them, so a broken fixture read exactly like the bundle
limitation. Each entry is now (run_id, signature, why): the run id is asserted
to exist, and the arm's own recorded text must carry the signature or it falls
through to SETUP-INVALID and fails the step.

kind_total() counts CAMOU-FL lines of a kind across the whole run rather than
one arm's window, so an arm can tell 'this binary predates the kind' from 'the
kind exists but not for my context'. The four kinds round 3 adds are registered
in both places that need them -- the guard's counters and the dump step's KINDS
list, which is a separate process with its own hardcoded copy.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push origin fix/fonts-round3
```

- [ ] **Step 7: Dispatch Phase 0 run 1 against `34432908522` and wait**

```bash
gh run list -w build.yml -R lang315/camoufox -L 10 \
  --json databaseId,headSha,status,conclusion \
  --jq '.[] | select(.databaseId==34432908522) | "\(.databaseId) \(.headSha[0:7]) \(.status) \(.conclusion)"'
git diff --stat 163ee25..c8c42ef -- patches additions settings bundle
gh workflow run smoke.yml -R lang315/camoufox --ref fix/fonts-round3 -f run_id=34432908522
sleep 20
gh run list -R lang315/camoufox --workflow=smoke.yml --limit 3 \
  --json databaseId,headSha,status,createdAt \
  --jq '.[] | "\(.databaseId) \(.status) \(.headSha[0:7]) \(.createdAt)"'
```
Expected: the first command prints `34432908522 163ee25 completed success`; the
`git diff --stat` prints **nothing**, which is what makes this artifact a stand-in for
`main`. Record the newest smoke id as `P0R1` in the ledger.

To wait, load `Monitor` (`ToolSearch` with query `select:Monitor`) and give it an
until-loop on:
```bash
gh run view <P0R1> -R lang315/camoufox --json status,conclusion \
  --jq '.status + " " + (.conclusion // "-")'
```
until the output starts with `completed`, capped at 45 minutes. If Monitor is
unavailable, poll every three minutes. `completed failure` is still readable and Step 8
still runs.

- [ ] **Step 8: Read back every re-baselined number and the three open questions**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
gh run view <P0R1> -R lang315/camoufox --log > .superpowers/sdd-fonts3/smoke-p0r1-<P0R1>.log
grep -v '36;1m' .superpowers/sdd-fonts3/smoke-p0r1-<P0R1>.log \
  | grep -E '\[setup\]|\((b|b2|b2r|e|f|g|h|i|i2|j|j2|k)\) |tripwire triage|SETUP-INVALID|UNEXPECTED RED|KNOWN UNMEASURABLE|arm h. / #88' \
  | sed -E 's/^[^Z]*Z//' | cut -c1-260 \
  | tee .superpowers/sdd-fonts3/smoke-p0r1-arms.txt
gh run download <P0R1> -R lang315/camoufox -n smoke-results -D .superpowers/sdd-fonts3/p0r1 || \
  gh api repos/lang315/camoufox/actions/artifacts --jq '.artifacts[] | select(.workflow_run.id==<P0R1>) | "\(.id) \(.name)"'
grep -E '^  (gate|set|group|scope-switch|fffd-cache|global-fallback|sys-fallback|default|facename|fc-subst|pref-fallback|fontlist|generic-map|default-unfiltered) ' \
  .superpowers/sdd-fonts3/smoke-p0r1-<P0R1>.log | sed -E 's/^[^Z]*Z//'
```

Write `.superpowers/sdd-fonts3/phase0-run1.md` with these named outputs, **each copied
from `smoke-p0r1-arms.txt` or from the per-kind counter table, never recalled**:

```markdown
# Phase 0 run 1 — re-baseline under FONTCONFIG_FILE
Run: <P0R1>, smoke.yml @ <workflow sha>, binary from build 34432908522 @ 163ee25.

## Q1. Which exit answered U+FFFD in the mac context?
<This binary emits no `fontlist` or `pref-fallback` line -- neither kind exists
in it. Answer from the width against the named candidate set (bundle U+FFFD
carriers: mac Menlo, Lucida Grande; win Segoe UI, Tahoma, Verdana; lin Arimo,
Tinos, STIX Two Math) plus the presence or absence of `sys-fallback` and
`global-fallback` lines. Paste the lines.>

## Q2. Does any `fffd-cache` line appear at all?
<Copy the `fffd-cache` row from the per-kind counter table. 0 means
SystemFindFontForChar's U+FFFD fast path never ran; a non-zero count with
`allowed=0` means CommonFontFallback answered before GlobalFontFallback could
log.>

## Q3. Does the runner's fontconfig `monospace` face carry U+FFFD?
<Under FONTCONFIG_FILE the alias is Cousine, which the bundle scan says does
NOT carry U+FFFD. Confirm from the run rather than from the scan: paste arm
(j)/(j2)'s donor lines.>

## Q4. Did (j)/(j2) become measurable, and what is each one's signature?
<If either now reaches its verdict, its KNOWN_UNMEASURABLE entry no longer
applies and Task 7 Step 1 must retire it.

If either is still absorbed, copy its `observed this run: …` line VERBATIM from
the triage block -- that line is `unmeasured_arms[tag]`, i.e. the arm's first
failure string truncated to 220 characters. Record the first 40 characters of
each, exactly as printed, as J_SIG and J2_SIG. They will differ: arm (j)'s
branches read "could not read the content-process table", "a new content process
appeared for B", "Tahoma is not among the families that demonstrably resolve
U+FFFD in this build", "the donor's AUTOMATIC U+FFFD fallback settled at", "the
leak signature ... equals the run's U+FFFD tofu floor"; arm (j2) adds
"bare-context setup ALSO invalid: none of the bisected candidates". Do NOT
paraphrase and do NOT shorten to a phrase you think is stable -- Task 2 Step 1
greps for these strings literally.

J_SIG  = <verbatim, 40 chars>
J2_SIG = <verbatim, 40 chars>>

## Re-baselined numbers
<Every width and count the existing arms print, copied verbatim. These are the
references Task 2's new arms are allowed to compare against.>

## Triage
<Paste the whole `=== tripwire triage ===` block.>
```

Append to the ledger: `P0R1=<id>`, its conclusion, and a one-line answer to each of Q1–Q4.

---

### Task 2: Six new arms, RED-first — B1 (#94), B2 (#92), B3 (#88), B4 (#82), B5 (#90), B7 (#91)

Workflow only. Each arm gets its own tripwire tag so a RED-today arm cannot turn a
currently-green arm red: `(n1)` for B1, `(n2)` for B2, `(h3)` for B3, `(n4)` for B4,
`(n5)` for B5, `(n7)` for B7.

**Every arm has three states, not two.** The `fontlist`, `pref-fallback` and
`generic-map` lines do not exist until Tasks 3 and 4 land, and on `34432908522` and
`34236331658` they never will. An arm that treats "the kind is absent from the whole
run" as a failed precondition reports SETUP-INVALID and, under Task 1's routing, fails
the step for a reason no re-run can change. So:

- `kind_total(kind) == 0` → **the binary predates the kind.** Fall back to whatever this
  arm can still establish from widths alone, and say in the printed line that the log
  half was unavailable. Append a tripwire **only** when the width evidence is a verdict
  on its own — for `(n1)` a match against the bare Tinos reference that also differs from
  the tofu floor, for `(n2)` a proportional `monospace` whose `sans-serif` control
  differs. Otherwise print and append nothing.
- `kind_total(kind) > 0` but no line for this arm's context → **SETUP-INVALID.** The
  arm records itself through `note_unmeasured` and fails the step.
- lines present for this context → score normally.

The first bullet is what gives #94 and #92 a Phase 0 RED at all: both are listed in
`EXPECTED_RED` for Phase 0 (Step 8), and a `Closes #94` in Task 9 has to cite a RED some
run actually produced. An arm whose width evidence cannot stand alone — `(n4)`, whose
whole verdict is about which cached family answered — appends nothing in this state and
its Phase 0 reading is a diagnostic line, not a tripwire.

**Log-window discipline (applies to every arm below).** `camou_fl` reads every file in
`LOG_DIR` and treats a file absent from the mark as offset `0` (`smoke.yml:658-687`), so
a browser process started *after* the mark still lands inside the window. Two consequences
each arm honours: take every `camou_fl` read **before** any reference launch, and filter
the result by the fixture context's own `ctx=`. A bare reference launch has no
per-context list, so its own generics resolve to the very families the fixtures forbid —
its `fontlist` line names `tinos` — and an unfiltered window would refuse the fixture as
invalid on the fixed build, where the arm is expected GREEN.

**Files:**
- Modify: `.github/workflows/smoke.yml`
- Create: `.superpowers/sdd-fonts3/gate-b5.md`, `.superpowers/sdd-fonts3/smoke-p0r2-<id>.log`,
  `.superpowers/sdd-fonts3/smoke-p0r2-arms.txt`, `.superpowers/sdd-fonts3/smoke-p0r2-84-<id>.log` (untracked)

**Interfaces:**
- Consumes: `kind_total`, `LOG_START`, `log_mark`, `camou_fl`, `note_unmeasured`,
  `tab_pids`, `one_page_arg`, `two_contexts_one_launch`, `build_probe_k`, `FONTS`,
  `tripwires` — all defined in `smoke.yml` before the insertion points below. Also
  `.superpowers/sdd-fonts3/phase0-run1.md` from Task 1 Step 8, whose Q4 supplies `J_SIG`
  and `J2_SIG` for Step 1 below.
- Produces: `.superpowers/sdd-fonts3/gate-b5.md`, containing exactly one of
  `GATE: B5 RED` / `GATE: B5 GREEN`, which Task 6 branches on; and the B4-on-`34236331658`
  reading that Task 7's B6 branch keys on.

- [ ] **Step 1: Turn on `KNOWN_UNMEASURABLE` signature matching, from run 1's own text**

Task 1 Step 5 landed the `(run_id, signature, why)` shape with `signature` set to `None`,
which makes the absorb behave exactly as it did before. Now that Phase 0 run 1 has been
read, fill both signatures in from `.superpowers/sdd-fonts3/phase0-run1.md`'s Q4 —
`J_SIG` and `J2_SIG`, copied verbatim from that run's `observed this run: …` lines, which
are `unmeasured_arms[tag]` (i.e. `failures[0][:220]`, `smoke.yml:864-869`).

**If Q4 says either arm became measurable**, do not give it a signature — remove its entry
from `KNOWN_UNMEASURABLE` entirely, because a measurable arm is reporting a real defect and
must reach `unexpected`.

Replace the two `None` values with the recorded strings:

```python
          KNOWN_UNMEASURABLE = {
              "(j)": ("34428270062", "<J_SIG, the first 40 chars, verbatim>",
                      "#82: U+FFFD never reaches SystemFindFontForChar on this bundle -- "
                      "the default font covers it; fffd-cache lines = 0 in run "
                      "34428270062. Re-check under FONTCONFIG_FILE: with the host's "
                      "DejaVu gone and monospace aliased to Cousine (no U+FFFD), this "
                      "may have become measurable."),
              "(j2)": ("34428270062", "<J2_SIG, the first 40 chars, verbatim>",
                       "#82: same, bare-donor variant."),
          }
```

The two strings **will differ** — arm (j) and arm (j2) take different branches — so a
single shared signature is a sign the readback was paraphrased rather than copied.

**Then assert each signature actually occurs in the file, before any dispatch.** This is
the check whose absence made the first draft of this plan fail every run: the signature it
guessed, `no fffd-cache line`, appears nowhere in `smoke.yml`, so both arms would have
fallen through to `unmeasured` and tripped `assert not (unexpected or unmeasured)` at
`smoke.yml:4385` on every run including Task 7's final one.

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
for sig in "<J_SIG>" "<J2_SIG>"; do
  printf '%-44s ' "$sig"
  grep -cF -- "$sig" .github/workflows/smoke.yml
done
```
Expected: a non-zero count for each. A `0` means the signature was not copied from the
arm's own source text — go back to `phase0-run1.md` and read it again. Costs a second;
being wrong costs a 15-minute run.

- [ ] **Step 2: Add arm (n1), the #94 pref-path arm**

Insert immediately after the arm (h) summary block, i.e. after the line printing
`      win: local('Segoe UI')=...` at `.github/workflows/smoke.yml:2581`. That is the
anchor; **do not** use "before the `# Web-font measurement` comment", which is 113 lines
further on at `:2694` with arm (h') in between. Arms (n2), (h3), (n4), (n5) and (n7) are
then each inserted directly after the previous one, so the six land as one contiguous
block starting at `:2582`.

```python
          # -----------------------------------------------------------
          # Arm (n1): #94, the pref-font path. gfxFontGroup::FindFontForChar
          # exit 7 (gfxTextRun.cpp:3576-3593) calls WhichPrefFontSupportsChar,
          # which walks mLangGroupPrefFonts[lang][generic] with NO gate of any
          # kind -- no CamouIsFontAllowed, no MaskedFontListBlocks, not even
          # IsVisibleToCSS. The memo is process-global and its key carries
          # neither a context id nor a FontVisibility, so the FIRST caller to
          # miss fixes the cell for the whole process, at context 0, where the
          # gate allows everything.
          #
          # Fixture. Context list ["Geneva"] (mac-only in fonts.json). Stack
          # '72px "Geneva", serif' -- naming a generic makes mFallbackGeneric
          # Serif (gfxTextRun.cpp:1998-2000), so the cell consulted is
          # [x-cyrillic][Serif]. U+1C80 is UBLOCK_CYRILLIC_EXTENDED_C, which has
          # a case in GetFontPrefLangFor, and the Unix block of all.js:2746 sets
          # font.name-list.serif.x-cyrillic to the literal "serif" -- which
          # fontconfig, under the bundle's own fonts.conf, answers with Tinos.
          #
          # WHY U+1C80. Scanned over every face and every cmap subtable of
          # bundle/fonts/{macos,windows,linux}: among families whose name does
          # not start with '.', ONLY Tinos and Arimo cover it. Both are
          # lin-only in fonts.json, so both gates refuse them under ["Geneva"],
          # and no mac family can answer instead -- which is what makes a RED
          # here attributable to the ungated pref path rather than to an
          # ordinary in-list fallback. Scan command:
          #   (see docs/superpowers/plans/2026-09-10-fonts-round3.md,
          #    "Fixture constants"; it prints ['arimo', 'tinos'])
          #
          # WHAT WOULD MAKE THIS PRINT A WRONG ANSWER (CLAUDE.md lesson 4):
          #  * The Tinos reference and the tofu floor could be equal, in which
          #    case "matched Tinos" and "rendered nothing" are the same number.
          #    Asserted below; if equal the arm scores nothing.
          #  * The Tinos reference is measured by FAMILY NAME in a BARE context.
          #    That is a SEPARATE browser process -- one_page_list_arg opens its
          #    own sync_playwright() -- so this is not a same-process
          #    comparison. What makes the two sides comparable is narrower and
          #    has to be stated as what it is: the same font FILES (one
          #    artifact, one FONTCONFIG_FILE), the same 72px size, the same
          #    canvas measureText path, and an advance width that is a property
          #    of the face rather than of the context. Arm (h) relies on the
          #    same property and states it the same way.
          #  * The reference launch's OWN font list contains Tinos -- its
          #    appended serif generic resolves there because no per-context list
          #    refuses it -- so its `fontlist` line would satisfy the "a carrier
          #    reached mFonts" branch below if it were in the window. Every
          #    camou_fl read is therefore taken BEFORE the reference launch, and
          #    the lines are additionally filtered to the fixture context's own
          #    ctx=. Either alone would do; both are cheap.
          #  * On a binary with no `fontlist` kind at all the precondition
          #    "the context's list resolved to no U+1C80 carrier" cannot be
          #    read. That is the width-only branch. It still scores: a width
          #    match against the bare reference IS #94's leak, and #94 needs a
          #    Phase 0 RED.
          N1_CP = 0x1C80          # CYRILLIC SMALL LETTER ROUNDED VE
          N1_PUA = 0xE000         # tofu floor: nothing bundled covers it
          N1_LIST = ["Geneva"]
          N1_OUTSIDE = "Tinos"    # the ctx-0 pref answer under the bundle conf

          JS_N1 = """(a) => {
            const c = document.createElement('canvas').getContext('2d');
            const out = {};
            c.font = '72px "' + a.named + '", serif';
            out.probe = c.measureText(String.fromCodePoint(a.cp)).width;
            out.floor = c.measureText(String.fromCodePoint(a.pua)).width;
            c.font = '72px "' + a.outside + '"';
            out.outsideDirect = c.measureText(String.fromCodePoint(a.cp)).width;
            return out;
          }"""

          def one_page_list_arg(font_list, js, arg):
              # one_page_arg() with an EXPLICIT list rather than a fonts.json
              # key. Same launch ({}), same context, same single page.
              with sync_playwright() as pw:
                  b = pw.firefox.launch(
                      executable_path=os.environ["CAMOUFOX_BIN"], headless=False,
                      env={**os.environ, "CAMOU_CONFIG": json.dumps({})})
                  ctx = b.new_context()
                  if font_list is not None:
                      ctx.add_init_script(
                          'if (typeof window.setFontList === "function") '
                          'window.setFontList(%s);' % json.dumps(",".join(font_list)))
                  page = ctx.new_page()
                  page.goto("data:text/html,<h1>n1</h1>")
                  result = page.evaluate(js, arg)
                  b.close()
                  return result

          def _ctx_tok(ln):
              """The `ctx=<n>` value of a CAMOU-FL line, or None."""
              tok = next((t for t in ln.split() if t.startswith("ctx=")), None)
              return tok[4:] if tok else None

          n1_mark = log_mark()
          n1 = one_page_list_arg(
              N1_LIST, JS_N1,
              {"named": "Geneva", "cp": N1_CP, "pua": N1_PUA,
               "outside": N1_OUTSIDE})
          # EVERY log read happens HERE, before the reference launch. The
          # reference runs with no per-context list, so its own appended serif
          # generic resolves to Tinos and its `fontlist` line names a U+1C80
          # carrier -- which is exactly the string the "a carrier reached
          # mFonts" branch below refuses on. camou_fl reads every file in
          # LOG_DIR and treats a file absent from the mark as offset 0
          # (smoke.yml:658-687), so a launch made after the mark IS inside the
          # window. Reading first is what keeps the fixture's window the
          # fixture's.
          n1_fl_all = camou_fl(n1_mark, "CAMOU-FL fontlist", limit=None)
          n1_pf_all = camou_fl(n1_mark, "CAMOU-FL pref-fallback", limit=None)
          # Second, independent narrowing: keep only the fixture context's own
          # lines. The fixture is the single launch in this window, so its ctx
          # is whichever non-zero id its `fontlist` lines carry.
          n1_ctxs = {c for c in (_ctx_tok(ln) for ln in n1_fl_all)
                     if c and c != "0"}
          n1_ctx = sorted(n1_ctxs)[0] if len(n1_ctxs) == 1 else None
          n1_fl = [ln for ln in n1_fl_all if _ctx_tok(ln) == n1_ctx] if n1_ctx else []
          n1_pf = [ln for ln in n1_pf_all if _ctx_tok(ln) == n1_ctx] if n1_ctx else []

          # The reference: Tinos's U+1C80 measured by family name in a BARE
          # context, where no per-context list gates anything.
          n1_ref = one_page_list_arg(
              None, JS_N1,
              {"named": "Geneva", "cp": N1_CP, "pua": N1_PUA,
               "outside": N1_OUTSIDE})["outsideDirect"]
          n1_have_fontlist = kind_total("fontlist") > 0
          print(f"  [arm n1 / #94] probe(U+1C80 in ['Geneva'])={n1['probe']} "
                f"floor(U+E000)={n1['floor']} tinos_ref={n1_ref} ctx={n1_ctx} "
                f"fontlist_lines={len(n1_fl)}/{len(n1_fl_all)} "
                f"pref_fallback_lines={len(n1_pf)}/{len(n1_pf_all)} "
                f"kind_totals: fontlist={kind_total('fontlist')} "
                f"pref-fallback={kind_total('pref-fallback')}")
          for _ln in (n1_fl + n1_pf)[-6:]:
              print(f"      {_ln}")

          n1_failures = []
          if abs(n1_ref - n1["floor"]) < 0.01:
              n1_failures.append(
                  f"control invalid: Tinos's U+1C80 width ({n1_ref}) equals the "
                  f"stack's own tofu floor ({n1['floor']}), so 'the pref path "
                  f"answered' and 'nothing rendered' are the same number and this "
                  f"arm cannot tell them apart")
          elif not n1_have_fontlist:
              # Binary predates the `fontlist` kind, so the precondition cannot
              # be READ -- but the width comparison stands on its own and is
              # what gives #94 its Phase 0 RED. The reference is a family-name
              # measurement of the very family the ctx-0 memo holds, so a match
              # is the leak; the tofu floor rules out "nothing rendered".
              if (abs(n1["probe"] - n1_ref) < 0.01
                      and abs(n1["probe"] - n1["floor"]) >= 0.01):
                  n1_failures.append(
                      f"PREF PATH LEAK (width-only, no `fontlist` kind in this "
                      f"binary): U+1C80 in a ['Geneva'] context measured "
                      f"{n1['probe']}, which is Tinos's width ({n1_ref}) measured by "
                      f"name in a bare context, and differs from this stack's own "
                      f"tofu floor ({n1['floor']}). Tinos is lin-only in fonts.json, "
                      f"so both gates refuse it and no allowed family covers U+1C80.")
              else:
                  print(f"  [arm n1 / #94] DIAGNOSTIC (binary emits no `fontlist` "
                        f"kind): U+1C80 measured {n1['probe']}, which is neither "
                        f"Tinos ({n1_ref}) nor the tofu floor ({n1['floor']}). Some "
                        f"third face answered; this arm cannot say which, and it "
                        f"scores nothing on this binary.")
          elif n1_ctx is None:
              n1_failures.append(
                  f"setup invalid: could not resolve a single non-zero ctx from this "
                  f"arm's `fontlist` lines (saw {sorted(n1_ctxs)}), so no line can be "
                  f"attributed to the fixture context")
          else:
              _mine = [ln for ln in n1_fl if "families=" in ln]
              # `families` is the LAST field of the format string and a key can
              # contain spaces, so the value runs to end of line.
              _fams = [ln.split("families=", 1)[1].strip() for ln in _mine]
              # Spec B1's GREEN is "width equals the tofu floor or a listed
              # family AND the log carries pref-fallback ... allowed=0"; its RED
              # is the width match AND no such line. Without this the GREEN also
              # covers "the pref path was never consulted at all", which is the
              # vacuous green lesson 4 is about.
              _refused = [ln for ln in n1_pf
                          if "key=tinos" in ln.lower() and "allowed=0" in ln]
              if not _mine:
                  n1_failures.append(
                      f"setup invalid: the run emitted {kind_total('fontlist')} "
                      f"`fontlist` lines but none for ctx={n1_ctx}, so the "
                      f"context's resolved family list could not be read")
              elif any(f == "" for f in _fams):
                  n1_failures.append(
                      "setup invalid: a `fontlist` line came back with an EMPTY "
                      "families= field, which is a child-process AsString failure "
                      "(SharedFontList.h:142-148), not an empty list")
              elif any(t in f.lower() for f in _fams for t in ("tinos", "arimo")):
                  n1_failures.append(
                      f"setup invalid: a U+1C80 carrier reached mFonts, so exit 4 "
                      f"answers before exit 7 and this arm tests nothing: {_mine[-1]}")
              elif abs(n1["probe"] - n1_ref) < 0.01:
                  n1_failures.append(
                      f"PREF PATH LEAK: U+1C80 in a ['Geneva'] context measured "
                      f"{n1['probe']}, which is Tinos's width ({n1_ref}) -- a "
                      f"lin-only family both gates refuse. pref-fallback lines for "
                      f"ctx={n1_ctx}: {len(n1_pf)}, of which "
                      f"{len(_refused)} refused tinos")
              elif not _refused:
                  n1_failures.append(
                      f"PREF PATH NOT CONSULTED: the width is right ({n1['probe']} vs "
                      f"tinos {n1_ref}, floor {n1['floor']}) but no "
                      f"`pref-fallback ctx={n1_ctx} key=tinos allowed=0` line exists, "
                      f"so this GREEN would also cover 'the read filter never ran'. "
                      f"pref-fallback lines for this ctx: {n1_pf[-3:] or 'none'}")
          if n1_failures:
              tripwires.append(f"(n1) ungated pref-font path (#94): {n1_failures}")
              # The marker is the common PREFIX of both verdict branches --
              # "PREF PATH LEAK" and "PREF PATH NOT CONSULTED". Passing only the
              # first would file a real NOT-CONSULTED verdict as unmeasured,
              # which is the opposite of what note_unmeasured is for.
              note_unmeasured("(n1)", n1_failures, "PREF PATH ")
          # -----------------------------------------------------------
```

- [ ] **Step 3: Add arm (n2), the #92 equal-width arm**

Insert immediately after arm (n1)'s closing `# ---` line.

```python
          # -----------------------------------------------------------
          # Arm (n2): #92, a generic under a per-context list must resolve to a
          # family of the RIGHT KIND. gfxFcPlatformFontList::FindGenericFamilies
          # calls FcFontSort with trim=FcFalse (gfxFcPlatformFontList.cpp:2760),
          # so it returns the WHOLE config sorted by fontconfig's distance
          # metric and the loop takes the first `limit` (default 3) families the
          # gate accepts. Under a mac list the three fontconfig answers
          # (Tinos/Arimo/Cousine) are all refused, so what comes back is three
          # families chosen by distance from a pattern the gate already emptied
          # of its real answer -- not by the generic. That is #92's mechanism.
          #
          # Fixture list ["Menlo", "Helvetica Neue", "Times"]: one family from
          # each of A2's three rows, all mac-only. Menlo is REQUIRED -- without
          # a monospace-row family the helper's fallback maps monospace and
          # sans-serif onto the same family and the arm is RED for a reason it
          # cannot show (spec-review I8).
          #
          # WHAT WOULD MAKE THIS PRINT A WRONG ANSWER (CLAUDE.md lesson 4):
          #  * `iiiii` == `mmmmm` is also true if NOTHING rendered. The
          #    sans-serif control must DIFFER on the same two strings in the
          #    same context and run; without it the arm is vacuous.
          #  * A monospace answer that is simply the default font would still
          #    show equal widths. The GREEN also requires generic-map to name a
          #    family, that family to be in the fixture list, and monospace's
          #    width to match Menlo named directly in the same context.
          #  * A `default-unfiltered` line for this context means the gated walk
          #    found nothing resident and the tail fired -- a fixture bug, not a
          #    fix. Counted and reported.
          N2_LIST = ["Menlo", "Helvetica Neue", "Times"]
          JS_N2 = """() => {
            const c = document.createElement('canvas').getContext('2d');
            const w = (font, s) => { c.font = font; return c.measureText(s).width; };
            const out = {};
            for (const g of ['monospace', 'sans-serif', 'serif']) {
              out[g + ':i'] = w('72px ' + g, 'iiiii');
              out[g + ':m'] = w('72px ' + g, 'mmmmm');
            }
            out['menlo:i'] = w('72px "Menlo"', 'iiiii');
            out['menlo:m'] = w('72px "Menlo"', 'mmmmm');
            return out;
          }"""

          n2_mark = log_mark()
          n2 = one_page_list_arg(N2_LIST, JS_N2, None)
          n2_gm = camou_fl(n2_mark, "CAMOU-FL generic-map", limit=None)
          n2_fl = camou_fl(n2_mark, "CAMOU-FL fontlist", limit=None)
          n2_du = camou_fl(n2_mark, "CAMOU-FL default-unfiltered", limit=None)
          print(f"  [arm n2 / #92] mono i/m={n2['monospace:i']}/{n2['monospace:m']} "
                f"sans i/m={n2['sans-serif:i']}/{n2['sans-serif:m']} "
                f"serif i/m={n2['serif:i']}/{n2['serif:m']} "
                f"menlo i/m={n2['menlo:i']}/{n2['menlo:m']} "
                f"generic-map={len(n2_gm)} fontlist={len(n2_fl)} "
                f"default-unfiltered={len(n2_du)}")
          for _ln in (n2_gm + n2_fl + n2_du)[-8:]:
              print(f"      {_ln}")

          n2_failures = []
          n2_mono_equal = abs(n2["monospace:i"] - n2["monospace:m"]) < 0.01
          n2_sans_equal = abs(n2["sans-serif:i"] - n2["sans-serif:m"]) < 0.01
          if n2_sans_equal:
              n2_failures.append(
                  f"control invalid: sans-serif measured 'iiiii' and 'mmmmm' at the "
                  f"same width ({n2['sans-serif:i']}), so equal widths do not mean "
                  f"monospaced here -- most likely nothing rendered at all")
          elif not n2_mono_equal:
              n2_failures.append(
                  f"GENERIC MISMAPPED: monospace measured 'iiiii'={n2['monospace:i']} "
                  f"and 'mmmmm'={n2['monospace:m']} -- a proportional face -- while "
                  f"sans-serif correctly differs. generic-map lines: "
                  f"{n2_gm[-3:] or 'none'}")
          elif kind_total("generic-map") > 0:
              # The fix is in this binary, so the log must corroborate the width.
              # `key` is the LAST field of
              # `generic-map ctx=%u generic=%d step=%s key=%s`, and a family key
              # can contain spaces -- A2's sans-serif row starts with
              # `Helvetica Neue`, which is in N2_LIST. Splitting on the first
              # space would yield "helvetica", which is in no fixture list, and
              # the arm would report the FIX as "named a family outside the
              # list" and fail the step in Phase 1. So key runs to end of line;
              # only `generic` and `step`, which are followed by another field,
              # may be split on whitespace.
              def _gm_last(ln, name):
                  return (ln.split(name + "=", 1)[1].strip()
                          if name + "=" in ln else "")

              def _gm_field(ln, name):
                  return (ln.split(name + "=", 1)[1].split(" ", 1)[0]
                          if name + "=" in ln else "")
              _keys = {}
              for _ln in n2_gm:
                  _keys.setdefault(_gm_field(_ln, "generic"), set()).add(
                      _gm_last(_ln, "key"))
              _flat = {k: sorted(v) for k, v in _keys.items()}
              _allowed = {f.casefold() for f in N2_LIST}
              _named = {k for vs in _keys.values() for k in vs} - {"none", ""}
              if not _named:
                  n2_failures.append(
                      f"setup invalid: the run emitted {kind_total('generic-map')} "
                      f"generic-map lines but every one in this arm's window says "
                      f"key=none, so no generic was resolved by the table: {_flat}")
              elif not _named.issubset(_allowed):
                  n2_failures.append(
                      f"generic-map named a family OUTSIDE the fixture list: "
                      f"{sorted(_named - _allowed)} (list={N2_LIST})")
              elif len(_named) < 2:
                  n2_failures.append(
                      f"generic-map named ONE family for every generic ({_named}), so "
                      f"monospace and sans-serif share a face and the equal-width "
                      f"reading above means nothing: {_flat}")
              elif abs(n2["monospace:m"] - n2["menlo:m"]) >= 0.01:
                  n2_failures.append(
                      f"monospace's width ({n2['monospace:m']}) does not match Menlo "
                      f"named directly in the same context ({n2['menlo:m']}), so the "
                      f"equal-width reading is some other monospaced face")
              elif n2_du:
                  n2_failures.append(
                      f"the unfiltered last-resort tail fired for this context "
                      f"({len(n2_du)} default-unfiltered lines) -- the gated walk "
                      f"found no resident family, which is a fixture bug: {n2_du[-2:]}")
          else:
              print(f"  [arm n2 / #92] DIAGNOSTIC (binary emits no `generic-map` "
                    f"kind): monospace is {'equal-width' if n2_mono_equal else 'PROPORTIONAL'} "
                    f"and the log cannot say which family answered.")
          if n2_failures:
              tripwires.append(f"(n2) generic -> family under a per-context list (#92): {n2_failures}")
              note_unmeasured("(n2)", n2_failures, "GENERIC MISMAPPED")
          # -----------------------------------------------------------
```

- [ ] **Step 4: Add arm (h3), the #88 default-font predicate**

B3 joins arm (h)'s launch, which is `one_page`'s bare `{}`
(`.github/workflows/smoke.yml:2175-2177`). It reads arm (h)'s **own** log window, so it
must be inserted after `h` is computed and after arm (h)'s `h_failures` block, and
before the `=== arms (e)-(h) summary ===` print. Arm (h)'s launches happen inside the
`e`/`f`/`g`/`h` assignment block; take the mark immediately before that block and pass
it in.

Spec §B3, verbatim, because the two GREEN shapes below are it:

> Extend arm (h): after `facename ... key=segoe ui allowed=0`, GREEN has two shapes and
> the arm says which fired: (i) the following `default ctx=6 family=X` names a family in
> the mac list; or (ii) no `default` line exists for that context at all **and** a
> `generic-map ctx=6 … key=<in-list family>` line shows the group resolved through A2's
> table instead (after A2, `monospace` maps to `Menlo`, `mFonts` is non-empty and
> `GetDefaultFont` is never reached — the fix removes the symptom the `default` line
> reported). Shape (ii) is only accepted when `generic-map` lines exist in the run; on a
> binary without that kind, a missing `default` line is SETUP-INVALID. That log predicate
> is the verdict. The width half is a discriminator only […]

`ctx=6` in that text is illustrative — it is run 34213805428's id. The arm reads the
context off the `facename` line and matches both following lines on it, as the code below
does; do not hardcode `6`.

First, immediately before the `e = {"mac": one_page("mac", JS_E), ...}` line
(`.github/workflows/smoke.yml:2205`), insert:

```python
          # Arm (h3) reads the log window arms (e)-(h) produce, so the mark has
          # to be taken before their launches, not after.
          efgh_mark = log_mark()
```

Then, immediately after arm (h)'s `h_failures` loop ends and before
`if e_failures:` (`.github/workflows/smoke.yml:2562`), insert:

```python
          # -----------------------------------------------------------
          # Arm (h3): #88. Arm (h) proved the face-name gate FIRES for the mac
          # probes -- the diag build logged ctx with a list, allowed=0 -- and
          # the text still rendered at 375.70001220703125. What serves that text
          # is gfxFontGroup::GetDefaultFont (gfxTextRun.cpp:2201-2320), which
          # opens NO AutoFontListContext and whose shared-list last-resort walk
          # (:2237-2263) has no gate at all. The verdict here is the LOG
          # PREDICATE: the `default ctx=N family=X` line that follows the mac
          # context's `facename ... key=segoe ui allowed=0` must name a family
          # the mac context's list contains.
          #
          # WHAT WOULD MAKE THIS PRINT A WRONG ANSWER (CLAUDE.md lesson 4):
          #  * The width half is NOT the verdict. #88's own comment records that
          #    262 of 513 bundled mac families tie at the target width, so an
          #    equality is not an identification. It is kept only as a
          #    discriminator, and the arm says so out loud when it cannot
          #    discriminate.
          #  * ctx is NOT hardcoded. Run 34213805428 happened to use ctx=6; the
          #    id depends on how many contexts preceded this arm. It is read off
          #    the `facename` line and the following `default` line is matched
          #    on the same id.
          #  * MATCHING ON ctx ALONE IS NOT ENOUGH, and this is the reason the
          #    reads below go through ONE camou_fl call. camou_fl iterates
          #    `for p in sorted(glob(...))` and only then the lines of each file
          #    (smoke.yml:658-687), so its output is grouped by cfx<PID> in
          #    LEXICOGRAPHIC file order -- `[-1]` is "last line of the
          #    last-sorting file", not "most recent". This arm's window is
          #    efgh_mark, which spans arms (e), (f), (f_control), (g) and (h):
          #    eight separate one_page() launches, eight browser processes,
          #    eight log files. Playwright allocates user-context ids per
          #    browser, so a later launch very likely reuses the same numeric
          #    id, and a ctx-only match would tie arm (h)'s `facename` line to
          #    some other arm's `default` line. The spec says "the FOLLOWING
          #    default line", which means: same log file, later in that file.
          #    Reading every CAMOU-FL line of the window once and filtering the
          #    ordered list in Python expresses both -- the file basename is
          #    each line's first token, and position is the list index -- and
          #    needs no new helper.
          def _ctx_of(ln):
              tok = next((t for t in ln.split() if t.startswith("ctx=")), None)
              return tok[4:] if tok else None

          #  * THE OBSERVABLE MOVES WHEN A2 LANDS, and scoring its absence as a
          #    broken setup would fail the very build that fixes #88.
          #    `CAMOU-FL default` is emitted only from
          #    gfxFontGroup::GetDefaultFont (gfxTextRun.cpp:2316), which is
          #    reached only when the group's own list resolved to NOTHING.
          #    Arm (h)'s stack is '48px "ProbeH_full", monospace'
          #    (smoke.yml:2120-2123). Today, under FONTCONFIG_FILE and a mac
          #    list, `monospace` -> Cousine and the appended `serif` -> Tinos,
          #    both lin-only and both refused, so mFonts is empty and the line
          #    fires -- that is the Phase 0 RED. AFTER A2, CamouGenericCandidate
          #    answers `monospace` from the table with Menlo (mac-only,
          #    bundled), mFonts is non-empty, GetFirstValidFont returns a real
          #    font, GetDefaultFont is never called, and NO `default` line
          #    exists for that context. So there are two GREEN shapes and the
          #    arm reports which one fired:
          #      shape A  a `default ctx=N family=X` line with X in the mac list
          #      shape B  no `default` line for that ctx, TOGETHER WITH a
          #               `generic-map ctx=N ... key=<in-list family>` line
          #               proving the group resolved through the table instead
          #    Shape B is only available once the binary emits `generic-map`;
          #    before that, a missing `default` line really is a broken setup.
          #    kind_total("generic-map") is what tells the two apart.
          def _file_of(ln):
              """The cfx<PID> basename camou_fl prefixes to every line."""
              parts = ln.split(None, 1)
              return parts[0] if parts else ""

          # ONE read of the whole window, in (file, line) order, then filtered
          # in Python. This is what lets "the following default line" mean the
          # same file and a later position, not merely the same ctx number.
          h3_all = camou_fl(efgh_mark, "CAMOU-FL ", limit=None)
          h3_face_idx = [i for i, ln in enumerate(h3_all)
                         if "CAMOU-FL facename" in ln and "key=segoe ui" in ln
                         and "allowed=0" in ln]
          h3_face = [h3_all[i] for i in h3_face_idx]
          h3_unfiltered = [ln for ln in h3_all if "CAMOU-FL default-unfiltered" in ln]
          h3_ctx = _ctx_of(h3_face[-1]) if h3_face else None
          h3_pos = h3_face_idx[-1] if h3_face_idx else -1
          h3_file = _file_of(h3_face[-1]) if h3_face else None
          # Same file, same ctx, and AFTER the refusal.
          h3_after = ([ln for i, ln in enumerate(h3_all)
                       if i > h3_pos and "CAMOU-FL default " in ln
                       and _file_of(ln) == h3_file and _ctx_of(ln) == h3_ctx]
                      if h3_ctx else [])
          h3_family = (h3_after[-1].split("family=", 1)[1].strip()
                       if h3_after and "family=" in h3_after[-1] else None)
          h3_maclist = {f.casefold() for f in FONTS["mac"]}
          # `key` is the last field of the generic-map line and may contain
          # spaces, so it runs to end of line -- same rule as arm (n2). Shape B
          # asserts that ARM (h)'s OWN group resolved through the table, so the
          # same file/ctx pinning applies; the position bound is dropped because
          # EnsureFontList runs BEFORE the face-name lookup, so a generic-map
          # line for this group legitimately precedes the facename line.
          h3_gm_mine = ([ln for ln in h3_all
                         if "CAMOU-FL generic-map" in ln
                         and _file_of(ln) == h3_file and _ctx_of(ln) == h3_ctx]
                        if h3_ctx else [])
          h3_gm = [ln for ln in h3_all if "CAMOU-FL generic-map" in ln]
          h3_gm_keys = {ln.split("key=", 1)[1].strip().casefold()
                        for ln in h3_gm_mine if "key=" in ln} - {"none", ""}
          h3_gm_inlist = sorted(k for k in h3_gm_keys if k in h3_maclist)
          print(f"  [arm h3 / #88] facename refusals for 'segoe ui': {len(h3_face)}; "
                f"file={h3_file} ctx={h3_ctx}; `default` lines in that file after the "
                f"refusal: {len(h3_after)}; family={h3_family!r}; "
                f"default-unfiltered={len(h3_unfiltered)}; generic-map in that file for "
                f"that ctx: {len(h3_gm_mine)} of {len(h3_gm)} in the window; "
                f"keys={sorted(h3_gm_keys)} in-list={h3_gm_inlist}; "
                f"kind_total(generic-map)={kind_total('generic-map')}")
          for _ln in (h3_face[-2:] + h3_after[-2:] + h3_gm_mine[-2:]):
              print(f"      {_ln}")

          h3_failures = []
          if kind_total("facename") == 0:
              print("  [arm h3 / #88] DIAGNOSTIC: this binary emits no `facename` "
                    "line, so the refusal this predicate follows cannot be seen.")
          elif not h3_face:
              h3_failures.append(
                  f"setup invalid: the run emitted {kind_total('facename')} facename "
                  f"lines but none with key=segoe ui allowed=0 in arm (h)'s window, so "
                  f"the refusal this predicate follows never happened")
          elif h3_family is None and kind_total("generic-map") > 0:
              # SHAPE B. A2 is in this binary and the group never needed a
              # default font. That is the fix working, not a broken fixture --
              # but only if the table demonstrably answered with an in-list
              # family for this same context.
              if h3_gm_inlist:
                  print(f"  [arm h3 / #88] GREEN, shape B: no `default` line for "
                        f"ctx={h3_ctx} -- the group never fell to the default font -- "
                        f"and generic-map resolved {h3_gm_inlist} from the context's "
                        f"own list. GetDefaultFont was not reached, which is what A2 "
                        f"is for.")
              else:
                  h3_failures.append(
                      f"DEFAULT FONT OUTSIDE THE LIST: no `default` line for "
                      f"ctx={h3_ctx} AND no generic-map line naming an in-list family "
                      f"for it, so nothing shows how the group resolved. generic-map "
                      f"keys seen: {sorted(h3_gm_keys) or 'none'}")
          elif h3_family is None:
              h3_failures.append(
                  f"setup invalid: no `CAMOU-FL default` line for ctx={h3_ctx} after "
                  f"the refusal, and this binary emits no `generic-map` kind, so the "
                  f"face that served the text was never named")
          elif h3_family.casefold() not in h3_maclist:
              h3_failures.append(
                  f"DEFAULT FONT OUTSIDE THE LIST: after refusing 'segoe ui' for "
                  f"ctx={h3_ctx}, GetDefaultFont served {h3_family!r}, which is not in "
                  f"the mac list. default-unfiltered lines: {len(h3_unfiltered)}")
          else:
              print(f"  [arm h3 / #88] GREEN, shape A: `default ctx={h3_ctx} "
                    f"family={h3_family}` names a family in the mac list.")
              # Discriminator only, and it says so when it discriminates nothing.
              _target = h["mac"]["hFull"]
              _others = [h["mac"]["baseline"], h["mac"]["sans"], h["mac"]["serif"]]
              if all(abs(_target - o) < 0.01 for o in _others):
                  print(f"  [arm h3 / #88] the width half asserts NOTHING this run: "
                        f"{_target} equals every other in-context reference "
                        f"{_others}, and 262 of 513 mac families tie at the #88 "
                        f"target. The log predicate above is the verdict.")
              else:
                  print(f"  [arm h3 / #88] discriminator OK: refused-probe width "
                        f"{_target} differs from at least one in-context reference "
                        f"{_others}.")
          if h3_failures:
              tripwires.append(f"(h3) default font after a per-context refusal (#88): {h3_failures}")
              note_unmeasured("(h3)", h3_failures, "DEFAULT FONT OUTSIDE THE LIST")
          # -----------------------------------------------------------
```

- [ ] **Step 5: Add arm (n4), the #82 donor/victim fixture**

Insert immediately after arm (j2)'s tripwire block, i.e. after the
`note_unmeasured("(j2)", j2_failures, "REPLACEMENT-CHAR CACHE LEAK")` line at
`.github/workflows/smoke.yml:4248`, and before the `EXPECTED_RED` assignment.

```python
          # -----------------------------------------------------------
          # Arm (n4): #82. mReplacementCharFallbackFamily is a per-process,
          # per-FontVisibility-level cache of the family that answered U+FFFD.
          # PR #93 gates the read (gfxPlatformFontList.cpp:1409-1427); this arm
          # is the measurement that gate never had.
          #
          # Fixture, traced exit by exit in the spec review: donor ["Times",
          # "Menlo"], victim ["Times", "Geneva"], both stacks "Times" only.
          # Times is 4/4 faces WITHOUT U+FFFD; A2's serif row starts with Times,
          # which both lists contain, so the appended default generic (serif,
          # from all.js:2038 via GetDefaultGeneric(x-western)) also resolves to
          # Times and both groups read families=times,times. The only U+FFFD
          # carrier the donor can reach is Menlo, through system fallback.
          # U+FFFD is the FIRST character of its own text run so aPrevMatchedFont
          # (exit 8) is empty.
          #
          # WHAT WOULD MAKE THIS PRINT A WRONG ANSWER (CLAUDE.md lesson 4):
          #  * Two contexts in different content processes share no cache at
          #    all, so the arm would read GREEN for a leak it never exposed.
          #    two_contexts_one_launch forces dom.ipc.processCount=1 and the
          #    pids are ASSERTED equal, not assumed.
          #  * mReplacementCharFallbackFamily is indexed by FontVisibility
          #    LEVEL. Both pages are same-scheme (data:) content documents, so
          #    both groups sit at the same level; a mismatch reads an empty slot
          #    and looks exactly like the pre-#93 report B6 keys on.
          #  * The victim's own tofu floor and Menlo's U+FFFD width could be
          #    equal, in which case "leaked" and "rendered nothing" are the same
          #    number. Asserted.
          #  * On a binary with no CAMOU-FL kinds at all (build 34236331658 @
          #    8990915 emits zero) none of the four log preconditions can be
          #    read. That is the width-only diagnostic branch, and its reading
          #    is what triggers B6.
          N4_DONOR = ["Times", "Menlo"]
          N4_DONOR_ALT = ["Times", "Lucida Grande"]   # recovery fixture
          N4_VICTIM = ["Times", "Geneva"]
          JS_N4 = """() => {
            const c = document.createElement('canvas').getContext('2d');
            const out = {};
            c.font = '72px "Times"';
            // U+FFFD first in its own measureText call, so aPrevMatchedFont is
            // empty when FindFontForChar runs for it.
            out.fffd = c.measureText('\\uFFFD').width;
            out.floor = c.measureText('\\uE000').width;
            return out;
          }"""
          JS_N4_REF = """() => {
            const c = document.createElement('canvas').getContext('2d');
            c.font = '72px "Menlo"';
            return {menlo: c.measureText('\\uFFFD').width};
          }"""

          n4_mark = log_mark()
          n4_a, n4_b, n4_pids = two_contexts_one_launch(
              N4_DONOR, N4_VICTIM, JS_N4,
              extra_prefs={"gfx.font_rendering.fallback.async": False,
                           "fission.autostart": False})
          # Every log read BEFORE the reference launch, for the reason stated in
          # the log-window discipline note at the head of this task.
          n4_fl = camou_fl(n4_mark, "CAMOU-FL fontlist", limit=None)
          n4_sys = camou_fl(n4_mark, "CAMOU-FL sys-fallback", "ch=U+FFFD", limit=None)
          n4_cache = camou_fl(n4_mark, "CAMOU-FL fffd-cache", limit=None)
          n4_pf = camou_fl(n4_mark, "CAMOU-FL pref-fallback", limit=None)
          n4_ref = one_page_list_arg(None, JS_N4_REF, None)["menlo"]
          # Spec B4 wants FOUR preconditions, two of them per context: the
          # donor's `fontlist` line AND the victim's, each times=times with no
          # carrier. `any(...)` over the whole window satisfies both with one
          # line and would pass a run in which the victim resolved something
          # else entirely. Resolve each context id from the line that is unique
          # to it -- the donor is the context that populated the cache
          # (sys-fallback), the victim is the one that read it (fffd-cache) --
          # and then assert each context's own fontlist line.
          # The donor is the context whose sys-fallback line names a REAL
          # family. `sys-fallback` is emitted UNCONDITIONALLY after the call,
          # not inside `if (font)` (gfxTextRun.cpp:3623-3630), with
          # `resolved=none` when nothing was found -- so the VICTIM emits one
          # too: it reaches WhichSystemFontSupportsChar (that is where the
          # fffd-cache read this arm needs lives) and comes back null once the
          # gate refuses Menlo. Its line is written after the donor's, in the
          # same content-process file under dom.ipc.processCount=1, so
          # `n4_sys[-1]` is the victim's and both ids would come out equal --
          # tripping this arm's own "one context cannot leak to itself" branch
          # on the very build where #82's only GREEN has to come from.
          # Filter on the same predicate the arm already asserts further down.
          _n4_sys_ok = [ln for ln in n4_sys
                        if "resolved=" in ln
                        and not ln.rstrip().endswith("resolved=none")]
          n4_donor_ctx = _ctx_tok(_n4_sys_ok[-1]) if _n4_sys_ok else None
          n4_victim_ctx = _ctx_tok(n4_cache[-1]) if n4_cache else None

          def _n4_families(ctx):
              return [ln.split("families=", 1)[1].strip()
                      for ln in n4_fl
                      if "families=" in ln and _ctx_tok(ln) == ctx]
          # _ctx_tok is defined in arm (n1) above. Both arms live in the same
          # `python - <<'PY'` heredoc -- (n1) is inserted around smoke.yml:2582
          # and this arm around :4248 -- so it is in scope here.
          print(f"  [arm n4 / #82] donor fffd={n4_a['fffd']} floor={n4_a['floor']}; "
                f"victim fffd={n4_b['fffd']} floor={n4_b['floor']}; "
                f"menlo_ref={n4_ref}; pids={n4_pids}; "
                f"donor_ctx={n4_donor_ctx} victim_ctx={n4_victim_ctx}; "
                f"fontlist={len(n4_fl)} sys-fallback(U+FFFD)={len(n4_sys)} "
                f"fffd-cache={len(n4_cache)} pref-fallback={len(n4_pf)}")
          for _ln in (n4_fl + n4_sys + n4_cache + n4_pf)[-10:]:
              print(f"      {_ln}")

          n4_failures = []
          # Keyed on `fontlist` ALONE, not on fffd-cache. 34432908522 @ 163ee25
          # emits fffd-cache but not fontlist, so an `or` here would be flipped
          # true by one fffd-cache line from arm (j) earlier in the run, take
          # the log branch, find no fontlist lines and report SETUP-INVALID on a
          # binary that was never going to have them. Every precondition in the
          # log branch below reads `fontlist`; that is the kind to test.
          n4_have_log = kind_total("fontlist") > 0
          if isinstance(n4_pids["after_a"], str) or isinstance(n4_pids["after_b"], str):
              n4_failures.append(
                  f"setup invalid: pgrep failed, so 'same process' could not be "
                  f"asserted: {n4_pids}")
          elif not (n4_pids["after_a"] & n4_pids["after_b"]):
              n4_failures.append(
                  f"setup invalid: donor and victim rendered in different content "
                  f"processes, and mReplacementCharFallbackFamily is a per-process "
                  f"singleton, so nothing could have been shared: {n4_pids}")
          elif abs(n4_ref - n4_b["floor"]) < 0.01:
              n4_failures.append(
                  f"control invalid: Menlo's U+FFFD width ({n4_ref}) equals the "
                  f"victim's own tofu floor ({n4_b['floor']}), so a leak and an empty "
                  f"render are the same number")
          elif not n4_have_log:
              # Build 34236331658 @ 8990915: zero CAMOU-FL lines of any kind.
              _leak = abs(n4_b["fffd"] - n4_ref) < 0.01
              _tofu = abs(n4_b["fffd"] - n4_b["floor"]) < 0.01
              _donor_menlo = abs(n4_a["fffd"] - n4_ref) < 0.01
              print(f"  [arm n4 / #82] DIAGNOSTIC (binary emits no CAMOU-FL kind): "
                    f"donor {'reached Menlo' if _donor_menlo else 'did NOT reach Menlo'}; "
                    f"victim read {'MENLO (leak)' if _leak else 'its tofu floor' if _tofu else 'neither'}. "
                    f"B6 TRIGGER = donor did not reach Menlo, i.e. something answered "
                    f"U+FFFD before SystemFindFontForChar; record which of the bundle's "
                    f"U+FFFD carriers the widths match.")
          else:
              _don = _n4_families(n4_donor_ctx)
              _vic = _n4_families(n4_victim_ctx)
              _pf_menlo = [ln for ln in n4_pf if "key=menlo" in ln and "allowed=1" in ln]

              def _times_only(fams):
                  return bool(fams) and all(
                      "times" in f.lower() and "menlo" not in f.lower()
                      and "lucida" not in f.lower() for f in fams)

              if n4_donor_ctx is None or n4_victim_ctx is None:
                  n4_failures.append(
                      f"setup invalid: could not resolve the donor's ctx from a "
                      f"`sys-fallback ch=U+FFFD resolved=<family>` line "
                      f"({n4_donor_ctx}; {len(n4_sys)} sys-fallback lines, "
                      f"{len(_n4_sys_ok)} of them naming a family) or the victim's "
                      f"from a `fffd-cache` line ({n4_victim_ctx}), so neither "
                      f"context's fontlist line can be identified")
              elif n4_donor_ctx == n4_victim_ctx:
                  n4_failures.append(
                      f"setup invalid: the donor and the victim resolved to the SAME "
                      f"ctx ({n4_donor_ctx}); one context cannot leak to itself")
              elif not _don or not _vic:
                  n4_failures.append(
                      f"setup invalid: {kind_total('fontlist')} `fontlist` lines in the "
                      f"run, but {len(_don)} for the donor (ctx={n4_donor_ctx}) and "
                      f"{len(_vic)} for the victim (ctx={n4_victim_ctx}); spec B4 wants "
                      f"both, separately")
              elif any(f == "" for f in _don + _vic):
                  n4_failures.append(
                      "setup invalid: a `fontlist` line has an EMPTY families= field, "
                      "which is a child-process AsString failure, not an empty list")
              elif not _times_only(_don):
                  n4_failures.append(
                      f"setup invalid: the DONOR (ctx={n4_donor_ctx}) did not resolve "
                      f"to Times-only, so a carrier is in mFonts and exit 4 answers "
                      f"before the cache: {_don}")
              elif not _times_only(_vic):
                  n4_failures.append(
                      f"setup invalid: the VICTIM (ctx={n4_victim_ctx}) did not resolve "
                      f"to Times-only, so its own stack could cover U+FFFD and a GREEN "
                      f"would not be the gate's doing: {_vic}")
              elif _pf_menlo:
                  n4_failures.append(
                      f"setup invalid: the donor's PREF path answered with Menlo "
                      f"({_pf_menlo[-1]}), so the cache was never populated by system "
                      f"fallback. Re-run this arm with the recovery fixture "
                      f"{N4_DONOR_ALT}, a carrier fontconfig's serif/sans candidates "
                      f"do not reach")
              elif not any("resolved=Menlo" in ln for ln in n4_sys):
                  n4_failures.append(
                      f"setup invalid: no `sys-fallback ctx=… ch=U+FFFD resolved=Menlo` "
                      f"line, so the donor never populated the cache: "
                      f"{n4_sys[-2:] or 'no sys-fallback lines at all'}")
              elif not any("key=menlo" in ln and "allowed=0" in ln for ln in n4_cache):
                  n4_failures.append(
                      f"setup invalid: no `fffd-cache ctx=… key=menlo allowed=0` line, "
                      f"so the victim never reached the cached-family read: "
                      f"{n4_cache[-2:] or 'no fffd-cache lines at all'}")
              elif abs(n4_b["fffd"] - n4_ref) < 0.01:
                  n4_failures.append(
                      f"U+FFFD CACHE LEAK: the victim rendered U+FFFD at {n4_b['fffd']}, "
                      f"which is Menlo's width ({n4_ref}) -- a family its own list "
                      f"excludes -- despite `fffd-cache … key=menlo allowed=0`")
              elif abs(n4_b["fffd"] - n4_b["floor"]) >= 0.01:
                  n4_failures.append(
                      f"the victim rendered U+FFFD at {n4_b['fffd']}, which is neither "
                      f"Menlo ({n4_ref}) nor its own tofu floor ({n4_b['floor']}); some "
                      f"third face answered and this arm cannot say which")
          if n4_failures:
              tripwires.append(f"(n4) replacement-char cache, donor/victim (#82): {n4_failures}")
              note_unmeasured("(n4)", n4_failures, "U+FFFD CACHE LEAK")
          # -----------------------------------------------------------
```

- [ ] **Step 6: Add arm (n5), the #90 speech-voices measurement**

Insert immediately after arm (n4). This is the gate Task 6 branches on.

```python
          # -----------------------------------------------------------
          # Arm (n5): #90. SpeechVoicesManager keeps its per-context voice list
          # in a process-local nsTHashMap (sVoicesMap,
          # patches/speech-voices-spoofing.patch) while its one-shot disable
          # flag goes through the cross-process RoverfoxStorageManager -- the
          # same asymmetry #83 turned out to be. This arm MEASURES it; the fix
          # (A4) lands only if this is RED.
          #
          # WHAT WOULD MAKE THIS PRINT A WRONG ANSWER (CLAUDE.md lesson 4):
          #  * getVoices() is legitimately empty until `voiceschanged` fires, so
          #    an empty read is not evidence of anything on its own. Read after
          #    goto() AND after the event, and report both.
          #  * The init script runs in juggler's ISOLATED world, so a window
          #    global it sets is invisible to page.evaluate(). Every page-world
          #    value comes back through a DOM attribute (the #83 shape).
          #  * Playwright runs init scripts on EVERY navigation and new_page()
          #    lands on about:blank first, so a one-shot setter registered
          #    before new_page() is already spent. add_init_script comes AFTER
          #    new_page(), exactly as probe_windows_fonts.py:640-646 does it.
          #  * A context reading an empty list while the pid set did not change
          #    is not a cross-process finding. pids are sampled between
          #    new_page() and goto() and reported with the verdict.
          N5_A = ["Alpha One", "Alpha Two"]
          N5_B = ["Beta One", "Beta Two"]
          N5_INIT = (
              '(() => {'
              ' const saw = (typeof window.setSpeechVoices === "function");'
              ' let applied = false, err = null;'
              ' if (saw) { try { window.setSpeechVoices(%s); applied = true; }'
              '            catch (e) { err = String(e); } }'
              ' const mark = () => { try { document.documentElement.setAttribute('
              '   "data-sv", JSON.stringify({saw, applied, err})); } catch (e) {} };'
              ' mark(); document.addEventListener("DOMContentLoaded", mark);'
              '})()'
          )
          JS_N5 = """async () => {
            const read = () => speechSynthesis.getVoices().map(v => v.name);
            const first = read();
            await new Promise(r => {
              if (read().length) { r(); return; }
              speechSynthesis.addEventListener('voiceschanged', r, {once: true});
              setTimeout(r, 4000);
            });
            const after = read();
            const n = document.createElement('script');
            n.type = 'application/json'; n.id = 'n5';
            n.textContent = JSON.stringify({first, after});
            document.documentElement.appendChild(n);
            return {first, after,
                    dataSv: document.documentElement.getAttribute('data-sv')};
          }"""

          def n5_two_contexts():
              out = {}
              with sync_playwright() as pw:
                  b = pw.firefox.launch(
                      executable_path=os.environ["CAMOUFOX_BIN"], headless=False,
                      firefox_user_prefs={"dom.ipc.processCount": 1},
                      env={**os.environ, "CAMOU_CONFIG": json.dumps({})})
                  for label, voices in (("a", N5_A), ("b", N5_B)):
                      ctx = b.new_context()
                      page = ctx.new_page()
                      pids_before = tab_pids()
                      ctx.add_init_script(N5_INIT % json.dumps(",".join(voices)))
                      page.goto("data:text/html,<h1>n5-%s</h1>" % label)
                      out[label] = {"res": page.evaluate(JS_N5),
                                    "pids_before": pids_before,
                                    "pids_after": tab_pids(),
                                    "want": voices}
                  b.close()
              return out

          n5 = n5_two_contexts()
          for _lbl in ("a", "b"):
              print(f"  [arm n5 / #90] ctx {_lbl}: want={n5[_lbl]['want']} "
                    f"first={n5[_lbl]['res']['first']} after={n5[_lbl]['res']['after']} "
                    f"data-sv={n5[_lbl]['res']['dataSv']} "
                    f"pids {n5[_lbl]['pids_before']} -> {n5[_lbl]['pids_after']}")

          n5_failures = []
          for _lbl in ("a", "b"):
              _sv = n5[_lbl]["res"]["dataSv"]
              if not _sv or '"applied":true' not in _sv.replace(" ", ""):
                  n5_failures.append(
                      f"setup invalid: ctx {_lbl}'s init script did not apply "
                      f"setSpeechVoices on the document that was measured "
                      f"(data-sv={_sv!r}); with no list installed a context is allowed "
                      f"everything and a wrong reading is indistinguishable from a leak")
          if not n5_failures:
              for _lbl, _other in (("a", "b"), ("b", "a")):
                  _got = set(n5[_lbl]["res"]["after"])
                  _want = set(n5[_lbl]["want"])
                  _theirs = set(n5[_other]["want"])
                  if _got & _theirs:
                      n5_failures.append(
                          f"VOICES LEAK: ctx {_lbl} read {sorted(_got & _theirs)}, which "
                          f"belongs to ctx {_other}; pids {n5[_lbl]['pids_before']} -> "
                          f"{n5[_lbl]['pids_after']}")
                  elif not _got:
                      n5_failures.append(
                          f"VOICES LEAK: ctx {_lbl} read an EMPTY voice list after "
                          f"`voiceschanged` while its own list was installed; pids "
                          f"{n5[_lbl]['pids_before']} -> {n5[_lbl]['pids_after']}")
                  elif not _got.issubset(_want):
                      n5_failures.append(
                          f"VOICES LEAK: ctx {_lbl} read {sorted(_got - _want)}, which is "
                          f"in neither context's configured list")
          if n5_failures:
              tripwires.append(f"(n5) per-context speech voices (#90): {n5_failures}")
              note_unmeasured("(n5)", n5_failures, "VOICES LEAK")
          # -----------------------------------------------------------
```

- [ ] **Step 7: Add arm (n7), the #91 real-load-status arm**

Insert immediately after arm (n5). This arm needs an HTTP origin: the smoke's
navigations are all `data:`, an opaque origin from which an absolute `http://` font
`url()` is a CORS-blocked cross-origin fetch, so **both** faces would read `error` for
a reason that has nothing to do with #91.

```python
          # -----------------------------------------------------------
          # Arm (n7): #91. FontFaceImpl::SetStatus discards aStatus entirely and
          # writes Loaded/Error from a family-name gate, so a url() face whose
          # download 404s still reports `loaded`. FontFace::Status() never reads
          # mStatus at all (FontFace.cpp:285-289), and FontFace::Load() resolves
          # its promise from the same gate rather than from the load.
          #
          # WHY AN HTTP SERVER. Every other navigation in this file is
          # `data:text/html,...`, which is an OPAQUE origin. An absolute
          # http:// font url() from an opaque origin is a cross-origin font
          # fetch with no CORS and is blocked before the network result matters,
          # so the 404 face AND the control face would both read `error` -- a
          # RED that looks exactly like a real one (spec-review I6).
          #
          # WHAT WOULD MAKE THIS PRINT A WRONG ANSWER (CLAUDE.md lesson 4):
          #  * document.fonts.ready does not guarantee a face LEFT `loading`.
          #    Each face is scored from its own .loaded promise, with a poll as
          #    the backstop.
          #  * The control face is the run-time fontTools probe from arm (k)
          #    (build_probe_k): unitsPerEm 1000, glyph 'a' advancing 2000, so 20
          #    glyphs at 48px measure exactly 1920 IF AND ONLY IF that face
          #    rendered. It differs from any fallback by construction rather
          #    than by assumption, which is the whole point.
          import base64 as _b64_n7
          import http.server as _http_n7
          import socketserver as _sock_n7
          import threading as _thr_n7

          n7_font_bytes = None
          try:
              _uri = build_probe_k()
              n7_font_bytes = _b64_n7.b64decode(_uri.split(",", 1)[1])
          except Exception as _exc:
              print(f"  [arm n7 / #91] SKIP: could not build the control font: "
                    f"{type(_exc).__name__}: {_exc}")

          if n7_font_bytes:
              N7_PAGE = (
                  b"<!doctype html><meta charset=utf-8><title>n7</title>"
                  b"<style>"
                  b"@font-face { font-family: N7Ctl; src: url('/ctl.ttf'); }"
                  b"@font-face { font-family: N7Bad; src: url('/nope.ttf'); }"
                  b"</style><body><h1>n7</h1>"
              )

              class _N7Handler(_http_n7.SimpleHTTPRequestHandler):
                  def log_message(self, *a):
                      pass

                  def do_GET(self):
                      if self.path.startswith("/ctl.ttf"):
                          body, code, ctype = n7_font_bytes, 200, "font/ttf"
                      elif self.path.startswith("/nope.ttf"):
                          body, code, ctype = b"not found", 404, "text/plain"
                      else:
                          body, code, ctype = N7_PAGE, 200, "text/html; charset=utf-8"
                      self.send_response(code)
                      self.send_header("Content-Type", ctype)
                      self.send_header("Content-Length", str(len(body)))
                      self.end_headers()
                      self.wfile.write(body)

              # allow_reuse_address is a CLASS attribute read inside
              # server_bind, so setting it on the instance after construction
              # does nothing. Set it on the subclass instead -- though with port
              # 0 the kernel picks a free port and it never mattered.
              _sock_n7.TCPServer.allow_reuse_address = True
              _srv = _sock_n7.TCPServer(("127.0.0.1", 0), _N7Handler)
              n7_port = _srv.server_address[1]
              _thr_n7.Thread(target=_srv.serve_forever, daemon=True).start()

              JS_N7 = """async () => {
                const faces = {};
                for (const f of document.fonts) {
                  const name = f.family.replace(/^["']|["']$/g, '');
                  faces[name] = f;
                }
                const score = async (name) => {
                  const f = faces[name];
                  if (!f) return 'NO_FACE_FOUND';
                  try { await f.loaded; } catch (e) { /* rejected -> read status */ }
                  for (let i = 0; i < 40 && f.status === 'loading'; i++) {
                    await new Promise(r => setTimeout(r, 100));
                  }
                  return f.status;
                };
                const c = document.createElement('canvas').getContext('2d');
                const s = 'aaaaaaaaaaaaaaaaaaaa';   // 20 glyphs -> 1920 at 48px
                c.font = '48px monospace';
                const baseline = c.measureText(s).width;
                const ctlStatus = await score('N7Ctl');
                const badStatus = await score('N7Bad');
                c.font = '48px "N7Ctl", monospace';
                const ctlWidth = c.measureText(s).width;
                return {ctlStatus, badStatus, ctlWidth, baseline};
              }"""

              def n7_run(font_list):
                  with sync_playwright() as pw:
                      b = pw.firefox.launch(
                          executable_path=os.environ["CAMOUFOX_BIN"], headless=False,
                          env={**os.environ, "CAMOU_CONFIG": json.dumps({})})
                      ctx = b.new_context()
                      page = ctx.new_page()
                      if font_list is not None:
                          ctx.add_init_script(
                              'if (typeof window.setFontList === "function") '
                              'window.setFontList(%s);' % json.dumps(",".join(font_list)))
                      page.goto("http://127.0.0.1:%d/" % n7_port)
                      out = page.evaluate(JS_N7)
                      b.close()
                      return out

              n7 = n7_run(FONTS["mac"])
              _srv.shutdown()
              print(f"  [arm n7 / #91] control face status={n7['ctlStatus']} "
                    f"width={n7['ctlWidth']} baseline={n7['baseline']}; "
                    f"404 face status={n7['badStatus']}")

              n7_failures = []
              if n7["ctlStatus"] == "NO_FACE_FOUND" or n7["badStatus"] == "NO_FACE_FOUND":
                  n7_failures.append(
                      f"setup invalid: document.fonts did not carry both @font-face "
                      f"rules (ctl={n7['ctlStatus']} bad={n7['badStatus']})")
              elif n7["ctlStatus"] != "loaded":
                  n7_failures.append(
                      f"control invalid: the REAL control font reported "
                      f"{n7['ctlStatus']!r}, so 'error' here says nothing about the 404 "
                      f"face -- the server, the origin or the face itself is at fault")
              elif abs(n7["ctlWidth"] - 1920.0) > 1.0:
                  n7_failures.append(
                      f"control invalid: the control face reports `loaded` but measured "
                      f"{n7['ctlWidth']} instead of 1920 (baseline {n7['baseline']}), so "
                      f"`loaded` is being reported for a face that did not render")
              elif n7["badStatus"] != "error":
                  n7_failures.append(
                      f"INVENTED LOAD STATUS: a face whose src url() 404s reports "
                      f"{n7['badStatus']!r}, not 'error', while the control face on the "
                      f"same page loaded and rendered at 1920")
              if n7_failures:
                  tripwires.append(f"(n7) FontFace load status for non-local faces (#91): {n7_failures}")
                  note_unmeasured("(n7)", n7_failures, "INVENTED LOAD STATUS")
          # -----------------------------------------------------------
```

- [ ] **Step 8: Write the Phase 0 `EXPECTED_RED` entries**

The six new arms are all expected RED on `34432908522`. Replace `EXPECTED_RED = {}`
(`.github/workflows/smoke.yml:4267`) with:

```python
          # Phase 0 of fonts round 3. Every entry here is a defect this branch
          # is about to fix or measure, so each is expected RED on the
          # pre-fix binaries and each is REMOVED in Task 7 once its fix lands.
          # Listed only so a RED does not fail the step and skip the four steps
          # that follow it (record_video, Integration suite, Detector-site
          # smoke, Upload results).
          EXPECTED_RED = {
              "(n1)": "#94, the pref-font memo is process-global and ungated at read; "
                      "unfixed until Task 3",
              "(n2)": "#92, a generic under a per-context list resolves by fontconfig "
                      "distance, not by the generic; unfixed until Task 4",
              "(h3)": "#88, GetDefaultFont's last-resort walk is ungated and unscoped; "
                      "unfixed until Task 4",
              "(n4)": "#82, the U+FFFD cache measurement; RED here means the #93 gate "
                      "does not hold, GREEN means it does and the RED control is B6",
              "(n5)": "#90, per-context speech voices -- MEASUREMENT, not a triaged "
                      "defect. A RED is the reading Task 6 branches on",
              "(n7)": "#91, FontFaceLoadStatus is invented rather than read for "
                      "non-local faces; unfixed until Task 5",
          }
```

The key match uses `t.startswith(k)`, and no existing tag is a prefix of any of these,
so none collide. `(h3)` and `(h)` do not collide either: `"(h3) …".startswith("(h)")` is
false.

- [ ] **Step 9: Syntax-check, count, commit**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
python3 .superpowers/sdd-fonts2/check_smoke_python.py .github/workflows/smoke.yml \
  "$TMPDIR/smoke-py-t2"
uv run --with pyyaml python -c "import yaml; yaml.safe_load(open('.github/workflows/smoke.yml')); print('YAML OK')"
grep -c 'tripwires.append' .github/workflows/smoke.yml
grep -n 'def one_page_list_arg\|def n5_two_contexts\|def n7_run\|efgh_mark = log_mark' .github/workflows/smoke.yml
git diff --stat .github/workflows/smoke.yml
```
Expected: every block `OK`, `0 failed`; `YAML OK`; the `tripwires.append` count rises by
six from whatever Task 1 left it at — **record the before and after numbers, do not
recall them**; each of the four definitions present exactly once.

```bash
git add .github/workflows/smoke.yml
git commit -m "measure(#94 #92 #88 #82 #90 #91): six RED-first smoke arms

Phase 0 run 2 of fonts round 3. Workflow only -- no patch, no rebuild.

(n1) #94. FindFontForChar exit 7 calls WhichPrefFontSupportsChar, which walks
mLangGroupPrefFonts with no gate at all, and that memo is process-global with
neither a context id nor a FontVisibility in its key -- so the first caller to
miss fixes the cell for the process, at context 0, where the gate allows
everything. The arm renders U+1C80 in a ['Geneva'] context. Among bundled
families whose name does not begin with '.', only Tinos and Arimo cover that
codepoint, both lin-only in fonts.json, so a match against Tinos's width is
attributable to the pref path and not to an in-list fallback.

(n2) #92. FcFontSort runs with trim=FcFalse, so the generic loop returns three
families chosen by fontconfig distance from a pattern the gate already emptied
of its real answer. The arm scores monospace as equal-width on 'iiiii' and
'mmmmm', with sans-serif on the same strings as the control -- without that
control, 'equal' is also what 'nothing rendered' looks like.

(h3) #88. Its own tag, not an extension of (h), so a RED-today predicate cannot
turn a green arm red. The verdict is the log: the `default ctx=N family=X` line
following the mac context's `facename key=segoe ui allowed=0` must name a
family that context's list contains. The width half is a discriminator only --
262 of 513 mac families tie at the target width -- and the arm says so when it
discriminates nothing. ctx is read off the facename line, never hardcoded.

(n4) #82. Donor ['Times','Menlo'], victim ['Times','Geneva'], both stacks
'Times'. Times has no U+FFFD in any of its four faces and the appended default
generic is serif, whose first table entry is Times, so both groups resolve to
times,times and the only carrier the donor can reach is Menlo through system
fallback. Same process asserted, not assumed; both pages same-scheme so both
groups sit at the same FontVisibility level, which is what
mReplacementCharFallbackFamily is indexed by.

(n5) #90 is a measurement, not a fix. Voices are read after goto AND after
voiceschanged, page-world values come back through a DOM attribute because
init scripts run in the isolated world, and add_init_script runs after
new_page() so the one-shot setter is not spent on about:blank.

(n7) #91 starts an http.server on 127.0.0.1 and navigates to it. Every other
navigation in this file is a data: URL, an opaque origin from which an absolute
http:// font url() is a CORS-blocked cross-origin fetch -- both faces would
read 'error' for a reason that has nothing to do with #91. The control face is
arm (k)'s run-time fontTools font, which measures exactly 1920 if and only if
it rendered.

Every arm has three states, not two: a binary that emits none of the log kinds
an arm reads scores width-only and appends nothing, rather than reporting
SETUP-INVALID for a precondition that build was never going to satisfy.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push origin fix/fonts-round3
```

- [ ] **Step 10: Dispatch Phase 0 run 2 on `34432908522`, and a second run on `34236331658`**

```bash
gh workflow run smoke.yml -R lang315/camoufox --ref fix/fonts-round3 -f run_id=34432908522
sleep 20
gh run list -R lang315/camoufox --workflow=smoke.yml --limit 3 \
  --json databaseId,headSha,status,createdAt \
  --jq '.[] | "\(.databaseId) \(.status) \(.headSha[0:7]) \(.createdAt)"'
```
Record the newest id as `P0R2`. Wait with `Monitor` as in Task 1 Step 7. Then:

```bash
gh workflow run smoke.yml -R lang315/camoufox --ref fix/fonts-round3 -f run_id=34236331658
sleep 20
gh run list -R lang315/camoufox --workflow=smoke.yml --limit 3 \
  --json databaseId,status,createdAt --jq '.[] | "\(.databaseId) \(.status) \(.createdAt)"'
```
Record as `P0R2_84`.

**`P0R2_84` will end `completed failure`, and that is expected.** `34236331658` is the
pre-#93 PR #84 artifact, and `EXPECTED_GREEN` on this branch lists `(b2)`, `(b2r)`,
`(i)`, `(i2)` and `(k)` — every one of which is RED on that binary. Read `(n1)` and
`(n4)` out of the log anyway; **do not** edit `EXPECTED_GREEN` to make that run pass.
The only reason it is dispatched is B1's and B4's width-only reading on a binary with
zero `CAMOU-FL` lines.

- [ ] **Step 11: Read the arms and write the B5 gate**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
for id in <P0R2> <P0R2_84>; do
  gh run view "$id" -R lang315/camoufox --log > .superpowers/sdd-fonts3/smoke-p0r2-"$id".log
  grep -v '36;1m' .superpowers/sdd-fonts3/smoke-p0r2-"$id".log \
    | grep -E '\[arm (n1|n2|h3|n4|n5|n7) |tripwire triage|SETUP-INVALID|UNEXPECTED RED|RED \(expected\)|KNOWN UNMEASURABLE' \
    | sed -E 's/^[^Z]*Z//' | cut -c1-260 \
    | tee .superpowers/sdd-fonts3/smoke-p0r2-arms-"$id".txt
done
```

Expected on `<P0R2>` (build `34432908522`, patches identical to `main`):

| Arm | Expected | What a different reading means |
|---|---|---|
| `(n1)` | RED, `PREF PATH LEAK (width-only, no \`fontlist\` kind in this binary)` — this **is** #94's Phase 0 RED, and Task 9 quotes this line | a `DIAGNOSTIC` line instead means the probe matched neither Tinos nor the tofu floor: some third face answered, and #94 has no RED until the fixture is re-derived |
| `(n2)` | RED, `GENERIC MISMAPPED` — no `generic-map` kind, so the log half is unavailable and the width check plus its `sans-serif` control carry the verdict | GREEN means #92 does not reproduce under `FONTCONFIG_FILE`; stop and report |
| `(h3)` | RED, `DEFAULT FONT OUTSIDE THE LIST` (shape A cannot be GREEN here: `monospace` → Cousine and `serif` → Tinos are both refused, so `mFonts` is empty and the `default` line fires) | `DIAGNOSTIC` means the `facename` kind is missing, which contradicts `163ee25`; re-read the counter table |
| `(n4)` | GREEN or `DIAGNOSTIC` — #93's gate is in this binary | RED means #93's gate does not hold and that is a finding of its own |
| `(n5)` | either; **this is the gate** | `setup invalid` means the binding name or the init-script ordering is wrong — fix the arm, re-dispatch |
| `(n7)` | RED, `INVENTED LOAD STATUS` | `control invalid` means the HTTP server or the control font is at fault, not #91 |

Every RED in that table is in `EXPECTED_RED` (Step 8), so the run's own triage prints
`RED (expected)` for each and the step does not fail on them.

Expected on `<P0R2_84>` (build `34236331658`, zero `CAMOU-FL` lines): `(n1)` scores
width-only exactly as above, and `(n4)` prints its `DIAGNOSTIC` line — `(n4)`'s width
evidence cannot stand alone, since its whole verdict is about which cached family
answered, so it appends nothing here. That `(n4)` line is the B6 trigger; record verbatim
whether the donor reached Menlo.

Write the gate file. It must contain exactly one of the two verdict lines, because
Task 6 branches on that string and nothing else:

```bash
cat > .superpowers/sdd-fonts3/gate-b5.md <<'EOF'
# Phase 0 gate — #90 (arm n5)

Run: <P0R2> (smoke.yml @ <workflow sha>, linux binary from build 34432908522 @ 163ee25)

GATE: B5 RED
# ^ exactly one of: "GATE: B5 RED" | "GATE: B5 GREEN"

## Lines this was read from
<paste every `[arm n5 / #90]` line verbatim from smoke-p0r2-arms-<P0R2>.txt>

## Reading rule applied
(n5) RED with a `VOICES LEAK` string  -> GATE: B5 RED   -> Task 6 runs.
(n5) GREEN                            -> GATE: B5 GREEN -> Task 6 is SKIPPED and
                                          #90 closes on the measurement alone.
(n5) RED with `setup invalid`         -> NEITHER. The arm measured nothing. Fix
                                          the arm and re-dispatch Step 9.
EOF

cat > .superpowers/sdd-fonts3/gate-b4-phase0.md <<'EOF'
# Phase 0 reading — #82 (arm n4) on the pre-#93 artifact

Run: <P0R2_84> (linux binary from build 34236331658 @ 8990915; zero CAMOU-FL lines)

B6 TRIGGER: <YES|NO>
# YES when the DIAGNOSTIC line says the donor did NOT reach Menlo, i.e. something
# answered U+FFFD before SystemFindFontForChar and the cache was never populated.
# Task 7's B6 branch runs only on YES.

## Lines this was read from
<paste the `[arm n4 / #82]` DIAGNOSTIC line and the donor/victim widths verbatim>

## Candidate set the widths were matched against
Bundle U+FFFD carriers (recon section 5): mac Menlo, Lucida Grande;
win Segoe UI, Tahoma, Verdana; lin Arimo, Tinos, STIX Two Math.
<record any two of those whose widths collide -- a collision means the match
identifies a SET, not a face>
EOF
```

Append to the ledger: `P0R2=<id>`, `P0R2_84=<id>`, each conclusion, the gate line, and
the B6 trigger.

---

### Task 3: A1 (#94) — the pref-font path (`patches/font-list-spoofing.patch`)

Populate the process-global pref-font memo unfiltered at context 0, and ask both gates
at every read. Plus the `fontlist` diagnostic that lets three arms read their
preconditions instead of assuming them.

**Task 3 must be committed before Task 4 starts.** Both edit the same patch file.

**Files:**
- Modify: `patches/font-list-spoofing.patch`
- Modify (transiently, never committed):
  `camoufox-152.0.4-beta.31/gfx/thebes/gfxPlatformFontList.{h,cpp}`,
  `camoufox-152.0.4-beta.31/gfx/thebes/gfxTextRun.cpp`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  ```cpp
  // gfx/thebes/gfxPlatformFontList.h, public section
  static bool CamouIsFamilyAllowed(
      FontVisibilityProvider* aFontVisibilityProvider,
      const nsACString& aFamilyName, nsACString* aLowerKeyOut = nullptr);
  ```
  Task 4 calls it by that exact name from `CamouGenericCandidate`, from
  `GetDefaultFontLocked` and from `gfxFontGroup::GetDefaultFont`'s walk.

  **Deviation from the spec, stated rather than absorbed.** §A2 gives the signature as
  two arguments. `gfxPlatformFontList::GenerateFontListKey` is **protected** (verified:
  the last top-level access specifier before its declaration at
  `gfxPlatformFontList.h:1002` is `protected:` at `:777`), so `gfxTextRun.cpp` cannot
  lowercase a key the way the in-class call sites do. Rather than add an
  `nsUnicharUtils.h` include to `gfxTextRun.cpp`, the accessor lowercases a copy
  internally — idempotent for the `fffd-cache` site, which already passes a lowercased
  key — and hands the lowercased key back through an optional third parameter so every
  `CAMOU-FL` line prints the same string. The spec's two-argument calls compile
  unchanged.

- [ ] **Step 1: Build the workspace**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
git status --short
make revert
git -C camoufox-152.0.4-beta.31 clean -fdq
python3 .superpowers/sdd-44/apply_upto.py 2>&1 | tail -25
```
`.superpowers/sdd-44/apply_upto.py` already hardcodes `TARGET = "font-list-spoofing.patch"`
(line 19) — use it unchanged. Expected: `OK: all N pre-target patches applied clean`,
then the target's own apply output, then `=== .rej files left: []`. A clean
`git status --short` at the repo root before starting; if `patches/` is dirty, stop.

Confirm the checkpoint and the anchors:
```bash
cd camoufox-152.0.4-beta.31
git tag --points-at HEAD
grep -n 'static bool MaskedFontListBlocks(' gfx/thebes/gfxPlatformFontList.h
grep -n 'static bool CamouIsFontAllowed(const nsACString& aLowerKey) {' gfx/thebes/gfxPlatformFontList.cpp
grep -n 'gfxPlatformFontList::GetPrefFontsLangGroupLocked(' gfx/thebes/gfxPlatformFontList.cpp
grep -n 'void gfxPlatformFontList::AddGenericFonts(' gfx/thebes/gfxPlatformFontList.cpp
grep -n 'gfxFontGroup::WhichPrefFontSupportsChar(' gfx/thebes/gfxTextRun.cpp
grep -n 'mFontListGeneration = pfl->GetGeneration();' gfx/thebes/gfxTextRun.cpp
cd ..
```
Expected: `first-checkpoint`; `gfxPlatformFontList.h:664`; `gfxPlatformFontList.cpp:1248`;
`:2639`; `:2666`; `gfxTextRun.cpp:3924`; `gfxTextRun.cpp:2029`. If a line number differs,
use the one the grep prints — the anchors below are text, not numbers.

- [ ] **Step 2: Declare the public gate accessor**

In `camoufox-152.0.4-beta.31/gfx/thebes/gfxPlatformFontList.h`, immediately after the
closing `const nsACString& aLowercaseFamily);` of `MaskedFontListBlocks` (`:666`) and
before the blank line preceding `static void FontWhitelistPrefChanged(`, insert:

```cpp

  // Camoufox (#94/#92/#88): the two-gate, fail-closed family test every read
  // filter this round adds asks. Identical in meaning to the one the U+FFFD
  // cache read already performs inline (gfxPlatformFontList.cpp:1415-1417):
  // an empty key refuses, the launch-level "fonts" mask refuses, then the
  // per-context list refuses. The launch half is not optional -- the memos
  // these filters sit in front of carry no FontVisibility and no provider in
  // their key, so a chrome caller (for which MaskedFontListAppliesTo is false)
  // can populate a cell first and store host families the mask would refuse.
  //
  // Takes a RAW family name and lowercases a copy, which is idempotent for the
  // call sites that already hold a key: gfxTextRun.cpp cannot reach the
  // protected GenerateFontListKey. aLowerKeyOut, when non-null, receives that
  // lowercased key so a caller's CAMOU-FL line prints the same string every
  // other CAMOU-FL line prints.
  //
  // Inherits the context-0 fail-open (CLAUDE.md lesson 5), unchanged.
  static bool CamouIsFamilyAllowed(
      FontVisibilityProvider* aFontVisibilityProvider,
      const nsACString& aFamilyName, nsACString* aLowerKeyOut = nullptr);
```

- [ ] **Step 3: Define it, next to the file-static it wraps**

In `camoufox-152.0.4-beta.31/gfx/thebes/gfxPlatformFontList.cpp`, immediately after the
closing brace of `static bool CamouIsFontAllowed(...)` (the line
`  return allowed;` then `}` at `:1265`), and before
`void gfxPlatformFontList::GetFontList(nsAtom* aLangGroup,`, insert:

```cpp

/* static */
bool gfxPlatformFontList::CamouIsFamilyAllowed(
    FontVisibilityProvider* aFontVisibilityProvider,
    const nsACString& aFamilyName, nsACString* aLowerKeyOut) {
  nsAutoCString key(aFamilyName);
  ToLowerCase(key);
  if (aLowerKeyOut) {
    *aLowerKeyOut = key;
  }
  // Fail closed on an empty key for the same reason the fffd-cache read does:
  // fontlist::String::AsString can return an empty string in a child process
  // even for a real family (SharedFontList.h:142-148), and an empty key can
  // never match a list entry, so the safe answer is to refuse.
  if (key.IsEmpty()) {
    return false;
  }
  return !MaskedFontListBlocks(aFontVisibilityProvider, key) &&
         CamouIsFontAllowed(key);
}
```

`ToLowerCase(nsACString&)` is already used in this file by `GenerateFontListKey`
(`:893-901`), so no include change. `CamouIsFontAllowed` is the file-static declared at
`:1083` and defined at `:1248`; it stays private, and every gate this round adds asks
both gates through the accessor.

- [ ] **Step 4: Populate the pref-font memo at context 0**

In `camoufox-152.0.4-beta.31/gfx/thebes/gfxPlatformFontList.cpp`, replace
`GetPrefFontsLangGroupLocked`'s body (`:2639-2663`):

```cpp
gfxPlatformFontList::PrefFontList*
gfxPlatformFontList::GetPrefFontsLangGroupLocked(
    FontVisibilityProvider* aFontVisibilityProvider,
    StyleGenericFontFamily aGenericType, eFontPrefLang aPrefLang) {
  if (aGenericType == StyleGenericFontFamily::MozEmoji ||
      aPrefLang == eFontPrefLang_Emoji) {
    // Emoji font has no lang
    PrefFontList* prefFonts = mEmojiPrefFont.get();
    if (MOZ_UNLIKELY(!prefFonts)) {
      prefFonts = new PrefFontList;
      ResolveEmojiFontNames(aFontVisibilityProvider, prefFonts);
      mEmojiPrefFont.reset(prefFonts);
    }
    return prefFonts;
  }

  auto index = static_cast<size_t>(aGenericType);
  PrefFontList* prefFonts = mLangGroupPrefFonts[aPrefLang][index].get();
  if (MOZ_UNLIKELY(!prefFonts)) {
    prefFonts = new PrefFontList;
    ResolveGenericFontNames(aFontVisibilityProvider, aGenericType, aPrefLang,
                            prefFonts);
    mLangGroupPrefFonts[aPrefLang][index].reset(prefFonts);
  }
  return prefFonts;
}
```
with:
```cpp
gfxPlatformFontList::PrefFontList*
gfxPlatformFontList::GetPrefFontsLangGroupLocked(
    FontVisibilityProvider* aFontVisibilityProvider,
    StyleGenericFontFamily aGenericType, eFontPrefLang aPrefLang) {
  // Camoufox (#94): both memos below are process-global singletons.
  // mLangGroupPrefFonts is keyed [eFontPrefLang][StyleGenericFontFamily] and
  // mEmojiPrefFont is not keyed at all (gfxPlatformFontList.h:1143-1144) --
  // neither carries a user context id or a FontVisibility. So the FIRST caller
  // to miss fixes the cell for the whole process, and whichever context that
  // caller happened to be in decides what every later context reads.
  //
  // The fix is a split: populate the cell UNFILTERED, at context 0, so its
  // contents do not depend on who missed first; then ask both gates at every
  // READ (WhichPrefFontSupportsChar in gfxTextRun.cpp, and AddGenericFonts
  // below). Forcing context 0 here cannot weaken the launch-level mask:
  // MaskedFontListAppliesTo (:904-915) asks MaskConfig::HasFontAllowlist() and
  // the provider, never the thread-local context.
  if (aGenericType == StyleGenericFontFamily::MozEmoji ||
      aPrefLang == eFontPrefLang_Emoji) {
    // Emoji font has no lang
    PrefFontList* prefFonts = mEmojiPrefFont.get();
    if (MOZ_UNLIKELY(!prefFonts)) {
      prefFonts = new PrefFontList;
      mozilla::dom::AutoFontListContext camouUnfiltered(0);
      ResolveEmojiFontNames(aFontVisibilityProvider, prefFonts);
      mEmojiPrefFont.reset(prefFonts);
    }
    return prefFonts;
  }

  auto index = static_cast<size_t>(aGenericType);
  PrefFontList* prefFonts = mLangGroupPrefFonts[aPrefLang][index].get();
  if (MOZ_UNLIKELY(!prefFonts)) {
    prefFonts = new PrefFontList;
    mozilla::dom::AutoFontListContext camouUnfiltered(0);
    ResolveGenericFontNames(aFontVisibilityProvider, aGenericType, aPrefLang,
                            prefFonts);
    mLangGroupPrefFonts[aPrefLang][index].reset(prefFonts);
  }
  return prefFonts;
}
```

`AutoFontListContext` is stack RAII that restores the previous id in its destructor
(`dom/base/FontListManager.h:29-40`), and both guards are declared inside the
`if (MOZ_UNLIKELY(!prefFonts))` block, so each closes before the function returns.
`mozilla/dom/FontListManager.h` is already included in this file — `CamouIsFontAllowed`
uses it.

- [ ] **Step 5: Read-filter the memo in `AddGenericFonts`**

In the same file, replace the tail of `gfxPlatformFontList::AddGenericFonts` (`:2691-2697`):

```cpp
  if (!prefFonts->IsEmpty()) {
    aFamilyList.SetCapacity(aFamilyList.Length() + prefFonts->Length());
    for (auto& f : *prefFonts) {
      aFamilyList.AppendElement(FamilyAndGeneric(f, aGenericType));
    }
  }
}
```
with:
```cpp
  if (!prefFonts->IsEmpty()) {
    aFamilyList.SetCapacity(aFamilyList.Length() + prefFonts->Length());
    for (auto& f : *prefFonts) {
      // Camoufox (#94): the read filter. The cell was populated unfiltered at
      // context 0 (GetPrefFontsLangGroupLocked above), so both gates are asked
      // here instead. The thread-local context is the one EnsureFontList
      // already opened (gfxTextRun.cpp:1956), and aFontVisibilityProvider is
      // this call's own parameter, so nothing needs plumbing.
      nsAutoCString camouRaw, camouKey;
      if (f.mShared) {
        camouRaw = f.mShared->Key().AsString(SharedFontList());
      } else if (f.mUnshared) {
        camouRaw = f.mUnshared->Name();
      }
      const bool camouAllowed =
          CamouIsFamilyAllowed(aFontVisibilityProvider, camouRaw, &camouKey);
      LOG_FONTLIST(("CAMOU-FL pref-fallback ctx=%u key=%s allowed=%d",
                    mozilla::dom::FontListManager::GetCurrentContext(),
                    camouKey.get(), camouAllowed ? 1 : 0));
      if (!camouAllowed) {
        continue;
      }
      aFamilyList.AppendElement(FamilyAndGeneric(f, aGenericType));
    }
  }
}
```

- [ ] **Step 6: Read-filter the memo in `WhichPrefFontSupportsChar`, under the group's own context**

In `camoufox-152.0.4-beta.31/gfx/thebes/gfxTextRun.cpp`, insert at the very top of
`gfxFontGroup::WhichPrefFontSupportsChar` (`:3924`), immediately after the opening brace
and before `eFontPrefLang charLang;`:

```cpp
  // Camoufox (#94): FindFontForChar reaches this function with NO
  // AutoFontListContext open. gfxTextRun.cpp has exactly three scopes --
  // EnsureFontList (:1956), GetFirstValidFont (:2327) and
  // WhichSystemFontSupportsChar (:4036) -- and all three are RAII-closed before
  // FindFontForChar's own body runs. Without this the read filter below would
  // ask the gate at context 0, where it allows everything, and the filter would
  // be a no-op in exactly the case it exists for. mUserContextId is this font
  // group's own cached id (ctor, :1864-1908), not the thread-local, so this
  // does not depend on any caller leaving a scope open.
  mozilla::dom::AutoFontListContext autoFontListCtx(mUserContextId);

```

Then, inside the `for (j = 0; j < numPrefs; j++)` loop, replace:
```cpp
      // look up the appropriate face
      FontFamily family = (*families)[j];
      if (family.IsNull()) {
        continue;
      }
```
with:
```cpp
      // look up the appropriate face
      FontFamily family = (*families)[j];
      if (family.IsNull()) {
        continue;
      }

      // Camoufox (#94): the read filter. mLangGroupPrefFonts / mEmojiPrefFont
      // are process-global with no context id and no FontVisibility in the key,
      // and this loop had no gate of any kind -- not CamouIsFontAllowed, not
      // MaskedFontListBlocks, not even IsVisibleToCSS. It is the only silent,
      // ungated producer on FindFontForChar's path: a hit here returns at
      // :3591 before WhichSystemFontSupportsChar can log anything at all.
      {
        nsAutoCString camouRaw, camouKey;
        if (family.mShared) {
          camouRaw = family.mShared->Key().AsString(pfl->SharedFontList());
        } else if (family.mUnshared) {
          camouRaw = family.mUnshared->Name();
        }
        const bool camouAllowed = gfxPlatformFontList::CamouIsFamilyAllowed(
            mFontVisibilityProvider, camouRaw, &camouKey);
        CAMOU_LOG_FONTLIST(("CAMOU-FL pref-fallback ctx=%u key=%s allowed=%d",
                            mUserContextId, camouKey.get(),
                            camouAllowed ? 1 : 0));
        if (!camouAllowed) {
          continue;
        }
      }
```

The `mLastPrefFamily` fast path three lines below is left as it is: it can only return
a family this same loop admitted on an earlier call, in this same font group, under
this same `mUserContextId`.

- [ ] **Step 7: Add the `fontlist` diagnostic to `EnsureFontList`**

In the same file, replace the tail of `gfxFontGroup::EnsureFontList` (`:2020-2031`):

```cpp
  // build the fontlist from the specified families
  for (const auto& f : fonts) {
    if (f.mFamily.mShared) {
      AddFamilyToFontList(f.mFamily.mShared, f.mGeneric);
    } else {
      AddFamilyToFontList(f.mFamily.mUnshared, f.mGeneric);
    }
  }

  mFontListGeneration = pfl->GetGeneration();
  mResolvedFonts = true;
}
```
with:
```cpp
  // build the fontlist from the specified families
  for (const auto& f : fonts) {
    if (f.mFamily.mShared) {
      AddFamilyToFontList(f.mFamily.mShared, f.mGeneric);
    } else {
      AddFamilyToFontList(f.mFamily.mUnshared, f.mGeneric);
    }
  }

  // Camoufox (#94) diagnostic: names the family list this group actually
  // resolved. Three smoke arms (#94, #92, #82) score their preconditions
  // against this line instead of inferring them from the fixture -- "the
  // appended generic maps to X", "the donor reaches SystemFindFontForChar",
  // "the codepoint's only carriers are outside the list" were each an
  // inference before it existed, and one of them was wrong.
  //
  // An EMPTY name in the families= field is a child-process read failure of
  // fontlist::String::AsString (SharedFontList.h:142-148), NOT an empty list;
  // the guard treats it as unmeasured, never as a verdict. Everything is built
  // inside the enabled test so the allocation costs nothing with the module
  // off, exactly like the URI copy at :1903.
  if (MOZ_UNLIKELY(CAMOU_LOG_FONTLIST_ENABLED())) {
    nsAutoCString camouFamilies;
    for (const auto& f : fonts) {
      nsAutoCString camouKey;
      if (f.mFamily.mShared) {
        camouKey = f.mFamily.mShared->Key().AsString(pfl->SharedFontList());
      } else if (f.mFamily.mUnshared) {
        camouKey = f.mFamily.mUnshared->Name();
      }
      // CamouIsFamilyAllowed's third parameter is the only lowercasing route
      // available here: GenerateFontListKey is protected. The verdict is
      // discarded; only the key is wanted.
      nsAutoCString camouLower;
      (void)gfxPlatformFontList::CamouIsFamilyAllowed(mFontVisibilityProvider,
                                                      camouKey, &camouLower);
      if (!camouFamilies.IsEmpty()) {
        camouFamilies.Append(',');
      }
      camouFamilies.Append(camouLower);
    }
    CAMOU_LOG_FONTLIST(("CAMOU-FL fontlist ctx=%u n=%u families=%s",
                        mUserContextId, uint32_t(fonts.Length()),
                        camouFamilies.get()));
  }

  mFontListGeneration = pfl->GetGeneration();
  mResolvedFonts = true;
}
```

- [ ] **Step 8: Regenerate the patch, guarding the section list**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox/camoufox-152.0.4-beta.31
git add -A
git reset -q _READY || true
git diff --cached first-checkpoint > ../.superpowers/sdd-fonts3/fls-t3.patch
cd ..
diff <(grep '^diff --git' patches/font-list-spoofing.patch) \
     <(grep '^diff --git' .superpowers/sdd-fonts3/fls-t3.patch)
for sec in dom/base/FontListManager.cpp dom/base/FontListManager.h dom/base/moz.build \
           dom/base/nsGlobalWindowInner.cpp dom/base/nsGlobalWindowInner.h \
           dom/webidl/Window.webidl gfx/thebes/gfxFcPlatformFontList.cpp \
           gfx/thebes/gfxFcPlatformFontList.h layout/style/FontFaceSet.cpp; do
  echo "--- $sec"
  diff <(awk -v s="diff --git a/$sec" '$0==s{f=1} f&&/^diff --git/&&$0!=s{exit} f' patches/font-list-spoofing.patch) \
       <(awk -v s="diff --git a/$sec" '$0==s{f=1} f&&/^diff --git/&&$0!=s{exit} f' .superpowers/sdd-fonts3/fls-t3.patch)
done
```
Expected: the section lists are identical (this task adds no file to the patch), and no
output from any of the nine per-section diffs — only `gfx/thebes/gfxPlatformFontList.cpp`,
`gfx/thebes/gfxPlatformFontList.h` and `gfx/thebes/gfxTextRun.cpp` may change. If a
section appears or disappears, stop.

`patches/font-list-spoofing.patch` starts at `diff --git` on line 1 and its sections are
already path-sorted, so it takes the regenerated file wholesale:
```bash
cp .superpowers/sdd-fonts3/fls-t3.patch patches/font-list-spoofing.patch
grep -c '^@@' patches/font-list-spoofing.patch
```
Record the hunk count; it is quoted in Step 10's commit message and must be read back.

- [ ] **Step 9: Dry-run the full stack with the applier the build uses**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
make revert
git -C camoufox-152.0.4-beta.31 clean -fdq
CAMOU_PATCH=/opt/homebrew/bin/gpatch make dir 2>&1 \
  | tee .superpowers/sdd-fonts3/make-dir-t3.log | tail -20
grep -c 'FAILED' .superpowers/sdd-fonts3/make-dir-t3.log
grep -niE 'fuzz|offset' .superpowers/sdd-fonts3/make-dir-t3.log
```
Expected: `0` FAILED. The fuzz/offset grep may print offsets for
`window-setter-seal.patch` and `system-ui-font-spoofing.patch`, which sort after
`font-list-spoofing.patch` and whose anchors move when it grows — those are accepted and
go in the PR body. **Any** fuzz or offset on `gfxPlatformFontList.cpp`,
`gfxPlatformFontList.h`, `gfxTextRun.cpp` or `gfxFcPlatformFontList.cpp` is a stop.

The `git clean -fdq` after `make revert` is not optional:
`font-list-spoofing.patch` **creates** `dom/base/FontListManager.{h,cpp}`, and a bare
reset leaves them behind as untracked. The creation hunks then land on existing files
and `--forward` makes GNU patch skip them without a word.

`0 FAILED` is not a placement proof. Read the applied tree:
```bash
cd camoufox-152.0.4-beta.31
grep -n 'CamouIsFamilyAllowed' gfx/thebes/gfxPlatformFontList.h gfx/thebes/gfxPlatformFontList.cpp gfx/thebes/gfxTextRun.cpp
grep -n 'camouUnfiltered' gfx/thebes/gfxPlatformFontList.cpp
grep -n 'CAMOU-FL pref-fallback\|CAMOU-FL fontlist' gfx/thebes/gfxPlatformFontList.cpp gfx/thebes/gfxTextRun.cpp
sed -n '/gfxFontGroup::WhichPrefFontSupportsChar/,/eFontPrefLang charLang/p' gfx/thebes/gfxTextRun.cpp | tail -4
cd ..
```
Expected: one declaration in the header, one definition plus one call in
`gfxPlatformFontList.cpp`, two calls in `gfxTextRun.cpp` (the pref filter and the
`fontlist` lowercaser); two `camouUnfiltered` guards; one `pref-fallback` line in each
`.cpp` and one `fontlist` line; and `AutoFontListContext autoFontListCtx(mUserContextId);`
as the first statement of `WhichPrefFontSupportsChar`.

- [ ] **Step 10: Commit**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
git add patches/font-list-spoofing.patch
git commit -m "fix(#94): populate the pref-font memo unfiltered, gate it at read

gfxFontGroup::FindFontForChar's step 2 calls WhichPrefFontSupportsChar
(gfx/thebes/gfxTextRun.cpp:3924-4028), which walked mLangGroupPrefFonts with no
gate of any kind -- not CamouIsFontAllowed, not MaskedFontListBlocks, not even
IsVisibleToCSS. It is the only silent, ungated producer on that path: a hit
returns before WhichSystemFontSupportsChar runs, so neither a fffd-cache line
nor a global-fallback line is ever emitted and the leak is invisible in the log.

Both memos behind it are process-global singletons. mLangGroupPrefFonts is
keyed [eFontPrefLang][StyleGenericFontFamily] and mEmojiPrefFont is not keyed at
all, so neither carries a user context id or a FontVisibility -- the first
caller to miss fixes the cell for the whole process, and no scope is open when
FindFontForChar reaches it, so that caller is at context 0 where the gate allows
everything.

The fix is a split, because no other shape survives a memo whose key cannot
carry the question. GetPrefFontsLangGroupLocked now populates under
AutoFontListContext(0), so a cell's contents no longer depend on who missed
first; both consumers -- WhichPrefFontSupportsChar and
gfxPlatformFontList::AddGenericFonts -- ask both gates at read. Forcing context
0 during population cannot weaken the launch-level mask: MaskedFontListAppliesTo
asks MaskConfig::HasFontAllowlist() and the provider, never the thread-local
context.

The read filter asks BOTH gates, not just the per-context list. The memo carries
no FontVisibility and no provider in its key, and MaskedFontListAppliesTo
returns false for a chrome document, so a chrome font group populating a cell
first would otherwise store host families the launch mask refuses and content
would read them back through a filter that never asks the launch question. Empty
keys fail closed for the same reason the U+FFFD cache read does.

gfxPlatformFontList::CamouIsFamilyAllowed is the accessor that makes this
callable from gfxTextRun.cpp: CamouIsFontAllowed is a file-static and
GenerateFontListKey is protected, so the accessor lowercases a copy itself and
hands the key back for the log line.

CAMOU-FL fontlist names the family list EnsureFontList actually resolved. Three
smoke arms scored preconditions by inference before it existed, and one of those
inferences was wrong; they now read it. An empty families= field is a
child-process AsString failure, not an empty list, and the guard treats it as
unmeasured.

Context 0 still fails open (CLAUDE.md lesson 5); unchanged and stated in the PR.

Verified: CAMOU_PATCH=gpatch make dir, 0 FAILED, no fuzz or offset on any
gfx/thebes file; <N> hunks in the regenerated patch; the applied tree shows the
scope as the first statement of WhichPrefFontSupportsChar and both
AutoFontListContext(0) guards inside GetPrefFontsLangGroupLocked's miss blocks.
Measured by smoke arm (n1), added in the previous commit.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

Append to the ledger: the sha, the hunk count, and the fuzz/offset grep result.

---

### Task 4: A2 (#88 + #92) — default font and generics, one mechanism (`patches/font-list-spoofing.patch`)

One helper, one table, five call sites. **Task 3 must be committed first** — this task's
`first-checkpoint` includes it, and both tasks edit the same patch file.

**Files:**
- Modify: `patches/font-list-spoofing.patch`
- Modify (transiently, never committed):
  `camoufox-152.0.4-beta.31/gfx/thebes/gfxPlatformFontList.{h,cpp}`,
  `camoufox-152.0.4-beta.31/gfx/thebes/gfxFcPlatformFontList.cpp`,
  `camoufox-152.0.4-beta.31/gfx/thebes/gfxTextRun.cpp`

**Interfaces:**
- Consumes: `gfxPlatformFontList::CamouIsFamilyAllowed(FontVisibilityProvider*, const nsACString&, nsACString* = nullptr)`
  from Task 3.
- Produces:
  ```cpp
  // gfx/thebes/gfxPlatformFontList.h, public section
  bool CamouGenericCandidate(FontVisibilityProvider* aFontVisibilityProvider,
                             mozilla::StyleGenericFontFamily aGeneric,
                             nsACString& aKeyOut, nsACString& aStepOut)
      MOZ_REQUIRES(mLock);
  ```
  `aStepOut` is one of `row`, `rows`, `list`; on a `false` return both out-params are
  `""`/`none` and the caller logs `step=none key=none`. No later task consumes it.

- [ ] **Step 1: Build the workspace and confirm Task 3 is in it**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
git status --short
make revert
git -C camoufox-152.0.4-beta.31 clean -fdq
python3 .superpowers/sdd-44/apply_upto.py 2>&1 | tail -25
grep -c 'CamouIsFamilyAllowed' camoufox-152.0.4-beta.31/gfx/thebes/gfxPlatformFontList.cpp
grep -c 'CAMOU-FL fontlist' camoufox-152.0.4-beta.31/gfx/thebes/gfxTextRun.cpp
```
Expected: `OK: all N pre-target patches applied clean`, `=== .rej files left: []`, then
`2` (the definition plus the `AddGenericFonts` call) and `1`. If either is `0`, Task 3
was not committed and this task must not proceed.

- [ ] **Step 2: Declare the helper**

In `camoufox-152.0.4-beta.31/gfx/thebes/gfxPlatformFontList.h`, immediately after the
`CamouIsFamilyAllowed` declaration Task 3 added, insert:

```cpp

  // Camoufox (#92/#88): a per-context generic -> family answer.
  //
  // Returns false -- and the caller keeps upstream behaviour untouched -- when
  // the thread-local context has no list (id 0, or no list installed). With a
  // list, it answers in three steps and says which one answered through
  // aStepOut:
  //   "row"  the ordered row for the generic itself, first key both gates allow
  //   "rows" the OTHER two rows, in QUERY-RELATIVE order, so a proportional
  //          query never lands on a monospaced face while a proportional one is
  //          in the list
  //   "list" SharedFontList()->Families() in index order, first non-hidden
  //          family whose key resolves non-empty and passes both gates
  //
  // The rows are OS-agnostic; the intersection with the context's own list is
  // what makes the answer OS-correct. Both gates are asked at every step
  // through CamouIsFamilyAllowed -- asking only the per-context list would let
  // a masked launch pick a family MaskConfig refuses and then memoize the empty
  // resolution in place of an answer fontconfig would have found.
  //
  // Requires mLock for the shared-list walk. All three call sites hold it:
  // gfxFcPlatformFontList::FindGenericFamilies asserts it,
  // gfxPlatformFontList::AddGenericFonts takes it, and GetDefaultFontLocked is
  // MOZ_REQUIRES(mLock). CamouIsFamilyAllowed takes only sFontListMutex, so the
  // established mLock -> sFontListMutex order (dom/base/FontListManager.cpp:64-72)
  // holds.
  bool CamouGenericCandidate(FontVisibilityProvider* aFontVisibilityProvider,
                             mozilla::StyleGenericFontFamily aGeneric,
                             nsACString& aKeyOut, nsACString& aStepOut)
      MOZ_REQUIRES(mLock);
```

- [ ] **Step 3: Define the rows and the helper**

In `camoufox-152.0.4-beta.31/gfx/thebes/gfxPlatformFontList.cpp`, immediately after the
`CamouIsFamilyAllowed` definition Task 3 added, insert:

```cpp

// Camoufox (#92): the candidate rows. Ordered, OS-agnostic, and deliberately
// spanning all three bundles plus the common host families -- the intersection
// with a context's own list is what makes the answer OS-correct, so a row that
// only named macOS families would answer nothing for a Windows context.
//
// nullptr-TERMINATED, so no array-size facility is needed. `std::size` lives in
// <iterator>, which this file does not include (its only standard include is
// <numeric> at :53), and mozilla::ArrayLength would need <mozilla/ArrayUtils.h>.
// A sentinel costs one pointer per row and adds no include.
static const char* const kCamouMonospaceRow[] = {
    "Menlo",           "Monaco",           "Consolas",
    "Courier New",     "Courier",          "Cousine",
    "Liberation Mono", "DejaVu Sans Mono", "Noto Sans Mono",
    nullptr};
static const char* const kCamouSansSerifRow[] = {
    "Helvetica Neue",  "Helvetica",        "Segoe UI",
    "Arial",           "Arimo",            "Liberation Sans",
    "DejaVu Sans",     "Noto Sans",
    nullptr};
static const char* const kCamouSerifRow[] = {
    "Times",           "Times New Roman",  "Georgia",
    "Tinos",           "Liberation Serif", "DejaVu Serif",
    "Noto Serif",
    nullptr};

bool gfxPlatformFontList::CamouGenericCandidate(
    FontVisibilityProvider* aFontVisibilityProvider,
    StyleGenericFontFamily aGeneric, nsACString& aKeyOut,
    nsACString& aStepOut) {
  aKeyOut.Truncate();
  aStepOut.AssignLiteral("none");

  // A context with no list of its own keeps upstream behaviour exactly. This
  // is the context-0 fail-open (CLAUDE.md lesson 5) and is unchanged here.
  const uint32_t camouCtx = mozilla::dom::FontListManager::GetCurrentContext();
  if (camouCtx == 0 ||
      !mozilla::dom::FontListManager::HasFontList(camouCtx)) {
    return false;
  }

  const char* const* rows[3];
  switch (aGeneric) {
    case StyleGenericFontFamily::Monospace:
      rows[0] = kCamouMonospaceRow;
      rows[1] = kCamouSansSerifRow;
      rows[2] = kCamouSerifRow;
      break;
    case StyleGenericFontFamily::Serif:
      rows[0] = kCamouSerifRow;
      rows[1] = kCamouSansSerifRow;
      rows[2] = kCamouMonospaceRow;
      break;
    default:
      // SansSerif, Cursive, Fantasy, SystemUi, MozEmoji, Math and None all
      // take the sans-serif row first. "-moz-default", which is what
      // gfxFcPlatformFontList::GetDefaultFontForPlatform actually asks for
      // (gfxFcPlatformFontList.cpp:2295-2297), is a literal string and not a
      // StyleGenericFontFamily value at all; its caller maps it to
      // StyleGenericFontFamily::SansSerif before reaching here.
      rows[0] = kCamouSansSerifRow;
      rows[1] = kCamouSerifRow;
      rows[2] = kCamouMonospaceRow;
      break;
  }

  for (size_t r = 0; r < 3; ++r) {
    for (const char* const* p = rows[r]; *p; ++p) {
      nsAutoCString key;
      if (CamouIsFamilyAllowed(aFontVisibilityProvider,
                               nsDependentCString(*p), &key)) {
        aKeyOut = key;
        if (r == 0) {
          aStepOut.AssignLiteral("row");
        } else {
          aStepOut.AssignLiteral("rows");
        }
        return true;
      }
    }
  }

  // Last step: the shared list in index order. Stable within a process, and a
  // child reads the parent's list, so two contexts in one process see the same
  // order. An empty key is a child-process AsString failure
  // (SharedFontList.h:142-148), never an answer, so it is skipped rather than
  // refused-and-counted.
  if (SharedFontList()) {
    fontlist::FontList* list = SharedFontList();
    fontlist::Family* families = list->Families();
    for (uint32_t i = 0, n = list->NumFamilies(); i < n; ++i) {
      if (families[i].IsHidden()) {
        continue;
      }
      nsAutoCString key;
      if (CamouIsFamilyAllowed(aFontVisibilityProvider,
                               families[i].Key().AsString(list), &key)) {
        aKeyOut = key;
        aStepOut.AssignLiteral("list");
        return true;
      }
    }
  }
  return false;
}
```

`nsDependentCString` is available through `nsString.h`, which this file already pulls in
via `gfxPlatformFontList.h`. If the build reports it undeclared, replace
`nsDependentCString(*p)` with `nsAutoCString(*p)` — same semantics, one copy.

- [ ] **Step 4: Take the table step first in `gfxFcPlatformFontList::FindGenericFamilies`**

In `camoufox-152.0.4-beta.31/gfx/thebes/gfxFcPlatformFontList.cpp`, inside the
`WithEntryHandle` lambda, replace:

```cpp
      cacheKey, [&](auto&& entry) -> PrefFontList* {
        if (!entry) {
          // if not found, ask fontconfig to pick the appropriate font
          RefPtr<FcPattern> genericPattern = dont_AddRef(FcPatternCreate());
```
with:
```cpp
      cacheKey, [&](auto&& entry) -> PrefFontList* {
        if (!entry) {
          // Camoufox (#92): the per-context table step, taken BEFORE the
          // fontconfig loop and unconditionally for a context that has a list.
          //
          // The loop below is FcFontSort(..., trim=FcFalse, ...) over the whole
          // config (:2760), so it returns every font sorted by fontconfig's
          // distance metric and the walk takes the first `limit` (default 3)
          // families the gate accepts. Under a mac per-context list the three
          // families fontconfig actually means -- Tinos, Arimo, Cousine -- are
          // all refused, so what comes back is three families chosen by
          // distance from a pattern the gate has already emptied of its real
          // answer, and they need not be of the generic's kind at all. That is
          // #92's mechanism. It does not depend on the list coming back empty,
          // which is why this step is not conditioned on that.
          //
          // Memoize ONLY when the helper answers AND the gated resolution comes
          // back non-empty. A candidate that cannot be resolved is not an
          // answer: memoizing an empty PrefFontList in place of the loop would
          // turn a masked launch into a generic that resolves to nothing, which
          // pre-A2 code never did.
          //
          // The resolution goes through the SCOPE-QUALIFIED base
          // gfxPlatformFontList::FindAndAddFamiliesLocked, exactly as the loop
          // below does at :2781-2784, never the virtual: the virtual is this
          // class's own override, which re-enters generic detection and
          // mFcSubstituteCache.
          const uint32_t camouCtx =
              mozilla::dom::FontListManager::GetCurrentContext();
          if (camouCtx != 0 &&
              mozilla::dom::FontListManager::HasFontList(camouCtx)) {
            // FIRST statement in this block, before CamouGenericCandidate is
            // called. That helper is MOZ_REQUIRES(mLock), and clang's
            // thread-safety analysis does not carry an enclosing function's
            // held capabilities into a lambda body -- which is exactly why
            // upstream repeats this assertion before its own
            // FindAndAddFamiliesLocked call at :2778. FindGenericFamilies is
            // itself MOZ_REQUIRES(mLock) (gfxFcPlatformFontList.h:359-361), so
            // the lock IS held; this is what makes the analysis see it.
            mLock.AssertCurrentThreadIn();
            StyleGenericFontFamily camouGeneric =
                StyleGenericFontFamily::SansSerif;
            if (aGeneric.EqualsLiteral("serif")) {
              camouGeneric = StyleGenericFontFamily::Serif;
            } else if (aGeneric.EqualsLiteral("monospace")) {
              camouGeneric = StyleGenericFontFamily::Monospace;
            }
            nsAutoCString camouKey, camouStep;
            bool camouAnswered = false;
            if (CamouGenericCandidate(aFontVisibilityProvider, camouGeneric,
                                      camouKey, camouStep)) {
              AutoTArray<FamilyAndGeneric, 1> camouFamilies;
              if (gfxPlatformFontList::FindAndAddFamiliesLocked(
                      aFontVisibilityProvider, StyleGenericFontFamily::None,
                      camouKey, &camouFamilies, FindFamiliesFlags(0)) &&
                  !camouFamilies.IsEmpty()) {
                auto camouPrefFonts = MakeUnique<PrefFontList>();
                camouPrefFonts->AppendElement(camouFamilies[0].mFamily);
                camouAnswered = true;
                LOG_FONTLIST(
                    ("CAMOU-FL generic-map ctx=%u generic=%d step=%s key=%s",
                     camouCtx, int(camouGeneric), camouStep.get(),
                     camouKey.get()));
                entry.Insert(std::move(camouPrefFonts));
              }
            }
            if (!camouAnswered) {
              LOG_FONTLIST(
                  ("CAMOU-FL generic-map ctx=%u generic=%d step=none key=none",
                   camouCtx, int(camouGeneric)));
            } else {
              return entry->get();
            }
          }

          // if not found, ask fontconfig to pick the appropriate font
          RefPtr<FcPattern> genericPattern = dont_AddRef(FcPatternCreate());
```

- [ ] **Step 5: Take the same step in the base `AddGenericFonts`**

Neither DWrite nor CoreText has a `FindGenericFamilies` (`grep -n FindGenericFamilies
gfx/thebes/*.cpp` finds it only in `gfxFcPlatformFontList.cpp`), so their generics come
through the pref memo and Step 4 alone would fix #92 on Linux only.

In `camoufox-152.0.4-beta.31/gfx/thebes/gfxPlatformFontList.cpp`, in
`gfxPlatformFontList::AddGenericFonts`, replace:

```cpp
  // langGroup ==> prefLang
  eFontPrefLang prefLang = GetFontPrefLangFor(langGroup);

  // lookup pref fonts
  PrefFontList* prefFonts = GetPrefFontsLangGroupLocked(aFontVisibilityProvider,
                                                        aGenericType, prefLang);
```
with:
```cpp
  // langGroup ==> prefLang
  eFontPrefLang prefLang = GetFontPrefLangFor(langGroup);

  // Camoufox (#92): the same table step gfxFcPlatformFontList::FindGenericFamilies
  // takes, here so the fix is platform-neutral. This is the ONLY generic path
  // on DWrite and CoreText -- neither has a FindGenericFamilies -- and A1's
  // read filter below only REMOVES refused families from the pref list; it adds
  // no per-context substitute, so on those platforms a generic under a list
  // would otherwise shrink to nothing and fall to the default font, which is
  // #92's exact symptom.
  //
  // Placed AFTER the math remap above so the row asked for is the row the
  // caller ends up wanting. Falls through to the pref memo when the helper
  // declines or its key resolves empty.
  {
    const uint32_t camouCtx = mozilla::dom::FontListManager::GetCurrentContext();
    if (camouCtx != 0 &&
        mozilla::dom::FontListManager::HasFontList(camouCtx)) {
      nsAutoCString camouKey, camouStep;
      bool camouAnswered = false;
      if (CamouGenericCandidate(aFontVisibilityProvider, aGenericType, camouKey,
                                camouStep)) {
        AutoTArray<FamilyAndGeneric, 1> camouFamilies;
        if (FindAndAddFamiliesLocked(aFontVisibilityProvider,
                                     StyleGenericFontFamily::None, camouKey,
                                     &camouFamilies, FindFamiliesFlags(0)) &&
            !camouFamilies.IsEmpty()) {
          camouAnswered = true;
          LOG_FONTLIST(("CAMOU-FL generic-map ctx=%u generic=%d step=%s key=%s",
                        camouCtx, int(aGenericType), camouStep.get(),
                        camouKey.get()));
          aFamilyList.AppendElement(
              FamilyAndGeneric(camouFamilies[0].mFamily, aGenericType));
        }
      }
      if (camouAnswered) {
        return;
      }
      LOG_FONTLIST(("CAMOU-FL generic-map ctx=%u generic=%d step=none key=none",
                    camouCtx, int(aGenericType)));
    }
  }

  // lookup pref fonts
  PrefFontList* prefFonts = GetPrefFontsLangGroupLocked(aFontVisibilityProvider,
                                                        aGenericType, prefLang);
```

- [ ] **Step 6: Gate `GetDefaultFontLocked`'s two last resorts, with an unfiltered tail**

In the same file, replace `gfxPlatformFontList::GetDefaultFontLocked`'s body
(`:2954-2971`):

```cpp
FontFamily gfxPlatformFontList::GetDefaultFontLocked(
    FontVisibilityProvider* aFontVisibilityProvider,
    const gfxFontStyle* aStyle) {
  FontFamily family =
      GetDefaultFontForPlatform(aFontVisibilityProvider, aStyle);
  if (!family.IsNull()) {
    return family;
  }
  // Something has gone wrong and we were unable to retrieve a default font
  // from the platform. (Likely the whitelist has blocked all potential
  // default fonts.) As a last resort, we return the first font in our list.
  if (SharedFontList()) {
    MOZ_RELEASE_ASSERT(SharedFontList()->NumFamilies() > 0);
    return FontFamily(SharedFontList()->Families());
  }
  MOZ_RELEASE_ASSERT(mFontFamilies.Count() > 0);
  return FontFamily(mFontFamilies.ConstIter().Data());
}
```
with:
```cpp
FontFamily gfxPlatformFontList::GetDefaultFontLocked(
    FontVisibilityProvider* aFontVisibilityProvider,
    const gfxFontStyle* aStyle) {
  FontFamily family =
      GetDefaultFontForPlatform(aFontVisibilityProvider, aStyle);
  if (!family.IsNull()) {
    return family;
  }

  // Camoufox (#88): before the two last resorts, give a context with its own
  // list a chance to name a family from it. "-moz-default" is what
  // GetDefaultFontForPlatform asks fontconfig for, and it is a literal string,
  // not a StyleGenericFontFamily -- it takes the sans-serif row.
  {
    const uint32_t camouCtx = mozilla::dom::FontListManager::GetCurrentContext();
    if (camouCtx != 0 &&
        mozilla::dom::FontListManager::HasFontList(camouCtx)) {
      nsAutoCString camouKey, camouStep;
      bool camouAnswered = false;
      if (CamouGenericCandidate(aFontVisibilityProvider,
                                StyleGenericFontFamily::SansSerif, camouKey,
                                camouStep)) {
        AutoTArray<FamilyAndGeneric, 1> camouFamilies;
        if (FindAndAddFamiliesLocked(aFontVisibilityProvider,
                                     StyleGenericFontFamily::None, camouKey,
                                     &camouFamilies, FindFamiliesFlags(0)) &&
            !camouFamilies.IsEmpty()) {
          camouAnswered = true;
          LOG_FONTLIST(("CAMOU-FL generic-map ctx=%u generic=%d step=%s key=%s",
                        camouCtx, int(StyleGenericFontFamily::SansSerif),
                        camouStep.get(), camouKey.get()));
          return camouFamilies[0].mFamily;
        }
      }
      // Spec A2 asks for generic-map on EVERY context-scoped generic
      // resolution, `key=none` when the helper declined. Without this line the
      // one site that can silently fall through to an unfiltered last resort
      // would be the one site with nothing in the log explaining it.
      if (!camouAnswered) {
        LOG_FONTLIST(("CAMOU-FL generic-map ctx=%u generic=%d step=none key=none",
                      camouCtx, int(StyleGenericFontFamily::SansSerif)));
      }
    }
  }

  // Something has gone wrong and we were unable to retrieve a default font
  // from the platform. (Likely the whitelist has blocked all potential
  // default fonts.) As a last resort, we return the first font in our list.
  //
  // Camoufox (#88): "first font in our list" becomes "first font the gate
  // allows", WITH AN UNFILTERED TAIL. A gate that finds nothing must not turn
  // this into a null FontFamily: the caller at gfxTextRun.cpp:2207-2221 does
  // `family.mUnshared->FindFontForStyle(...)` behind a debug-only MOZ_ASSERT,
  // so an empty answer is a content-process crash on a shipped build, not a
  // diagnosable MOZ_CRASH_UNSAFE. GetFontFamilyList (:1315-1338) already
  // refills unfiltered for exactly this reason, and the log line says when the
  // tail fired so a guard can see it.
  if (SharedFontList()) {
    MOZ_RELEASE_ASSERT(SharedFontList()->NumFamilies() > 0);
    fontlist::FontList* list = SharedFontList();
    fontlist::Family* families = list->Families();
    for (uint32_t i = 0, n = list->NumFamilies(); i < n; ++i) {
      if (families[i].IsHidden()) {
        continue;
      }
      if (CamouIsFamilyAllowed(aFontVisibilityProvider,
                               families[i].Key().AsString(list))) {
        return FontFamily(&families[i]);
      }
    }
    LOG_FONTLIST(("CAMOU-FL default-unfiltered ctx=%u",
                  mozilla::dom::FontListManager::GetCurrentContext()));
    return FontFamily(families);
  }
  MOZ_RELEASE_ASSERT(mFontFamilies.Count() > 0);
  for (auto iter = mFontFamilies.ConstIter(); !iter.Done(); iter.Next()) {
    if (CamouIsFamilyAllowed(aFontVisibilityProvider, iter.Data()->Name())) {
      return FontFamily(iter.Data());
    }
  }
  LOG_FONTLIST(("CAMOU-FL default-unfiltered ctx=%u",
                mozilla::dom::FontListManager::GetCurrentContext()));
  return FontFamily(mFontFamilies.ConstIter().Data());
}
```

- [ ] **Step 7: Scope and gate `gfxFontGroup::GetDefaultFont`**

In `camoufox-152.0.4-beta.31/gfx/thebes/gfxTextRun.cpp`, insert at the very top of
`gfxFontGroup::GetDefaultFont` (`:2201`), before `if (mDefaultFont) {`:

```cpp
  // Camoufox (#88): this function opened NO AutoFontListContext, so everything
  // below it -- gfxPlatformFontList::GetDefaultFont, GetDefaultFontForPlatform
  // and, on Linux, the fontconfig generic loop it reaches -- resolved and
  // MEMOIZED under context 0. Its two callers disagree: GetFirstValidFont's
  // tail (:2408) is inside the scope opened at :2327, and FindFontForChar's
  // fontListLength == 0 branch (:3518) is not. mUserContextId is this group's
  // own cached id, so opening the scope here makes both callers agree without
  // depending on either.
  mozilla::dom::AutoFontListContext autoFontListCtx(mUserContextId);

```

Then replace the shared-list last-resort walk (`:2237-2263`):

```cpp
    if (pfl->SharedFontList()) {
      fontlist::FontList* list = pfl->SharedFontList();
      numFonts = list->NumFamilies();
      fontlist::Family* families = list->Families();
      for (uint32_t i = 0; i < numFonts; ++i) {
        fontlist::Family* fam = &families[i];
        if (!fam->IsInitialized()) {
          (void)pfl->InitializeFamily(fam);
        }
        fontlist::Face* face =
            fam->FindFaceForStyle(pfl->SharedFontList(), mStyle);
        if (face) {
          fe = pfl->GetOrCreateFontEntry(face, fam);
          if (fe) {
            mDefaultFont = fe->FindOrMakeFont(&mStyle);
            if (mDefaultFont) {
              break;
            }
            NS_WARNING("FindOrMakeFont failed");
          }
        }
      }
    } else {
```
with:
```cpp
    if (pfl->SharedFontList()) {
      fontlist::FontList* list = pfl->SharedFontList();
      numFonts = list->NumFamilies();
      fontlist::Family* families = list->Families();
      // Camoufox (#88): this walk had no gate at all, and it is the LIVE branch
      // (gfx.e10s.font-list.shared defaults true), so it is the face that
      // serves text after a per-context refusal. Two passes: the first honours
      // the gate, the second is the unfiltered tail. The tail is not optional
      // -- a context whose list names only families this process does not have
      // resident is reachable through the public setFontList API, and returning
      // no font from here reaches MOZ_CRASH_UNSAFE at :2306. The log line names
      // the pass so a guard can see the tail fire.
      for (int camouPass = 0; camouPass < 2 && !mDefaultFont; ++camouPass) {
        if (camouPass == 1) {
          CAMOU_LOG_FONTLIST(("CAMOU-FL default-unfiltered ctx=%u",
                              mUserContextId));
        }
        for (uint32_t i = 0; i < numFonts; ++i) {
          fontlist::Family* fam = &families[i];
          if (camouPass == 0 &&
              !gfxPlatformFontList::CamouIsFamilyAllowed(
                  mFontVisibilityProvider, fam->Key().AsString(list))) {
            continue;
          }
          if (!fam->IsInitialized()) {
            (void)pfl->InitializeFamily(fam);
          }
          fontlist::Face* face =
              fam->FindFaceForStyle(pfl->SharedFontList(), mStyle);
          if (face) {
            fe = pfl->GetOrCreateFontEntry(face, fam);
            if (fe) {
              mDefaultFont = fe->FindOrMakeFont(&mStyle);
              if (mDefaultFont) {
                break;
              }
              NS_WARNING("FindOrMakeFont failed");
            }
          }
        }
      }
    } else {
```

The non-shared `else` branch below is left untouched: it calls `pfl->GetFontFamilyList`,
which is already per-context gated and already refills unfiltered on empty
(`gfxPlatformFontList.cpp:1332-1337`), and it is dormant while
`gfx.e10s.font-list.shared` is true.

- [ ] **Step 8: Regenerate, guard, dry-run**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox/camoufox-152.0.4-beta.31
git add -A
git reset -q _READY || true
git diff --cached first-checkpoint > ../.superpowers/sdd-fonts3/fls-t4.patch
cd ..
diff <(grep '^diff --git' patches/font-list-spoofing.patch) \
     <(grep '^diff --git' .superpowers/sdd-fonts3/fls-t4.patch)
for sec in dom/base/FontListManager.cpp dom/base/FontListManager.h dom/base/moz.build \
           dom/base/nsGlobalWindowInner.cpp dom/base/nsGlobalWindowInner.h \
           dom/webidl/Window.webidl gfx/thebes/gfxFcPlatformFontList.h \
           layout/style/FontFaceSet.cpp; do
  echo "--- $sec"
  diff <(awk -v s="diff --git a/$sec" '$0==s{f=1} f&&/^diff --git/&&$0!=s{exit} f' patches/font-list-spoofing.patch) \
       <(awk -v s="diff --git a/$sec" '$0==s{f=1} f&&/^diff --git/&&$0!=s{exit} f' .superpowers/sdd-fonts3/fls-t4.patch)
done
cp .superpowers/sdd-fonts3/fls-t4.patch patches/font-list-spoofing.patch
grep -c '^@@' patches/font-list-spoofing.patch
```
Expected: identical section lists, no output from any of the eight per-section diffs
(only `gfxFcPlatformFontList.cpp`, `gfxPlatformFontList.{h,cpp}` and `gfxTextRun.cpp`
change), and a hunk count to record.

```bash
make revert
git -C camoufox-152.0.4-beta.31 clean -fdq
CAMOU_PATCH=/opt/homebrew/bin/gpatch make dir 2>&1 \
  | tee .superpowers/sdd-fonts3/make-dir-t4.log | tail -20
grep -c 'FAILED' .superpowers/sdd-fonts3/make-dir-t4.log
grep -niE 'fuzz|offset' .superpowers/sdd-fonts3/make-dir-t4.log
cd camoufox-152.0.4-beta.31
grep -n 'CamouGenericCandidate' gfx/thebes/gfxPlatformFontList.h gfx/thebes/gfxPlatformFontList.cpp gfx/thebes/gfxFcPlatformFontList.cpp
grep -c 'CAMOU-FL generic-map' gfx/thebes/gfxPlatformFontList.cpp gfx/thebes/gfxFcPlatformFontList.cpp
grep -c 'CAMOU-FL default-unfiltered' gfx/thebes/gfxPlatformFontList.cpp gfx/thebes/gfxTextRun.cpp
grep -n 'AutoFontListContext autoFontListCtx(mUserContextId);' gfx/thebes/gfxTextRun.cpp
sed -n '/if (!entry) {/,/RefPtr<FcPattern> genericPattern/p' gfx/thebes/gfxFcPlatformFontList.cpp | tail -6
cd ..
```
Expected: `0` FAILED; fuzz/offset only on `window-setter-seal.patch` and
`system-ui-font-spoofing.patch`; one declaration and one definition of
`CamouGenericCandidate` plus three call sites (`gfxPlatformFontList.cpp` twice —
`AddGenericFonts` and `GetDefaultFontLocked` — and `gfxFcPlatformFontList.cpp` once);
`generic-map` counts `4` and `2` — `AddGenericFonts` and `GetDefaultFontLocked` each emit
an answered and a declined line, `FindGenericFamilies` both — and `default-unfiltered`
counts `2` and `1` (`GetDefaultFontLocked`'s shared and unshared tails,
`gfxFontGroup::GetDefaultFont`'s single pass-1 line).

`grep -c 'mozilla::dom::AutoFontListContext autoFontListCtx(mUserContextId);'
gfx/thebes/gfxTextRun.cpp` must print **5**: the three that were already there
(`EnsureFontList` `:1956`, `GetFirstValidFont` `:2327`, `WhichSystemFontSupportsChar`
`:4036`), plus `WhichPrefFontSupportsChar` from Task 3 and `GetDefaultFont` from this
task. Read the number back rather than assuming it. Finally, the table block must sit
**above** `RefPtr<FcPattern> genericPattern` in `gfxFcPlatformFontList.cpp`.

- [ ] **Step 9: Commit**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
git add patches/font-list-spoofing.patch
git commit -m "fix(#88 #92): scope the default font, give generics a per-context step

Two issues, one mechanism: a context with its own font list had no way to say
which of ITS families a generic or a default should resolve to, and the code
that answers both questions ran outside its context.

#92. gfxFcPlatformFontList::FindGenericFamilies calls FcFontSort with
trim=FcFalse, so it walks the WHOLE sorted config and takes the first three
families the gate accepts. Under a mac per-context list the three families
fontconfig actually means -- Tinos, Arimo, Cousine on the bundle's own
fonts.conf -- are all refused, so what comes back is three families ranked by
distance from a pattern the gate has already emptied of its answer, and they
need not be of the generic's kind at all. gfxPlatformFontList::CamouGenericCandidate
answers first, from an ordered OS-agnostic table intersected with the context's
own list: the generic's own row, then the other two rows in query-relative
order so a proportional query never lands on a monospaced face while a
proportional one is in the list, then the shared list in index order. The step
that answered goes in the log. The same step runs in the base AddGenericFonts,
which is the ONLY generic path on DWrite and CoreText -- neither platform has a
FindGenericFamilies -- so this is fixed platform-neutrally rather than deferred
to an arm that cannot see it.

An empty resolution is never memoized in place of the fontconfig loop. A
candidate the gated lookup cannot resolve is not an answer, and memoizing the
empty list would turn a masked launch into a generic that resolves to nothing --
a regression pre-A2 code did not have, in the configuration that ships.

#88. gfxFontGroup::GetDefaultFont opened no AutoFontListContext, so everything
below it resolved and memoized under context 0 -- while one of its two callers
(GetFirstValidFont) does hold a scope and the other (FindFontForChar's
fontListLength == 0 branch) does not. It now opens its own from the group's
cached id. Its shared-list last-resort walk, the live branch, had no gate at
all; it is now two passes, gated then unfiltered. GetDefaultFontLocked's two
last resorts get the same treatment.

Every one of those walks keeps an UNFILTERED TAIL. A context whose list names
only families this process does not have resident is reachable through the
public setFontList API, and a gate that returned nothing there would produce a
default-constructed FontFamily that gfxTextRun.cpp:2207-2221 dereferences behind
a debug-only MOZ_ASSERT -- a content-process crash on a shipped build.
GetFontFamilyList already refills unfiltered for exactly this reason.
CAMOU-FL default-unfiltered says when a tail fired.

Every gate this round adds asks BOTH gates through
gfxPlatformFontList::CamouIsFamilyAllowed; the file-static stays private.

Verified: CAMOU_PATCH=gpatch make dir, 0 FAILED, no fuzz or offset on any
gfx/thebes file; <N> hunks; the applied tree shows the table block above
FcPatternCreate, three CamouGenericCandidate call sites, and five
AutoFontListContext(mUserContextId) scopes in gfxTextRun.cpp -- the three that
were already there (EnsureFontList, GetFirstValidFont,
WhichSystemFontSupportsChar) plus WhichPrefFontSupportsChar and GetDefaultFont.
Measured by smoke arms (n2) and (h3).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

Append to the ledger: the sha, hunk count, and every grep count from Step 8.

---

### Task 5: A3 (#91) — real `FontFaceLoadStatus` for non-local faces (`patches/font-hijacker.patch`)

Three edits in `layout/style/`, all inside `patches/font-hijacker.patch`.

**Safe to run after Tasks 3 and 4** even though `font-hijacker.patch` sorts *before*
`font-list-spoofing.patch` by basename: both patches carry
`gfx/thebes/gfxPlatformFontList.{cpp,h}` sections, but A3 touches only `layout/style/`,
so `font-list-spoofing.patch`'s anchors do not move. Step 6's full-stack dry-run is the
proof, and it requires **zero fuzz on `font-list-spoofing.patch`**.

**Files:**
- Create: `.superpowers/sdd-fonts3/splice.py` (untracked)
- Modify: `patches/font-hijacker.patch`
- Modify (transiently, never committed):
  `camoufox-152.0.4-beta.31/layout/style/FontFace.cpp`,
  `camoufox-152.0.4-beta.31/layout/style/FontFaceImpl.cpp`

**Interfaces:**
- Consumes: `bool FontFaceImpl::CamouHasNonLocalSource() const` — already in the patch
  from round 2 (PR #84), visible at `FontFace.cpp:285`, `FontFace.cpp:314` and
  `FontFaceImpl.cpp:370`.
- Produces: no new symbol.

- [ ] **Step 1: Write the argv-driven splicer**

`patches/font-hijacker.patch` carries a 38-line prose header before its first
`diff --git`, which no `git diff` can reproduce, and its sections are not in path-sorted
order. `.superpowers/sdd-fonts2/splice_fh.py` does the right thing but has **no CLI** —
`OLD`, `NEW`, `OUT` and `TARGETS` are module-level constants. Create an argv version
with the same `sections()` logic:

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
cat > .superpowers/sdd-fonts3/splice.py <<'PY'
#!/usr/bin/env python3
"""Replace only the named sections of a patch file with the regenerated ones,
leaving every other byte untouched -- including a prose header (which no
`git diff` can reproduce), pre-existing offset-carrying hunk headers, the
index-line conventions of the other sections, and the ORDER of the sections
(which git diff always re-sorts by path).

Usage: splice.py OLD.patch NEW.patch OUT.patch section [section ...]

Index-line policy, copied from .superpowers/sdd-fonts2/splice_fh.py: keep git's
regenerated `index` line where the original section had one, drop it where the
original had none.
"""
import sys


def sections(path):
    """[(name_or_None, [lines])] preserving order and exact bytes."""
    lines = open(path, encoding="utf-8").read().split("\n")
    out, cur, name = [], [], None
    for ln in lines:
        if ln.startswith("diff --git "):
            if cur:
                out.append((name, cur))
            name = ln.split(" b/")[-1]
            cur = [ln]
        else:
            cur.append(ln)
    if cur:
        out.append((name, cur))
    return out


def main(argv):
    if len(argv) < 5:
        sys.exit(__doc__)
    old_p, new_p, out_p, targets = argv[1], argv[2], argv[3], argv[4:]
    old, new = sections(old_p), sections(new_p)
    result, spliced = [], []
    for n, body in old:
        if n not in targets:
            result.extend(body)
            continue
        repl = [s for m, s in new if m == n]
        if len(repl) != 1:
            sys.exit(f"FATAL: {len(repl)} '{n}' sections in {new_p}")
        repl = list(repl[0])
        had_index = any(l.startswith("index ") for l in body)
        if not any(l.startswith("index ") for l in repl):
            sys.exit(f"FATAL: regenerated '{n}' has no index line")
        if not had_index:
            repl = [l for l in repl if not l.startswith("index ")]
        result.extend(repl)
        spliced.append((n, had_index, len(body), len(repl)))
    if len(spliced) != len(targets):
        sys.exit(f"FATAL: spliced {len(spliced)} of {len(targets)} targets")
    open(out_p, "w", encoding="utf-8").write("\n".join(result))
    for n, had_index, lo, ln in spliced:
        print(f"spliced {n}: index-line kept={had_index}  {lo} -> {ln} lines")
    print(f"wrote {out_p}")


if __name__ == "__main__":
    main(sys.argv)
PY
python3 .superpowers/sdd-fonts3/splice.py 2>&1 | head -3
```
Expected: the usage text (it exits when given no arguments).

- [ ] **Step 2: Build the workspace at `font-hijacker.patch`**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
git status --short
make revert
git -C camoufox-152.0.4-beta.31 clean -fdq
sed 's/^TARGET = .*/TARGET = "font-hijacker.patch"/' .superpowers/sdd-44/apply_upto.py \
  > .superpowers/sdd-fonts3/apply_upto_fh.py
grep -n '^TARGET' .superpowers/sdd-fonts3/apply_upto_fh.py
python3 .superpowers/sdd-fonts3/apply_upto_fh.py 2>&1 | tail -25
```
Expected: `19:TARGET = "font-hijacker.patch"`; then
`OK: all N pre-target patches applied clean` and `=== .rej files left: []`.

Confirm the anchors:
```bash
cd camoufox-152.0.4-beta.31
git tag --points-at HEAD
grep -n 'CamouHasNonLocalSource' layout/style/FontFace.cpp layout/style/FontFaceImpl.cpp
grep -n 'FontFaceLoadStatus FontFace::Status()\|Promise\* FontFace::Load(' layout/style/FontFace.cpp
grep -n 'void FontFaceImpl::SetStatus(' layout/style/FontFaceImpl.cpp
cd ..
```
Expected: `first-checkpoint`; `FontFace.cpp:285`, `FontFace.cpp:314`,
`FontFaceImpl.cpp:370`; `FontFace.cpp:263`, `FontFace.cpp:292`;
`FontFaceImpl.cpp:354`.

- [ ] **Step 3: `FontFaceImpl::SetStatus` — run the upstream body for a non-local face**

In `camoufox-152.0.4-beta.31/layout/style/FontFaceImpl.cpp`, replace the whole body of
`SetStatus` (`:354-400`):

```cpp
void FontFaceImpl::SetStatus(FontFaceLoadStatus aStatus) {
  gfxFontUtils::AssertSafeThreadOrServoFontMetricsLocked();

  // GetFamily() returns the CSS-escaped, possibly-quoted family name;
  // use the raw atom instead so a quoted CSS-rule key is never compared
  // against unquoted per-context list entries (#44).
  nsAutoCString fontFamily;
  if (nsAtom* familyName = GetFamilyName()) {
    fontFamily = nsAtomCString(familyName);
  }

  // #80: a url() or ArrayBuffer face's family name is invented by the page and
  // can never be in an OS font list, so the family gate can only ever answer
  // "no" for it. Skip the gate for those; keep it for local()-only faces,
  // whose family name genuinely names a host font. Note this does NOT restore
  // real load status -- aStatus is still discarded here, tracked separately.
  if (CamouHasNonLocalSource() || IsFontAllowed(fontFamily)) {
    mStatus = FontFaceLoadStatus::Loaded;
  } else {
    mStatus = FontFaceLoadStatus::Error;
  }

  if (mInFontFaceSet) {
    mFontFaceSet->OnFontFaceStatusChanged(this);
  }

  for (FontFaceSetImpl* otherSet : mOtherFontFaceSets) {
    otherSet->OnFontFaceStatusChanged(this);
  }

  UpdateOwnerPromise();
}
```
with:
```cpp
void FontFaceImpl::SetStatus(FontFaceLoadStatus aStatus) {
  gfxFontUtils::AssertSafeThreadOrServoFontMetricsLocked();

  // #91: for a face whose bytes come from the page -- any url() source, or an
  // ArrayBuffer face -- run UPSTREAM'S body verbatim, including the equal
  // early-out and the backwards-transition guard this fork had deleted. #80
  // stopped such a face being reported `error`; it left every one of them
  // reported `loaded`, which is a different wrong answer: a page can 404 its
  // own font and read `loaded`, and `document.fonts.ready` resolves on a face
  // that never loaded. The producers that carry the REAL network result are
  // FontFaceImpl::Entry::SetLoadState (:842, :845-846); everything below is
  // what lets their answer through.
  if (CamouHasNonLocalSource()) {
    if (mStatus == aStatus) {
      return;
    }

    if (aStatus < mStatus) {
      // We're being asked to go backwards in status!  Normally, this shouldn't
      // happen.  But it can if the FontFace had a user font entry that had
      // loaded, but then was given a new one by FontFaceSet::InsertRuleFontFace
      // if we used a local() rule.  For now, just ignore the request to
      // go backwards in status.
      return;
    }

    mStatus = aStatus;

    if (mInFontFaceSet) {
      mFontFaceSet->OnFontFaceStatusChanged(this);
    }

    for (FontFaceSetImpl* otherSet : mOtherFontFaceSets) {
      otherSet->OnFontFaceStatusChanged(this);
    }

    UpdateOwnerPromise();
    return;
  }

  // local()-only face: the family name genuinely names a host font, so the
  // gate stays and the status is still derived from it rather than from a
  // load that never happens.
  //
  // GetFamily() returns the CSS-escaped, possibly-quoted family name;
  // use the raw atom instead so a quoted CSS-rule key is never compared
  // against unquoted per-context list entries (#44).
  nsAutoCString fontFamily;
  if (nsAtom* familyName = GetFamilyName()) {
    fontFamily = nsAtomCString(familyName);
  }

  if (IsFontAllowed(fontFamily)) {
    mStatus = FontFaceLoadStatus::Loaded;
  } else {
    mStatus = FontFaceLoadStatus::Error;
  }

  if (mInFontFaceSet) {
    mFontFaceSet->OnFontFaceStatusChanged(this);
  }

  for (FontFaceSetImpl* otherSet : mOtherFontFaceSets) {
    otherSet->OnFontFaceStatusChanged(this);
  }

  UpdateOwnerPromise();
}
```

- [ ] **Step 4: `FontFace::Status()` — read `mStatus` for a non-local face**

In `camoufox-152.0.4-beta.31/layout/style/FontFace.cpp`, replace `Status()`'s tail
(`:272-290`, starting at the `// GetFamily() returns the CSS-escaped family name` comment
directly below the `AutoFontListContext` declaration):

```cpp
  // GetFamily() returns the CSS-escaped family name (quoted when it
  // needs quoting, e.g. '"Segoe UI"'), which then never matches an
  // unquoted per-context list entry. GetFamilyName() is the raw,
  // unquoted atom (#44).
  nsAutoCString fontFamily;
  if (nsAtom* familyName = mImpl->GetFamilyName()) {
    fontFamily = nsAtomCString(familyName);
  }

  // #80: same skip as FontFaceImpl::SetStatus. This getter is the one a page
  // reads most often, and on the JS FontFace path it runs before the face has
  // a gfxUserFontEntry at all -- which is why the test is on the descriptor
  // block rather than the entry.
  if (mImpl->CamouHasNonLocalSource() || mozilla::dom::IsFontAllowed(fontFamily)) {
    return FontFaceLoadStatus::Loaded;
  } else {
    return FontFaceLoadStatus::Error;
  }
}
```
with:
```cpp
  // #91: this getter never read mStatus at all -- it recomputed a verdict from
  // the family gate on every call, so FontFaceImpl::Status() (`return mStatus;`)
  // was dead for every face. For a page-supplied face the real status is the
  // one SetStatus stored, so read it.
  if (mImpl->CamouHasNonLocalSource()) {
    return mImpl->Status();
  }

  // GetFamily() returns the CSS-escaped family name (quoted when it
  // needs quoting, e.g. '"Segoe UI"'), which then never matches an
  // unquoted per-context list entry. GetFamilyName() is the raw,
  // unquoted atom (#44).
  nsAutoCString fontFamily;
  if (nsAtom* familyName = mImpl->GetFamilyName()) {
    fontFamily = nsAtomCString(familyName);
  }

  if (mozilla::dom::IsFontAllowed(fontFamily)) {
    return FontFaceLoadStatus::Loaded;
  } else {
    return FontFaceLoadStatus::Error;
  }
}
```

The `AutoFontListContext` at the top of the function is left in place: the `local()`
branch below still needs it, and it is harmless for the early return.

- [ ] **Step 5: `FontFace::Load()` — actually load a non-local face**

In the same file, replace `Load()`'s tail (`:305-322`):

```cpp
  // Same fix as Status() above: use the raw family atom, not the
  // CSS-escaped (possibly quoted) string (#44).
  nsAutoCString fontFamily;
  if (nsAtom* familyName = mImpl->GetFamilyName()) {
    fontFamily = nsAtomCString(familyName);
  }

  // #80: same skip as Status() above, so `new FontFace(f, 'url(...)').load()`
  // resolves instead of rejecting for a family the page invented.
  if (mImpl->CamouHasNonLocalSource() || mozilla::dom::IsFontAllowed(fontFamily)) {
    // For allowed fonts, always resolve the promise
    mLoaded->MaybeResolve(this);
  } else {
    // For non-allowed fonts, always reject the promise
    mLoaded->MaybeReject(NS_ERROR_FAILURE);
  }

  mImpl->UpdateOwnerKeepAlive();
  return mLoaded;
}
```
with:
```cpp
  // #91: for a page-supplied face, run upstream's body. This fork resolved the
  // promise from the family gate and never called mImpl->Load() at all, which
  // is why FontFaceImpl::Load, DoLoad and CreateUserFontEntry had NO caller
  // anywhere in the tree and no SetLoadState ever fired for such a face.
  // Restoring the call gives them one; the promise then resolves or rejects
  // from mStatus through UpdateOwnerPromiseSync (FontFaceImpl.cpp:412-430),
  // which is first-wins, so a real network failure rejects.
  if (mImpl->CamouHasNonLocalSource()) {
    mImpl->Load();
    mImpl->UpdateOwnerKeepAlive();
    return mLoaded;
  }

  // Same fix as Status() above: use the raw family atom, not the
  // CSS-escaped (possibly quoted) string (#44).
  nsAutoCString fontFamily;
  if (nsAtom* familyName = mImpl->GetFamilyName()) {
    fontFamily = nsAtomCString(familyName);
  }

  if (mozilla::dom::IsFontAllowed(fontFamily)) {
    // For allowed fonts, always resolve the promise
    mLoaded->MaybeResolve(this);
  } else {
    // For non-allowed fonts, always reject the promise
    mLoaded->MaybeReject(NS_ERROR_FAILURE);
  }

  mImpl->UpdateOwnerKeepAlive();
  return mLoaded;
}
```

- [ ] **Step 6: Regenerate, splice, dry-run the full stack**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox/camoufox-152.0.4-beta.31
git add -A
git reset -q _READY || true
git diff --cached first-checkpoint > ../.superpowers/sdd-fonts3/fh-new.patch
cd ..
diff <(grep '^diff --git' patches/font-hijacker.patch) \
     <(grep '^diff --git' .superpowers/sdd-fonts3/fh-new.patch)
```
Expected: the two lists differ **in order only** — `git diff` sorts by path while the
committed patch does not — and neither gains nor loses an entry. That reordering is
exactly why this patch is spliced rather than copied.

```bash
python3 .superpowers/sdd-fonts3/splice.py \
  patches/font-hijacker.patch \
  .superpowers/sdd-fonts3/fh-new.patch \
  .superpowers/sdd-fonts3/fh-spliced.patch \
  layout/style/FontFace.cpp layout/style/FontFaceImpl.cpp
head -3 .superpowers/sdd-fonts3/fh-spliced.patch
diff <(grep '^diff --git' patches/font-hijacker.patch) \
     <(grep '^diff --git' .superpowers/sdd-fonts3/fh-spliced.patch)
diff <(sed -n '1,38p' patches/font-hijacker.patch) \
     <(sed -n '1,38p' .superpowers/sdd-fonts3/fh-spliced.patch)
cp .superpowers/sdd-fonts3/fh-spliced.patch patches/font-hijacker.patch
```
Expected: `spliced layout/style/FontFace.cpp: …` and
`spliced layout/style/FontFaceImpl.cpp: …`; the spliced file's first three lines are the
original prose header's; the section-list diff prints **nothing**; the 38-line header
diff prints **nothing**.

The OLD-vs-SPLICED section-list diff is identical **by construction** — `splice.py`
copies OLD's non-target sections verbatim — so it can never fail and is not the guard.
The guard is the OLD-vs-`fh-new.patch` comparison above it, which is the one that can
detect a workspace edit outside the two target files.

```bash
make revert
git -C camoufox-152.0.4-beta.31 clean -fdq
CAMOU_PATCH=/opt/homebrew/bin/gpatch make dir 2>&1 \
  | tee .superpowers/sdd-fonts3/make-dir-t5.log | tail -20
grep -c 'FAILED' .superpowers/sdd-fonts3/make-dir-t5.log
grep -niE 'fuzz|offset' .superpowers/sdd-fonts3/make-dir-t5.log
```
Expected: `0` FAILED, and the fuzz/offset grep shows **nothing on
`font-list-spoofing.patch`** — that is the proof that editing a patch which sorts
earlier did not move Tasks 3 and 4's anchors. Offsets on `window-setter-seal.patch` and
`system-ui-font-spoofing.patch` are accepted as before. Any output naming
`gfxPlatformFontList`, `gfxTextRun` or `gfxFcPlatformFontList` is a stop.

Read the tree back:
```bash
cd camoufox-152.0.4-beta.31
grep -n 'CamouHasNonLocalSource' layout/style/FontFace.cpp layout/style/FontFaceImpl.cpp layout/style/FontFaceImpl.h
grep -n 'return mImpl->Status();\|mImpl->Load();' layout/style/FontFace.cpp
sed -n '/void FontFaceImpl::SetStatus(/,/^}/p' layout/style/FontFaceImpl.cpp | grep -n 'aStatus < mStatus\|mStatus == aStatus\|mStatus = aStatus'
cd ..
```
Expected: five `CamouHasNonLocalSource` hits (declaration, definition, and one call in
each of `SetStatus`, `Status()`, `Load()`); one `return mImpl->Status();` and one
`mImpl->Load();`; and the three restored upstream lines inside `SetStatus`.

- [ ] **Step 7: Commit**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
git add patches/font-hijacker.patch
git commit -m "fix(#91): report the real FontFaceLoadStatus for non-local faces

PR #84 stopped a page's own url() web font being reported 'error'. It left
every one of them reported 'loaded', which is a different wrong answer and a
detector-visible one: a page can 404 its own font and read status 'loaded',
document.fonts.ready resolves on a face that never loaded, and FontFace.load()
resolves regardless of the network.

Four couplings produced that, all verified on the tree:

FontFaceImpl::SetStatus discarded aStatus entirely and wrote Loaded or Error
from the family gate, dropping upstream's equal early-out AND its
backwards-transition guard. The producers that carry the real network result --
FontFaceImpl::Entry::SetLoadState and its dispatched lambda -- had their answer
thrown away.

FontFace::Status() never read mStatus at all; it recomputed the same verdict on
every call, so FontFaceImpl::Status(), which is `return mStatus;`, was dead code
for every face in the tree.

FontFace::Load() resolved its promise from the gate and never called
mImpl->Load(), so FontFaceImpl::Load, DoLoad and CreateUserFontEntry had no
caller anywhere -- grep for mImpl->Load() found nothing -- and no SetLoadState
ever fired for a JS-constructed face.

For a face whose bytes come from the page (any url() source, or an ArrayBuffer
face) all three now run upstream's body verbatim; local()-only faces, whose
family name genuinely names a host font, keep the gate. The promise resolves or
rejects from mStatus through UpdateOwnerPromiseSync, which is first-wins.

Verified: CAMOU_PATCH=gpatch make dir, 0 FAILED, and NO fuzz or offset on
patches/font-list-spoofing.patch -- editing a patch that sorts earlier did not
move the previous two commits' anchors. The 38-line prose header and the
section ORDER of font-hijacker.patch are byte-identical: this patch is spliced,
never regenerated wholesale, because git diff re-sorts sections by path.
Measured by smoke arm (n7).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

Append to the ledger: the sha, the splice output, and the fuzz/offset grep result.

---

### Task 6: A4 (#90) — per-context speech voices (`patches/speech-voices-spoofing.patch`) — CONDITIONAL

Read the gate first. Run this task **only** if it says `GATE: B5 RED`.

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
grep -E '^GATE: B5 (RED|GREEN)$' .superpowers/sdd-fonts3/gate-b5.md
```
- `GATE: B5 RED` → run every step below.
- `GATE: B5 GREEN` → **skip this task entirely.** #90 closes on the measurement alone
  (spec §C); record the skip in the ledger and move to Task 7.
- Neither, or no file → Task 2 Step 11 did not finish. Stop.

**Files:**
- Modify: `patches/speech-voices-spoofing.patch`
- Modify (transiently, never committed):
  `camoufox-152.0.4-beta.31/dom/base/SpeechVoicesManager.cpp`

**Interfaces:**
- Consumes: `.superpowers/sdd-fonts3/gate-b5.md`.
- Produces: no new symbol. `SpeechVoicesManager`'s public API is unchanged —
  `SetVoices`, `HasVoices`, `IsVoiceAllowed`, `DisableFunction`,
  `IsFunctionEnabledForWebIDL` keep their exact signatures, so
  `dom/media/webspeech/synth/SpeechSynthesis.cpp` and `dom/webidl/Window.webidl` are
  untouched.

- [ ] **Step 1: Build the workspace**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
git status --short
make revert
git -C camoufox-152.0.4-beta.31 clean -fdq
sed 's/^TARGET = .*/TARGET = "speech-voices-spoofing.patch"/' .superpowers/sdd-44/apply_upto.py \
  > .superpowers/sdd-fonts3/apply_upto_sv.py
grep -n '^TARGET' .superpowers/sdd-fonts3/apply_upto_sv.py
python3 .superpowers/sdd-fonts3/apply_upto_sv.py 2>&1 | tail -25
grep -n 'sVoicesMap\|RoverfoxStorageManager' camoufox-152.0.4-beta.31/dom/base/SpeechVoicesManager.cpp
grep -n 'RoverfoxStorageManager' camoufox-152.0.4-beta.31/dom/base/SpeechVoicesManager.h
```
Expected: `19:TARGET = "speech-voices-spoofing.patch"`;
`OK: all N pre-target patches applied clean`; `=== .rej files left: []`; four
`sVoicesMap` hits and two `RoverfoxStorageManager` hits in the `.cpp`; and one
`#include "RoverfoxStorageManager.h"` already present in the `.h`, so **no include
change is needed**.

- [ ] **Step 2: Replace the process-local map with cross-process storage**

In `camoufox-152.0.4-beta.31/dom/base/SpeechVoicesManager.cpp`, replace everything from
`static mozilla::Mutex sVoicesMutex(...)` through the end of `IsVoiceAllowed`:

```cpp
static mozilla::Mutex sVoicesMutex("SpeechVoicesManager");
static nsTHashMap<nsUint32HashKey, nsTHashSet<nsString>> sVoicesMap;

nsString SpeechVoicesManager::DisabledKeyForUserContext(uint32_t aId) {
  nsAutoString key;
  key.AppendPrintf("spvoices_d_%u", aId);
  return key;
}

void SpeechVoicesManager::SetVoices(uint32_t aUserContextId,
                                     const nsAString& aVoiceList) {
  MutexAutoLock lock(sVoicesMutex);
  nsTHashSet<nsString>& voiceSet = sVoicesMap.LookupOrInsert(aUserContextId);
  voiceSet.Clear();

  // Parse comma-separated voice names
  nsAutoString remaining(aVoiceList);
  while (!remaining.IsEmpty()) {
    int32_t comma = remaining.FindChar(',');
    nsAutoString name;
    if (comma >= 0) {
      name = Substring(remaining, 0, comma);
      remaining = Substring(remaining, comma + 1);
    } else {
      name = remaining;
      remaining.Truncate();
    }
    name.Trim(" \t");
    if (!name.IsEmpty()) {
      voiceSet.Insert(name);
    }
  }
}

bool SpeechVoicesManager::HasVoices(uint32_t aUserContextId) {
  MutexAutoLock lock(sVoicesMutex);
  return sVoicesMap.Contains(aUserContextId);
}

bool SpeechVoicesManager::IsVoiceAllowed(uint32_t aUserContextId,
                                          const nsAString& aVoiceName) {
  MutexAutoLock lock(sVoicesMutex);
  auto* voiceSet = sVoicesMap.Lookup(aUserContextId).DataPtrOrNull();
  if (!voiceSet) return true;
  return voiceSet->Contains(nsString(aVoiceName));
}
```
with:
```cpp
// Camoufox (#90): the voice list used to live in a file-static nsTHashMap,
// which is PROCESS-LOCAL, while the one-shot disable flag beside it went
// through the cross-process RoverfoxStorageManager. A context therefore
// installed its list in the process that ran the init script and could then
// render in a content process that never received it -- the exact asymmetry
// #83 turned out to be for the font list. The list now goes through the same
// cross-process store the flag does, in the shape WebGLParamsManager uses
// (patches/webgl-spoofing.patch: PutString / GetString on a per-context key).
//
// The list is stored joined by ',' and re-split at read. Voice names are
// arbitrary strings and could in principle contain a comma, which would split
// one name into two -- both halves then fail IsVoiceAllowed, so the failure is
// a refusal, not a leak. That is the same trade the comma-separated
// setFontList / setSpeechVoices WebIDL surface already makes at the input end.
nsString SpeechVoicesManager::VoicesKeyForUserContext(uint32_t aId) {
  nsAutoString key;
  key.AppendPrintf("spvoices_%u", aId);
  return key;
}

nsString SpeechVoicesManager::DisabledKeyForUserContext(uint32_t aId) {
  nsAutoString key;
  key.AppendPrintf("spvoices_d_%u", aId);
  return key;
}

void SpeechVoicesManager::SetVoices(uint32_t aUserContextId,
                                     const nsAString& aVoiceList) {
  // Normalise on the way in -- trim each name and drop the empties -- so a
  // reader can compare against the stored string without re-parsing rules.
  nsAutoString joined;
  nsAutoString remaining(aVoiceList);
  while (!remaining.IsEmpty()) {
    int32_t comma = remaining.FindChar(',');
    nsAutoString name;
    if (comma >= 0) {
      name = Substring(remaining, 0, comma);
      remaining = Substring(remaining, comma + 1);
    } else {
      name = remaining;
      remaining.Truncate();
    }
    name.Trim(" \t");
    if (!name.IsEmpty()) {
      if (!joined.IsEmpty()) {
        joined.Append(u',');
      }
      joined.Append(name);
    }
  }
  RoverfoxStorageManager::PutString(VoicesKeyForUserContext(aUserContextId),
                                    joined);
}

bool SpeechVoicesManager::HasVoices(uint32_t aUserContextId) {
  nsAutoString stored;
  return RoverfoxStorageManager::GetString(
      VoicesKeyForUserContext(aUserContextId), stored);
}

bool SpeechVoicesManager::IsVoiceAllowed(uint32_t aUserContextId,
                                          const nsAString& aVoiceName) {
  nsAutoString stored;
  if (!RoverfoxStorageManager::GetString(
          VoicesKeyForUserContext(aUserContextId), stored)) {
    // No list installed for this context: unchanged behaviour, allow.
    return true;
  }
  nsAutoString remaining(stored);
  while (!remaining.IsEmpty()) {
    int32_t comma = remaining.FindChar(',');
    nsAutoString name;
    if (comma >= 0) {
      name = Substring(remaining, 0, comma);
      remaining = Substring(remaining, comma + 1);
    } else {
      name = remaining;
      remaining.Truncate();
    }
    if (name.Equals(aVoiceName)) {
      return true;
    }
  }
  return false;
}
```

Then delete the **one** now-unused include at the top of the same file. `sVoicesMap` and
its `MutexAutoLock` are gone, so nothing in the `.cpp` needs `Mutex.h` any more:
```cpp
#include "mozilla/Mutex.h"
```
Remove that line and leave every other include. `nsTHashMap` and `nsTHashSet` come from
`SpeechVoicesManager.h`, which this change does not prune.

- [ ] **Step 3: Declare the new key helper**

In `camoufox-152.0.4-beta.31/dom/base/SpeechVoicesManager.h`, replace:
```cpp
 private:
  static nsString DisabledKeyForUserContext(uint32_t aId);
};
```
with:
```cpp
 private:
  // Camoufox (#90): the per-context key the voice list is stored under in
  // RoverfoxStorageManager, alongside the disable flag's own key.
  static nsString VoicesKeyForUserContext(uint32_t aId);
  static nsString DisabledKeyForUserContext(uint32_t aId);
};
```

`nsTHashMap`, `nsHashKeys` and `nsTHashSet` are still included by the header; leave them
rather than pruning includes that were not this change's to touch.

- [ ] **Step 4: Regenerate, splice, dry-run**

`patches/speech-voices-spoofing.patch`'s sections are **not** in path-sorted order
(`nsGlobalWindowInner.h` precedes `.cpp`, and `dom/media/…` follows `dom/webidl/…`), so
it must be spliced.

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox/camoufox-152.0.4-beta.31
git add -A
git reset -q _READY || true
git diff --cached first-checkpoint > ../.superpowers/sdd-fonts3/sv-new.patch
cd ..
# PRE-splice check, and it is the only one that can fail. splice.py copies
# OLD's non-target sections verbatim, so OLD-vs-SPLICED is identical by
# construction; comparing them proves nothing. What has to be checked is
# OLD vs the REGENERATED diff: the two section lists must contain the same
# entries, differing only in order (git diff sorts by path, this patch does
# not). A gained or lost entry means the workspace edit touched a file outside
# the two targets, and splicing would silently drop it.
diff <(grep '^diff --git' patches/speech-voices-spoofing.patch | sort) \
     <(grep '^diff --git' .superpowers/sdd-fonts3/sv-new.patch | sort)
python3 .superpowers/sdd-fonts3/splice.py \
  patches/speech-voices-spoofing.patch \
  .superpowers/sdd-fonts3/sv-new.patch \
  .superpowers/sdd-fonts3/sv-spliced.patch \
  dom/base/SpeechVoicesManager.cpp dom/base/SpeechVoicesManager.h
diff <(grep '^diff --git' patches/speech-voices-spoofing.patch) \
     <(grep '^diff --git' .superpowers/sdd-fonts3/sv-spliced.patch)
cp .superpowers/sdd-fonts3/sv-spliced.patch patches/speech-voices-spoofing.patch

make revert
git -C camoufox-152.0.4-beta.31 clean -fdq
CAMOU_PATCH=/opt/homebrew/bin/gpatch make dir 2>&1 \
  | tee .superpowers/sdd-fonts3/make-dir-t6.log | tail -20
grep -c 'FAILED' .superpowers/sdd-fonts3/make-dir-t6.log
grep -niE 'fuzz|offset' .superpowers/sdd-fonts3/make-dir-t6.log
cd camoufox-152.0.4-beta.31
grep -c 'sVoicesMap' dom/base/SpeechVoicesManager.cpp
grep -n 'VoicesKeyForUserContext' dom/base/SpeechVoicesManager.cpp dom/base/SpeechVoicesManager.h
grep -n 'setSpeechVoices' dom/webidl/Window.webidl
cd ..
```
Expected: the section-list diff prints nothing (order preserved); `0` FAILED; no fuzz or
offset on any `gfx/thebes/` or `layout/style/` file; `sVoicesMap` count `0`; **five**
`VoicesKeyForUserContext` hits — one declaration in the `.h`, one definition in the
`.cpp`, and one use each in `SetVoices`, `HasVoices` and `IsVoiceAllowed` — and
`setSpeechVoices` still present in the WebIDL, unchanged.

- [ ] **Step 5: Commit**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
git add patches/speech-voices-spoofing.patch
git commit -m "fix(#90): store per-context speech voices cross-process

Smoke arm (n5) went RED on run <P0R2>: <paste the arm's own VOICES LEAK line>.

SpeechVoicesManager kept its per-context voice list in a file-static
nsTHashMap, which is process-local, while the one-shot disable flag beside it
went through the cross-process RoverfoxStorageManager. A context installed its
list in whichever process ran the init script and could then render in a
content process that never received it -- the same asymmetry #83 turned out to
be for the font list.

The list now goes through the same store the flag does, in the shape
WebGLParamsManager uses: PutString / GetString on a per-context key, with
HasVoices becoming a GetString success test. The public API and the WebIDL
binding are unchanged, so SpeechSynthesis.cpp is untouched.

FontListManager has the same shape -- a process-local nsTHashMap for the value,
RoverfoxStorageManager for the flag -- and this RED is evidence about it too.
That consequence is written into the PR and into #44; it is not closed here as
a speech bug.

Verified: CAMOU_PATCH=gpatch make dir, 0 FAILED, no fuzz or offset on any
gfx/thebes or layout/style file; zero sVoicesMap references left in the applied
tree. The patch was SPLICED, not regenerated wholesale: its sections are not in
git-diff path order and a plain copy would silently reorder them.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

Append to the ledger: the sha and the grep counts.

---

### Task 7: Build, smoke, and the conditional #82 RED control

**Files:**
- Modify: `.github/workflows/smoke.yml` (`EXPECTED_RED` / `EXPECTED_GREEN` /
  `KNOWN_UNMEASURABLE` only)
- Create: `.superpowers/sdd-fonts3/smoke-p1-<id>.log`,
  `.superpowers/sdd-fonts3/smoke-p1-arms.txt`, `.superpowers/sdd-fonts3/gate-b4.md`,
  `.superpowers/sdd-fonts3/make-dir-final.log` (untracked)

**Interfaces:**
- Consumes: Tasks 3, 4, 5 and (conditionally) 6, all committed;
  `.superpowers/sdd-fonts3/gate-b4-phase0.md` from Task 2.
- Produces: `BUILD_LINUX`, `BUILD_WINDOWS` and `FIX_SHA` in the ledger. Task 8 uses
  `BUILD_WINDOWS`; Task 9 quotes all three.

- [ ] **Step 1: Retire the fixed arms from `EXPECTED_RED`**

Every arm this branch fixes must now be GREEN, and an arm that is expected GREEN and
comes back unmeasured fails under its own name — which is what makes the fix's evidence
mandatory rather than optional. Replace the `EXPECTED_RED` dict Task 2 Step 8 wrote
with:

```python
          # Round 3's C++ has landed, so every arm it fixes is expected GREEN
          # and moves to EXPECTED_GREEN below. What stays red here is only what
          # this branch does NOT close.
          EXPECTED_RED = {}
```

and add the round-3 arms to the existing `EXPECTED_GREEN` dict, keeping its current
entries:

```python
              "(n1)": "#94, the pref-font memo is populated unfiltered at context 0 and "
                      "both gates are asked at read",
              "(n2)": "#92, a generic under a per-context list resolves through the "
                      "ordered table intersected with that list",
              "(h3)": "#88, GetDefaultFont opens its own scope and both last-resort "
                      "walks are gate-approved with an unfiltered tail",
              "(n4)": "#82, the U+FFFD cache read is gated (PR #93) and this arm is the "
                      "measurement that gate never had",
              "(n7)": "#91, a non-local face reports the status its load produced",
```

`(n5)` goes to `EXPECTED_GREEN` **only if Task 6 ran**; if the gate said
`GATE: B5 GREEN`, add it there too, since it was already green. Either way it must not
stay in `EXPECTED_RED`.

If Task 1 Step 8's `phase0-run1.md` recorded that `(j)` or `(j2)` became measurable
under `FONTCONFIG_FILE`, remove that arm from `KNOWN_UNMEASURABLE` in the same edit —
an arm listed there that reaches its verdict now falls through to `unexpected` and fails
the step, which is the intended behaviour but must be a deliberate decision, not a
surprise.

- [ ] **Step 2: Apply the whole stack the way the build does, and read it back**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
git status --short
make revert
git -C camoufox-152.0.4-beta.31 clean -fdq
CAMOU_PATCH=/opt/homebrew/bin/gpatch make dir 2>&1 \
  | tee .superpowers/sdd-fonts3/make-dir-final.log | tail -20
grep -c 'FAILED' .superpowers/sdd-fonts3/make-dir-final.log
grep -niE 'fuzz|offset' .superpowers/sdd-fonts3/make-dir-final.log
cd camoufox-152.0.4-beta.31
grep -c 'CamouIsFamilyAllowed' gfx/thebes/gfxPlatformFontList.h gfx/thebes/gfxPlatformFontList.cpp gfx/thebes/gfxTextRun.cpp
grep -c 'CamouGenericCandidate' gfx/thebes/gfxPlatformFontList.cpp gfx/thebes/gfxFcPlatformFontList.cpp
grep -c 'CAMOU-FL pref-fallback\|CAMOU-FL fontlist\|CAMOU-FL generic-map\|CAMOU-FL default-unfiltered' \
  gfx/thebes/gfxPlatformFontList.cpp gfx/thebes/gfxFcPlatformFontList.cpp gfx/thebes/gfxTextRun.cpp
grep -c 'CamouHasNonLocalSource' layout/style/FontFace.cpp layout/style/FontFaceImpl.cpp
cd ..
```
Expected: `0` FAILED; fuzz/offset only on `window-setter-seal.patch` and
`system-ui-font-spoofing.patch`. **Record every count**; they go in the PR body and must
be read back, not recalled.

- [ ] **Step 3: Record the sha and dispatch both builds**

```bash
git log --oneline -6
git rev-parse HEAD
git push origin fix/fonts-round3
gh workflow run build.yml -R lang315/camoufox --ref fix/fonts-round3 -f build_target=linux-x86_64
gh workflow run build.yml -R lang315/camoufox --ref fix/fonts-round3 -f build_target=windows-x86_64
sleep 25
gh run list -w build.yml -R lang315/camoufox -L 5 \
  --json databaseId,headSha,status,displayTitle,createdAt \
  --jq '.[] | "\(.databaseId) \(.status) \(.headSha[0:7]) \(.createdAt) \(.displayTitle)"'
```
`gh run list` does not report the `build_target` input, so map ids to targets by reading
each run's own jobs rather than by guessing from order:
```bash
for id in <id1> <id2>; do
  echo -n "$id -> "
  gh run view "$id" -R lang315/camoufox --json jobs --jq '[.jobs[].name] | join(", ")'
done
cat >> .superpowers/sdd-fonts3/progress.md <<EOF
FIX_SHA=$(git rev-parse HEAD)
BUILD_LINUX=<id>
BUILD_WINDOWS=<id>
EOF
```

Wait with `Monitor` on:
```bash
for id in <BUILD_LINUX> <BUILD_WINDOWS>; do
  echo -n "$id "; gh run view "$id" -R lang315/camoufox --json status,conclusion \
    --jq '.status + " " + (.conclusion // "-")'
done
```
until both lines start with `completed`, capped at 60 minutes and re-armed until both
land (builds run 40–95 minutes, so expect two arming cycles). Expected: two
`completed success`. A `completed failure` means the patch does not compile — read
`gh run view <id> --log-failed`, fix in the owning task (3, 4, 5 or 6), and re-dispatch
**both** at the new sha so the PR's evidence comes from one commit.

- [ ] **Step 4: Smoke the Linux build and read every arm**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
gh workflow run smoke.yml -R lang315/camoufox --ref fix/fonts-round3 -f run_id=<BUILD_LINUX>
sleep 20
gh run list -R lang315/camoufox --workflow=smoke.yml --limit 3 \
  --json databaseId,status,createdAt --jq '.[] | "\(.databaseId) \(.status) \(.createdAt)"'
```
Record as `SMOKE_P1`, wait, then:
```bash
gh run view <SMOKE_P1> -R lang315/camoufox --log > .superpowers/sdd-fonts3/smoke-p1-<SMOKE_P1>.log
grep -v '36;1m' .superpowers/sdd-fonts3/smoke-p1-<SMOKE_P1>.log \
  | grep -E '\[arm (n1|n2|h3|n4|n5|n7) |\[setup\]|tripwire triage|SETUP-INVALID|UNEXPECTED RED|KNOWN UNMEASURABLE|GREEN' \
  | sed -E 's/^[^Z]*Z//' | cut -c1-260 \
  | tee .superpowers/sdd-fonts3/smoke-p1-arms.txt
grep -E '^  (pref-fallback|fontlist|generic-map|default-unfiltered) ' \
  .superpowers/sdd-fonts3/smoke-p1-<SMOKE_P1>.log | sed -E 's/^[^Z]*Z//'
```

Expected on this build:

| Arm | Expected | If different |
|---|---|---|
| `(n1)` | GREEN, with `pref-fallback ctx=N key=tinos allowed=0` in the arm's window | a `DIAGNOSTIC` line means the `fontlist` kind is still absent — Task 3 did not land in this binary |
| `(n2)` | GREEN, `generic-map` naming different in-list families for `monospace` and `sans-serif`, zero `default-unfiltered` for that context | a nonzero `default-unfiltered` count is a fixture bug, not a fix |
| `(h3)` | GREEN, `default ctx=N family=X` with `X` in the mac list | still RED means A2's walk did not take effect |
| `(n4)` | GREEN, with all four log preconditions observed | RED means #93's gate does not hold |
| `(n5)` | GREEN | RED after Task 6 means A4 did not take effect |
| `(n7)` | GREEN, 404 face `error`, control face `loaded` at width 1920 | `control invalid` means the HTTP server, not #91 |
| every pre-existing arm | unchanged from `phase0-run1.md` | a changed number is a regression from A1/A2 and must be explained before the PR |

The per-kind counter table must show all four new kinds with a non-zero count. A zero on
any of them means the emit site never ran in this binary.

- [ ] **Step 5: The #82 RED control (B6) — CONDITIONAL**

```bash
grep -E '^B6 TRIGGER: (YES|NO)$' .superpowers/sdd-fonts3/gate-b4-phase0.md
```
- `B6 TRIGGER: NO` → arm (n4) already went RED somewhere without the gate, so #82 has
  its control. Skip to Step 6 and record the skip.
- `B6 TRIGGER: YES` → run this step. Expect YES: on `8990915` there is no A1, so
  `WhichPrefFontSupportsChar` answers U+FFFD from the context-0 memo — under the bundle
  `fonts.conf` that is `Tinos`, which carries U+FFFD — for donor and victim alike, and
  `SystemFindFontForChar` is never reached.

The diagnostic drops **only** the refusal on the `fffd-cache` hit branch and **keeps the
log line**, so the leak is named in the log:

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
make revert
git -C camoufox-152.0.4-beta.31 clean -fdq
python3 .superpowers/sdd-44/apply_upto.py >/dev/null 2>&1
```
In `camoufox-152.0.4-beta.31/gfx/thebes/gfxPlatformFontList.cpp`, inside
`SystemFindFontForChar`'s `if (aCh == 0xFFFD)` block, replace:
```cpp
      if (!camouAllowed) {
        fontEntry = nullptr;
      }
```
with:
```cpp
      // B6 DIAGNOSTIC, reverted before merge and never on main: drop the
      // refusal so #82's leak reproduces, and KEEP the log line above so the
      // leak is named rather than merely rendered.
      (void)camouAllowed;
```
Then regenerate, `cp`, `make dir`, commit with a message whose first line is
`diag(#82): DO NOT MERGE -- drop the fffd-cache refusal to produce the RED control`,
push, and dispatch one Linux build and one smoke on it.

Expected on that smoke: `(n4)` RED with `U+FFFD CACHE LEAK`, the log carrying
`fffd-cache ctx=V key=menlo allowed=0`, and the victim's width equal to Menlo's. That is
#82's RED.

Then revert:
```bash
git revert --no-edit <diag sha>
git log --oneline -3
git push origin fix/fonts-round3
```
and re-dispatch the Linux build and smoke at the reverted head, which must be GREEN on
`(n4)` again. **Both the diagnostic commit and its revert stay on the branch; neither
reaches `main` as a net change.** Record both build ids, both smoke ids and both `(n4)`
readings in `.superpowers/sdd-fonts3/gate-b4.md`.

If `(n4)` cannot go RED even with the refusal dropped, **#82 stays open** with the
reason written (spec §C). Do not close it on a GREEN whose RED was never demonstrated.

- [ ] **Step 6: Write the final gate file and commit the triage edit**

```bash
cat > .superpowers/sdd-fonts3/gate-b4.md <<'EOF'
# #82 evidence

GREEN: run <SMOKE_P1>, arm (n4) on build <BUILD_LINUX> @ <FIX_SHA>
<paste the arm's own GREEN line and all four observed preconditions>

RED:   <one of>
  (a) run <SMOKE_B6>, arm (n4) on the diagnostic build <BUILD_B6>, refusal dropped
      <paste the U+FFFD CACHE LEAK line and the fffd-cache line>
  (b) NOT DEMONSTRATED. #82 stays open. Reason: <write it>
EOF

cd /Users/lang/GolandProjects/github.com/lang315/camoufox
python3 .superpowers/sdd-fonts2/check_smoke_python.py .github/workflows/smoke.yml \
  "$TMPDIR/smoke-py-t7"
git add .github/workflows/smoke.yml
git commit -m "measure(#44): retire the round-3 arms from EXPECTED_RED

Every arm this branch fixes is now expected GREEN, so a run in which one comes
back unmeasured fails under its own name rather than being absorbed. Read back
from run <SMOKE_P1> on build <BUILD_LINUX> @ <FIX_SHA>: <one line per arm with
its verdict>.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push origin fix/fonts-round3
```

Append to the ledger: `SMOKE_P1`, its conclusion, each arm's verdict, the four new kinds'
counts, and the B6 outcome.

---

### Task 8: B8 (#87) — native Windows, family-name arms and the codepoint arm

Runs on the user's Windows build PC. There is no Windows runner in `.github/workflows/`
(`smoke.yml:18` is `runs-on: ubuntu-24.04` and is the only runner declaration), and
`build-tester/run_tests.sh` has no Windows branch, so this is a standalone script run by
hand — the same shape round 2 used.

**#87 asks for both halves.** The existing family-name arms (`choose_host_family`, the
host-only survey, the in-list control, the bundled-unlisted sharpener) run **unchanged**,
in the same session, against the same two binaries. This task adds the codepoint arm
beside them.

**Files:**
- Modify: `build-tester/scripts/probe_windows_fonts.py`
- Create: `.superpowers/sdd-fonts3/probe-win-baseline.json`, `-round3.json`, and the
  matching `.log` files (untracked)

**Interfaces:**
- Consumes: `BUILD_WINDOWS` and `FIX_SHA` from Task 7; the Windows baseline build
  `34450188525` @ `c8c42ef`.
- Produces: two JSON result objects, each with the existing keys plus
  `codepoint` (`{"cp", "carriers", "chosen_reason", "control_cp", "control_carriers",
  "host_cmap_families", "bundle_cmap_families"}`) and two new `verdicts` rows whose
  `probe` field is `"codepoint"`. Task 9's PR body and the #87 comment quote them.

- [ ] **Step 1: Precondition — the SSH master must already be open**

Password authentication is in play on this host and repeated failures trip a fail2ban
lockout, so **never** retry authentication and never open a second connection after a
failure. The shell has a broken `ssh` wrapper; use `/usr/bin/ssh`.

```bash
/usr/bin/ssh -O check buildpc 2>&1
```
Expected: a line reporting the master process is running. **Anything else means stop and
report BLOCKED** — do not try to open it, and do not put the host address or port
anywhere in this repo. `buildpc` is the alias; the connection details live in the user's
SSH config.

- [ ] **Step 2: Confirm the native Windows venv**

WSL does not count — the question is about `C:\Windows\Fonts` on the Windows host.

```bash
/usr/bin/ssh buildpc 'D:\camou-probe\venv\Scripts\python.exe -c "import sys; print(sys.version); print(sys.executable)"'
/usr/bin/ssh buildpc 'D:\camou-probe\venv\Scripts\python.exe -m pip show playwright fonttools greenlet 2>&1 | findstr /B "Name Version"'
```
Expected: Python 3.11 or newer with an executable path under `D:\`; `playwright 1.55.0`
exactly, `fonttools 4.60.2`, `greenlet 3.1.1`. A newer Playwright reports a
clean-looking 0/0 against camoufox-152 (`CLAUDE.md`, memory `build-tester-playwright-pin`).
If the venv is missing, create it and install those three pins before continuing.

- [ ] **Step 3: Add the codepoint arm to the probe**

In `build-tester/scripts/probe_windows_fonts.py`, extend `PAGE_JS`. Replace:

```javascript
    // U+FFFD exercises codepoint fallback (SystemFindFontForChar /
    // GlobalFontFallback), which the family-name probes do not touch at all.
    // Reported, never scored: under a masked launch there is no reference
    // guaranteed to differ from it, so a verdict here could not be trusted.
    c.font = '48px "__NoSuchFamilyAtAll6__"';
    out['__fffd__'] = c.measureText('\uFFFD').width;
    c.font = '48px monospace';
    out['__monospace__'] = c.measureText(S).width;
```
with:
```javascript
    // U+FFFD exercises codepoint fallback (SystemFindFontForChar /
    // GlobalFontFallback), which the family-name probes do not touch at all.
    // Reported, never scored: under a masked launch there is no reference
    // guaranteed to differ from it, so a verdict here could not be trusted.
    c.font = '48px "__NoSuchFamilyAtAll6__"';
    out['__fffd__'] = c.measureText('\uFFFD').width;
    c.font = '48px monospace';
    out['__monospace__'] = c.measureText(S).width;
    // #87's codepoint half. Same stack for all three so the comparison is
    // within one document, one thread and one launch:
    //   __cp__      the codepoint whose only host carriers are OFF the launch
    //               list and which nothing bundled covers -- reachable bare,
    //               refused masked, if the gate holds
    //   __cpfloor__ a PUA codepoint in the SAME stack: the tofu floor
    //   __cpctl__   a codepoint covered only by an IN-LIST host family: must
    //               render identically bare and masked, or the whole
    //               measurement is about a dead font stack rather than a gate
    var cpFont = '48px "__NoSuchFamilyAtAll7__"';
    c.font = cpFont;
    out['__cp__'] = c.measureText(String.fromCodePoint(%(cp)d)).width;
    out['__cpfloor__'] = c.measureText('\uE000').width;
    out['__cpctl__'] = (%(cpctl)d > 0)
        ? c.measureText(String.fromCodePoint(%(cpctl)d)).width : null;
```

and extend `build_url` to pass the two new values:
```python
    js = PAGE_JS % {
        "absent1": json.dumps(ABSENT_1),
        "absent2": json.dumps(ABSENT_2),
        "families": json.dumps(list(families)),
        "node": RESULTS_NODE,
        "cp": codepoint,
        "cpctl": codepoint_control,
    }
```
`PAGE_JS` already uses `%%` for its literal percent (`'@#$%%^&*()_+'`), so the new
`%(cp)d` placeholders interpolate correctly.

Thread both values through `build_url` and `measure`. Replace their signatures:

```python
def build_url(families):
```
with:
```python
def build_url(families, codepoint, codepoint_control):
```
and:
```python
def measure(exe, families, camou_config, per_context_list, headful, timeout=60000):
```
with:
```python
def measure(exe, families, camou_config, per_context_list, headful, timeout=60000,
            codepoint=0, codepoint_control=0):
```
then, inside `measure`, replace:
```python
    url = build_url(families)
```
with:
```python
    url = build_url(families, codepoint, codepoint_control)
```

Add the selection function beside `choose_host_family`:

```python
def choose_codepoint(host_cmaps, bundle_cmaps, bundled_keys, launch_keys):
    """Pick the codepoint the masked launch must not be able to render.

    Returns (cp, carriers, reason) or (None, [], reason).

    The requirement is the same one that makes choose_host_family a control:
    the value under test must be reachable in the BARE launch, or its refusal
    under a mask is indistinguishable from "nothing covers it here". So the
    codepoint must be covered by at least one host family, by NO bundled
    family, and by NO family on the launch list.

    `bundle_cmaps` is separate from `host_cmaps` and load-bearing. Filtering
    only on `key in bundled_keys` while iterating host_cmaps excludes bundled
    families that are ALSO installed on the host -- and Makefile:190 packages a
    Windows artifact with `--fonts macos linux`, so the normal case is a bundled
    family the host does NOT have. Such a family contributes no cmap to
    host_cmaps, is invisible to a name-only filter, and would answer the
    codepoint under the masked launch legitimately -- which this arm would then
    score as a leak.
    """
    from collections import defaultdict
    by_cp = defaultdict(list)
    for key, (orig, cps) in host_cmaps.items():
        if key in bundled_keys or key in launch_keys or orig.startswith("."):
            continue
        for cp in cps:
            by_cp[cp].append(orig)
    # Everything reachable under the masked launch: host families that are on
    # the list, plus EVERY family the artifact bundles, whether or not the host
    # also has it.
    covered_elsewhere = set()
    for key, (orig, cps) in host_cmaps.items():
        if key in bundled_keys or key in launch_keys:
            covered_elsewhere |= cps
    for key, (orig, cps) in bundle_cmaps.items():
        covered_elsewhere |= cps
    usable = sorted(cp for cp, fams in by_cp.items()
                    if cp not in covered_elsewhere and 0x0100 <= cp < 0x2FFF)
    if not usable:
        return None, [], (
            "no codepoint is covered by a host-only, unlisted family and by "
            "nothing bundled or listed: the codepoint arm cannot run here")
    cp = usable[0]
    return cp, sorted(by_cp[cp]), (
        "lowest of %d codepoints covered only by host families that are "
        "neither bundled nor on the launch list; bundle coverage of %d "
        "families was subtracted" % (len(usable), len(bundle_cmaps)))


def choose_codepoint_control(host_cmaps, launch_keys):
    """A codepoint covered only by an IN-LIST host family. It must render the
    same bare and masked; if it does not, the masked launch has no working font
    stack at all and the arm above asserts nothing."""
    from collections import defaultdict
    in_list, out_list = defaultdict(list), set()
    for key, (orig, cps) in host_cmaps.items():
        if orig.startswith("."):
            continue
        if key in launch_keys:
            for cp in cps:
                in_list[cp].append(orig)
        else:
            out_list |= cps
    usable = sorted(cp for cp, fams in in_list.items()
                    if cp not in out_list and 0x0100 <= cp < 0x2FFF)
    return (usable[0], sorted(in_list[usable[0]])) if usable else (0, [])
```

Add the cmap reader beside `_names_from_file`, and the two walks beside
`bundle_families` / `host_families`:

```python
def _cmap_from_file(path):
    """(family names, covered codepoints) out of one font file.

    Same tolerance as _names_from_file: C:\\Windows\\Fonts holds .fon and other
    formats fontTools cannot open, and a single unreadable face must not cost
    the whole walk. Every cmap subtable of every face is unioned -- a font can
    put its Unicode coverage in a format-4 BMP table, a format-12 full table,
    or both, and reading only the first would under-report coverage, which for
    this arm means picking a codepoint some family CAN render.
    """
    from fontTools.ttLib import TTCollection, TTFont  # lazy: --self-test needs neither

    ext = path.suffix.lower()
    if ext not in (".ttf", ".otf", ".ttc", ".otc"):
        return set(), set()
    try:
        faces = (
            list(TTCollection(str(path)).fonts)
            if ext in (".ttc", ".otc")
            else [TTFont(str(path), fontNumber=0, lazy=True)]
        )
    except Exception:
        return set(), set()
    names, cps = _names_from_file(path), set()
    for face in faces:
        try:
            tables = list(face["cmap"].tables)
        except Exception:
            continue
        for t in tables:
            try:
                cps |= set(t.cmap.keys())
            except Exception:
                continue
    return names, cps


def host_cmaps(root=r"C:\Windows\Fonts"):
    """{casefolded name: (original spelling, set of codepoints)} for the host.

    Sibling of host_families(); same directory, same machine-wide-only scope.
    A family with several files (regular, bold, ...) accumulates the union of
    their coverage, which is the right question here: "can this family render
    the codepoint at all".
    """
    out = {}
    base = Path(root)
    if not base.is_dir():
        return out
    for p in sorted(base.iterdir()):
        if not p.is_file():
            continue
        names, cps = _cmap_from_file(p)
        for name in names:
            key = name.casefold()
            orig, seen = out.get(key, (name, set()))
            out[key] = (orig, seen | cps)
    return out


def bundle_cmaps(dirs):
    """{casefolded name: (original spelling, set of codepoints)} for the ARTIFACT.

    Not derivable from host_cmaps: Makefile:190 packages Windows with
    `--fonts macos linux`, so the normal case is a bundled family the host does
    not have, which contributes no cmap to host_cmaps at all. choose_codepoint
    subtracts this coverage because such a family answers the codepoint under
    the masked launch legitimately.
    """
    out = {}
    for d in dirs:
        for p in sorted(Path(d).rglob("*")):
            if not p.is_file():
                continue
            names, cps = _cmap_from_file(p)
            for name in names:
                key = name.casefold()
                orig, seen = out.get(key, (name, set()))
                out[key] = (orig, seen | cps)
    return out
```

Wire it into `main()`. Immediately after the existing
`in_list_probes` / `bundled_unlisted_probes` / `families` assignments and **before** the
`results = {` literal, insert:

```python
    # #87's codepoint half. Both cmap walks run here, once, because both are
    # slow (every face of every file) and both feed one selection.
    host_cps = host_cmaps()
    bundle_cps = bundle_cmaps(bundle_dirs)
    cp_value, cp_carriers, cp_reason = choose_codepoint(
        host_cps, bundle_cps, set(bundled), launch_keys)
    cp_ctl, cp_ctl_carriers = choose_codepoint_control(host_cps, launch_keys)
    if not host_cps:
        print(r"FATAL: no cmaps read from C:\Windows\Fonts. This script must run on "
              "the native Windows interpreter, not under WSL.")
        return 1
```

Then add the block to the `results = {` literal, beside `"candidates"`:

```python
        "codepoint": {
            "cp": cp_value,
            "carriers": cp_carriers,
            "chosen_reason": cp_reason,
            "control_cp": cp_ctl,
            "control_carriers": cp_ctl_carriers,
            "host_cmap_families": len(host_cps),
            "bundle_cmap_families": len(bundle_cps),
        },
```

Pass both codepoints to all three launches. Replace:

```python
    results["bare"] = measure(args.executable_path, families, {}, None, args.headful)
    results["launch_list"] = measure(args.executable_path, families,
                                     {"fonts": launch_list}, None, args.headful)
    results["per_context"] = measure(args.executable_path, families, {},
                                     launch_list, args.headful)
```
with:
```python
    results["bare"] = measure(args.executable_path, families, {}, None, args.headful,
                              codepoint=cp_value or 0, codepoint_control=cp_ctl)
    results["launch_list"] = measure(args.executable_path, families,
                                     {"fonts": launch_list}, None, args.headful,
                                     codepoint=cp_value or 0, codepoint_control=cp_ctl)
    results["per_context"] = measure(args.executable_path, families, {},
                                     launch_list, args.headful,
                                     codepoint=cp_value or 0, codepoint_control=cp_ctl)
```

And print it beside the existing U+FFFD line, replacing:

```python
    print("\n[U+FFFD, informational only] bare=%s launch_list=%s per_context=%s"
          % tuple(results[n]["widths"].get("__fffd__") for n in
                  ("bare", "launch_list", "per_context")))
```
with:
```python
    print("\n[U+FFFD, informational only] bare=%s launch_list=%s per_context=%s"
          % tuple(results[n]["widths"].get("__fffd__") for n in
                  ("bare", "launch_list", "per_context")))
    print("\n[codepoint arm] U+%04X carriers=%s\n  chosen: %s"
          % (cp_value or 0, cp_carriers, cp_reason))
    print("  control U+%04X carriers=%s" % (cp_ctl, cp_ctl_carriers))
    for name in ("bare", "launch_list", "per_context"):
        w = results[name]["widths"]
        print("    %-12s cp=%s floor=%s control=%s"
              % (name, w.get("__cp__"), w.get("__cpfloor__"), w.get("__cpctl__")))
```

Add the two verdict rows in `judge`, immediately before the `overall` computation:

```python
    # 7. #87's codepoint half. The family-name arms above never touch
    #    SystemFindFontForChar / GlobalFontFallback at all.
    cp = (results.get("codepoint") or {}).get("cp")
    if cp:
        bare_w = (results.get("bare") or {}).get("widths") or {}
        mask_w = (results.get("launch_list") or {}).get("widths") or {}
        ctx_w = (results.get("per_context") or {}).get("widths") or {}
        bare_cp, bare_floor = bare_w.get("__cp__"), bare_w.get("__cpfloor__")
        ctl_bare, ctl_mask = bare_w.get("__cpctl__"), mask_w.get("__cpctl__")
        if bare_cp is None or bare_floor is None:
            verdicts.append(_v("bare", "codepoint", "invalid",
                               "the codepoint or its floor was never measured"))
        elif abs(bare_cp - bare_floor) <= EPS:
            verdicts.append(_v("bare", "codepoint", "unscored",
                               "CONTROL FAILED: the codepoint measured its own tofu "
                               "floor in the BARE launch, where no mask applies, so a "
                               "refusal under a mask would assert nothing."))
        elif ctl_bare is None or ctl_mask is None or abs(ctl_bare - ctl_mask) > EPS:
            verdicts.append(_v("launch_list", "codepoint", "unscored",
                               "CONTROL FAILED: the in-list codepoint control rendered "
                               "differently bare (%s) and masked (%s), so the masked "
                               "launch has no working font stack and 'refused' says "
                               "nothing." % (ctl_bare, ctl_mask)))
        else:
            for name, w in (("launch_list", mask_w), ("per_context", ctx_w)):
                v = w.get("__cp__")
                if v is None:
                    verdicts.append(_v(name, "codepoint", "invalid",
                                       "the codepoint was never measured"))
                elif abs(v - bare_cp) <= EPS:
                    verdicts.append(_v(name, "codepoint", "fail",
                                       "U+%04X still resolves to a host family that is "
                                       "off the list (width %s matches the bare launch), "
                                       "so codepoint fallback reaches host fonts."
                                       % (cp, v)))
                else:
                    verdicts.append(_v(name, "codepoint", "pass",
                                       "U+%04X no longer resolves to its host carrier "
                                       "(%s bare vs %s here)." % (cp, bare_cp, v)))
    else:
        # choose_codepoint found no usable codepoint. Without this row the
        # block above appends NOTHING, `overall` stays "pass", and Task 9 would
        # close #87 on "both halves GREEN" while one half never ran -- a
        # silently absent measurement reading exactly like a passing one
        # (CLAUDE.md lesson 3). The risk is real: covered_elsewhere subtracts
        # every bundled family's coverage, a Windows artifact bundles the macOS
        # and Linux sets including Noto (Makefile:190), and the search window is
        # only 0x0100..0x2FFF.
        verdicts.append(_v("bare", "codepoint", "unscored",
                           "NOT RUN: %s" % ((results.get("codepoint") or {})
                                            .get("chosen_reason") or
                                            "no codepoint block in the result object")))
```

Then make an unscored codepoint half block a `pass`. Replace the `overall` computation:

```python
    if any(v["status"] == "invalid" for v in verdicts):
        overall = "invalid"
    elif any(v["status"] == "fail" for v in verdicts):
        overall = "fail"
    else:
        overall = "pass"
    return verdicts, overall
```
with:
```python
    # #87 closes on BOTH halves, so a codepoint half that produced no scored row
    # must not read as a pass. This is deliberately NARROW -- it looks only at
    # rows whose probe is "codepoint" -- because "unscored" elsewhere (the
    # bundled-unlisted sharpener when the in-list control failed) always travels
    # with an invalid or fail row that already decides the run.
    cp_rows = [v for v in verdicts if v["probe"] == "codepoint"]
    if any(v["status"] == "invalid" for v in verdicts):
        overall = "invalid"
    elif any(v["status"] == "fail" for v in verdicts):
        overall = "fail"
    elif not cp_rows or any(v["status"] == "unscored" for v in cp_rows):
        overall = "unscored"
    else:
        overall = "pass"
    return verdicts, overall
```

`main()` already does `return 0 if overall == "pass" else 1` and
`results["passed"] = overall == "pass"`, so an `unscored` run exits non-zero without
another edit. Add one line beside the existing `invalid` message, replacing:

```python
    if overall == "invalid":
        print("This run measured nothing usable. Do not report a pass or a fail from it.")
```
with:
```python
    if overall == "invalid":
        print("This run measured nothing usable. Do not report a pass or a fail from it.")
    elif overall == "unscored":
        print("The family-name half ran, but the codepoint half produced no scored "
              "verdict. #87 asks for BOTH halves; do not close it on this run.")
```

`_canned` (`build-tester/scripts/probe_windows_fonts.py:669-686`) builds each launch
through a **nested `run(host, extra=None)`** and returns a dict literal; `self_test`
(`:691-745`) has one helper, `check(label, cond)`, a closure at `:695`. There is no
`_check` and no `_judge_status`. The edits below are written against those.

Replace `_canned`'s signature:

```python
def _canned(host_w=120.0, list_w=None, ctx_w=None, absent=80.0,
            data_fl='{"saw":true,"applied":true,"err":null}', absent2=None):
```
with:
```python
def _canned(host_w=120.0, list_w=None, ctx_w=None, absent=80.0,
            data_fl='{"saw":true,"applied":true,"err":null}', absent2=None,
            cp=0x2C60, cp_bare=200.0, cp_masked=80.0, cp_floor=80.0,
            cp_ctl=150.0, cp_ctl_masked=None):
```

The defaults describe a PASSING codepoint half — reachable bare (200 ≠ floor 80), refused
under both masks (80), control stable at 150 — so every pre-existing self-test case keeps
its current verdict. That matters more than usual now: with the `overall` change above, a
result object carrying **no** codepoint rows scores `unscored`, and `check("clean run is
pass", o == "pass")` at `:726` would start failing if `_canned` did not supply them.

Then give `run()` the two extra widths and add the `codepoint` block to the returned dict.
Replace the whole body:

```python
    def run(host, extra=None):
        w = {"__absent1__": absent, "__absent2__": absent if absent2 is None else absent2,
             "Host One": host, "Listed A": absent + 40, "Listed B": absent + 41,
             "Unlisted X": absent, "__fffd__": 9.0, "__monospace__": absent}
        w.update(extra or {})
        return {"widths": w, "data_fl": None, "page_error": None}
    return {
        "host_family": "Host One",
        "host_family_reason": "canned",
        "candidates": ["Host One"],
        "in_list_probes": ["Listed A", "Listed B"],
        "bundled_unlisted_probes": ["Unlisted X"],
        "bare": run(host_w),
        "launch_list": run(absent if list_w is None else list_w),
        "per_context": dict(run(absent if ctx_w is None else ctx_w), data_fl=data_fl),
    }
```
with:
```python
    ctl_masked = cp_ctl if cp_ctl_masked is None else cp_ctl_masked

    def run(host, cp_w, ctl_w, extra=None):
        w = {"__absent1__": absent, "__absent2__": absent if absent2 is None else absent2,
             "Host One": host, "Listed A": absent + 40, "Listed B": absent + 41,
             "Unlisted X": absent, "__fffd__": 9.0, "__monospace__": absent,
             "__cp__": cp_w, "__cpfloor__": cp_floor, "__cpctl__": ctl_w}
        w.update(extra or {})
        return {"widths": w, "data_fl": None, "page_error": None}
    return {
        "host_family": "Host One",
        "host_family_reason": "canned",
        "candidates": ["Host One"],
        "in_list_probes": ["Listed A", "Listed B"],
        "bundled_unlisted_probes": ["Unlisted X"],
        "codepoint": {"cp": cp, "carriers": ["Host One"],
                      "chosen_reason": "canned"},
        "bare": run(host_w, cp_bare, cp_ctl),
        "launch_list": run(absent if list_w is None else list_w,
                           cp_masked, ctl_masked),
        "per_context": dict(run(absent if ctx_w is None else ctx_w,
                                cp_masked, ctl_masked), data_fl=data_fl),
    }
```

`run`'s two new parameters are positional and required, and its only three call sites are
the ones shown, so a missed one is a `TypeError` at self-test time rather than a silently
absent width.

Then add the cases at the end of `self_test()`, after the `applied:false is invalid`
check at `:744-745` and before whatever `self_test` does with `fails`. They use `check`
and one local closure, in the same style as the rest of the function:

```python
    print("codepoint arm (#87):")

    def cp_status(obj):
        """The set of statuses on rows whose probe is 'codepoint'."""
        return {x["status"] for x in judge(obj)[0] if x["probe"] == "codepoint"}

    check("reachable bare, refused under both masks -> pass",
          cp_status(_canned()) == {"pass"})
    check("still resolves to the host carrier under a mask -> fail",
          cp_status(_canned(cp_masked=200.0)) == {"fail"})
    check("codepoint measures its own tofu floor in the BARE launch -> unscored",
          cp_status(_canned(cp_bare=80.0)) == {"unscored"})
    check("in-list codepoint control moved between launches -> unscored",
          cp_status(_canned(cp_ctl_masked=99.0)) == {"unscored"})
    no_cp = _canned()
    no_cp["codepoint"]["cp"] = None
    check("no codepoint selected -> an unscored row, not silence",
          cp_status(no_cp) == {"unscored"})
    check("and that alone stops the run reading as a pass",
          judge(no_cp)[1] == "unscored")
    check("a clean run still passes with the codepoint half present",
          judge(_canned())[1] == "pass")
```

Every expected status above follows from `judge`'s own branches on those widths: default
`cp_bare=200.0` differs from `cp_floor=80.0` so the bare control holds; `cp_masked=80.0`
differs from `cp_bare` so both masked launches pass; raising `cp_masked` to `200.0` makes
`abs(v - bare_cp) <= EPS` true in both, giving two `fail` rows; `cp_bare=80.0` equals the
floor, which short-circuits to the single bare `unscored` row; and `cp_ctl_masked=99.0`
makes `abs(ctl_bare - ctl_mask) > EPS` true, which short-circuits to the masked `unscored`
row.

Run it before shipping anything:
```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
python3 build-tester/scripts/probe_windows_fonts.py --self-test
```
Expected: every case reported, `0 failed`. This needs neither Playwright nor fontTools
nor a browser, so it costs a second.

- [ ] **Step 4: Ship both artifacts and run**

`D:\camou-probe\artifact` must be re-created from the build run being tested; a stale
directory silently changes the candidate pool (`Makefile:190` — a Windows artifact
bundles macOS and Linux fonts, never Windows).

For each of the two runs — baseline `34450188525` @ `c8c42ef`, then round 3
`<BUILD_WINDOWS>` @ `<FIX_SHA>`:

```bash
/usr/bin/ssh buildpc 'powershell -Command "Remove-Item -Recurse -Force D:\camou-probe\artifact -ErrorAction SilentlyContinue; New-Item -ItemType Directory -Force D:\camou-probe\artifact"'
/usr/bin/ssh buildpc 'powershell -Command "cd D:\camou-probe\artifact; gh run download <RUN_ID> -R lang315/camoufox -n CamoufoxBuilds-windows-x86_64 -D .; Get-ChildItem"'
/usr/bin/ssh buildpc 'powershell -Command "cd D:\camou-probe\artifact; Expand-Archive -Force (Get-ChildItem *.zip)[0].FullName .\cf; Get-ChildItem -Recurse -Filter camoufox.exe | Select-Object -First 1 FullName"'
```
Note the quoting, which is the reverse of what round 2's note said: the whole `ssh`
argument is **single**-quoted here, and `powershell -Command` takes a **double**-quoted
string inside it, so any literal quoting the PowerShell command itself needs must be
single quotes. Getting this backwards ends the command early and the failure looks like a
PowerShell syntax error, not a quoting one.

Copy the probe over and run it. `scp` treats the first `:` as the host/path separator, so
a bare `buildpc:D:/…` target is ambiguous; give the path relative to the SSH session's
home directory, or quote it so the drive letter survives:
```bash
/usr/bin/scp build-tester/scripts/probe_windows_fonts.py 'buildpc:D:\camou-probe\probe.py'
/usr/bin/ssh buildpc 'powershell -Command "D:\camou-probe\venv\Scripts\python.exe D:\camou-probe\probe.py --executable-path <exe path> --bundle-dir <artifact fonts dir> --out D:\camou-probe\out.json"' \
  2>&1 | tee .superpowers/sdd-fonts3/probe-win-<label>.log
/usr/bin/ssh buildpc 'powershell -Command "Get-Content D:\camou-probe\out.json"' \
  > .superpowers/sdd-fonts3/probe-win-<label>.json
```
`--bundle-dir` must point at the **extracted artifact's own** fonts directory, never at
this checkout's `bundle/fonts` — a repo checkout is a proxy that can drift from the
binary under test.

Expected on the **round-3** build: `overall: PASS`, with a `pass` row for every
`launch_list` and `per_context` probe including the two `codepoint` rows. Expected on the
**baseline**: a `fail` row on `codepoint` is a #94-shaped finding on Windows and is the
RED that makes the round-3 PASS mean something; a `pass` there means the codepoint half
was already closed on Windows and the PR says so rather than claiming a fix.

If either run prints `overall: INVALID`, it measured nothing usable. Do not report a
pass or a fail from it; read which control failed and re-select the codepoint.

If either prints `overall: UNSCORED`, the family-name half ran and the codepoint half did
not reach a verdict. The run carries a `[unscored] bare codepoint …` row saying why —
either `NOT RUN:` followed by `choose_codepoint`'s own `chosen_reason` (no codepoint
survived the filter), or one of the two control failures. **#87 does not close on such a
run.** Widen the search window in `choose_codepoint`, or accept that this host cannot
supply the arm and say so in the issue; do not read the missing half as a pass.

- [ ] **Step 5: Commit the probe change**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
git add build-tester/scripts/probe_windows_fonts.py
git commit -m "measure(#87): add the codepoint arm to the native Windows probe

#87 asks for the guard's probes on a native Windows host covering family-name
lookup AND codepoint fallback, under both a bare launch and a launch carrying a
fonts key. The script already had the family-name half; this adds the other.

The codepoint is selected at run time from the host's own cmaps: covered by at
least one host family, by NO bundled family, and by NO family on the launch
list. Both halves of that are load-bearing -- a bundled carrier would answer for
the masked launch legitimately, and a listed carrier would make the refusal
meaningless.

Two controls, because a refusal has two boring explanations. The codepoint must
render differently from its own PUA tofu floor in the BARE launch, where no mask
applies; and a second codepoint covered only by an IN-LIST host family must
render identically bare and masked, which is what rules out 'the masked launch
has no working font stack at all'. A run that fails either control reports
unscored, never pass and never fail.

The family-name arms are unchanged and run in the same session against the same
two binaries, so #87 closes on both halves. macOS stays UNMEASURED: there is no
macOS host, and CoreTextFontList::PlatformGlobalFontFallback returns the system
font through FindSystemFontFamily with no gate at all.

Verified: --self-test passes, including the two new control-failure cases.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push origin fix/fonts-round3
```

Append to the ledger: both run labels, both `overall` values, and each `codepoint`
verdict row.

---

### Task 9: Documentation, PR, issue comments

**Files:**
- Modify: `CLAUDE.md` ("Still ungated" paragraph and the ungated-paths list)
- Modify: `docs/superpowers/specs/2026-09-10-fonts-round3-design.md` (Outcome section)
- Modify: `docs/superpowers/plans/2026-09-10-fonts-round3.md` (Outcome section)
- Create: `.superpowers/sdd-fonts3/pr-body.md`, `.superpowers/sdd-fonts3/pr-appendix.md`,
  `.superpowers/sdd-fonts3/comment-{82,87,88,90,91,92,94}.md` (untracked)

**Interfaces:**
- Consumes: every id, sha, count and verdict in `.superpowers/sdd-fonts3/progress.md`,
  `phase0-run1.md`, `gate-b5.md`, `gate-b4.md`, and both probe JSON files.
- Produces: a merged PR.

- [ ] **Step 1: Read the branch back before describing it**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
git log --oneline main..fix/fonts-round3
git diff --stat main...fix/fonts-round3
git rev-parse HEAD
gh run list -w build.yml -R lang315/camoufox -L 6 \
  --json databaseId,headSha,status,conclusion \
  --jq '.[] | "\(.databaseId) \(.headSha[0:7]) \(.status) \(.conclusion)"'
gh run list -w smoke.yml -R lang315/camoufox -L 8 \
  --json databaseId,headSha,status,conclusion \
  --jq '.[] | "\(.databaseId) \(.headSha[0:7]) \(.status) \(.conclusion)"'
```
Every sha, run id and count that goes into the PR body comes from this output, not from
memory (`CLAUDE.md` lesson 6 — two of round 2's three failures of this kind went into
commit messages on a pushed branch).

- [ ] **Step 2: Rewrite `CLAUDE.md`'s "Still ungated" paragraph**

The current paragraph in "Verifying spoofing claims" begins `Still ungated after it:`
and names `gfxFontGroup::GetDefaultFont()`'s shared-list branch, the non-shared
`LookupInFaceNameLists` and `CommonFontFallback` `else` branches, and `LookupLocalFont`
on macOS and Windows. Replace it with what is true **after** this round, and add the
paths this round closed to the list above it. The paragraph must state, in this order:

1. What round 3 closed: the pref-font memo read path (`WhichPrefFontSupportsChar` and
   `AddGenericFonts`, #94); the generic→family map under a per-context list on all three
   platforms (#92); `gfxFontGroup::GetDefaultFont`'s scope and its shared-list walk, plus
   `GetDefaultFontLocked`'s two last resorts (#88); and `FontFaceLoadStatus` for
   non-local faces (#91).
2. What is still ungated: `CoreTextFontList::FindSystemFontFamily`'s ungated return on
   the macOS system-font path; the DWrite non-shared substitution branch, dormant while
   `gfx.e10s.font-list.shared` is true; `LookupLocalFont` on the macOS and Windows
   platform font lists, which a Linux guard cannot see; and the context-0 fail-open,
   which no round has changed.
3. What every last-resort walk now does on empty — return the unfiltered family and log
   `CAMOU-FL default-unfiltered` — and why: a gate that finds nothing must not become a
   release-build null dereference at `gfxTextRun.cpp:2207-2221`.

Add a **lesson 8 only if this round produced one.** Two candidates, and both need the
run that established them quoted beside them: an arm that reads a log kind must be able
to tell "this binary predates the kind" from "the kind exists but not for my context",
because the third state is the difference between a diagnostic and a step failure; and
an entry in a "known unmeasurable" table must name both the run that established the
reason and a signature the arm's own text must carry, or a broken fixture hides inside
the standing excuse. Write neither unless this round's runs actually demonstrate it.

- [ ] **Step 3: Write the Outcome sections**

Append an `# Outcome` section to
`docs/superpowers/specs/2026-09-10-fonts-round3-design.md` and to this plan, each
recording: which tasks ran, which conditionals fired (Task 6, Step 5's B6) and why, every
deviation from the written plan with its reason, the build and smoke ids, and every arm's
final verdict. Round 2's plan has this shape at its end; follow it.

- [ ] **Step 4: Write the PR body and the evidence appendix**

`.superpowers/sdd-fonts3/pr-body.md` must be **under 65,536 bytes** — check with
`wc -c` before opening the PR — and carry one section per issue, each with the RED and
the GREEN that close it:

| Issue | Closes on |
|---|---|
| #94 | arm (n1) RED on `34432908522`'s Phase 0 run — the width-only `PREF PATH LEAK` line, quoted verbatim, since that binary emits no `fontlist` kind and the log half of the verdict does not exist there — GREEN on `<SMOKE_P1>` with `pref-fallback … key=tinos allowed=0` present |
| #92 | arm (n2) RED on Phase 0, GREEN on `<SMOKE_P1>` with `generic-map` naming different families |
| #88 | arm (h3) RED on Phase 0, GREEN on `<SMOKE_P1>` — say which GREEN shape fired: shape A is a `default` line naming an in-list family, shape B is no `default` line for that context together with a `generic-map` line naming one, which is what A2 produces once the group stops falling to the default font at all |
| #91 | arm (n7) RED on Phase 0, GREEN on `<SMOKE_P1>` |
| #82 | arm (n4) GREEN on `<SMOKE_P1>` **plus** the B6 RED; if B6 could not go RED, #82 **stays open** with the reason |
| #90 | the measurement, plus the fix only if arm (n5) was RED |
| #87 | both halves GREEN on the round-3 Windows build — `overall: PASS`, which the probe now withholds unless a **scored** `codepoint` row exists, so an absent half cannot read as a passing one. An `overall: UNSCORED` run closes nothing; quote the `[unscored] … codepoint` row and its reason instead. macOS stated as unmeasured. |

Two sections the PR must carry beyond the per-issue ones:

- **The `FontListManager` consequence.** If arm (n5) went RED, that RED demonstrates the
  same mechanism for the font list this whole round is about: `FontListManager` keeps its
  per-context value in a process-local `nsTHashMap` (`dom/base/FontListManager.cpp:16`)
  with a cross-process disable flag (`:109-111`). Write it into the PR and into #44. It
  is not closed here as a speech bug.
- **NOT verified.** The macOS host is unmeasured, so `CoreTextFontList::FindSystemFontFamily`
  and `LookupLocalFont` on macOS are stated, not tested. The context-0 fail-open is
  unchanged. The `@font-face` path is gated in the shape arm (e) measures, not by a
  scope — `InsertRuleFontFace` still carries no `AutoFontListContext`. The accepted
  offsets on `window-setter-seal.patch` and `system-ui-font-spoofing.patch` go here too.
- **Which fontconfig the guard measured, and which one ships.** The smoke launches with
  the bundle's **Linux** `fonts.conf`, where `sans-serif`/`serif`/`monospace` alias to
  `Arimo`/`Tinos`/`Cousine` — all `lin`-only, all refused under a mac or win per-context
  list, which is what makes A2's table decide every generic in arms (n1), (n2) and (n4).
  A shipped Camoufox picks the conf by the **spoofed** OS
  (`pythonlib/camoufox/utils.py:213-231`), so a mac-fingerprinted session runs with
  `Helvetica`/`Times`/`Menlo` — all mac families, all allowed under a mac list — and
  fontconfig answers its own generics there without A2 being consulted. #92 is still real,
  because the refusal case is reachable whenever the per-context list and the spoofed OS
  disagree, but arm (n2)'s RED is partly an artifact of the conf the guard chose. State it
  next to what the guard proves (CLAUDE.md lesson 3); do not claim the arm covers the
  shipped mac configuration.

The evidence appendix — full smoke arm output, both probe JSON files, the per-kind
counter tables, the `make dir` grep results — goes in a **comment** on the PR from the
start, not in the body.

- [ ] **Step 5: Open the PR**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
wc -c .superpowers/sdd-fonts3/pr-body.md
gh pr create -R lang315/camoufox --base main --head fix/fonts-round3 \
  --title "fonts round 3: pref-font path (#94), per-context generics (#92), default font (#88), real FontFace status (#91)" \
  --body-file .superpowers/sdd-fonts3/pr-body.md
gh pr comment <PR> -R lang315/camoufox --body-file .superpowers/sdd-fonts3/pr-appendix.md
gh pr view <PR> -R lang315/camoufox --json number,url,title --jq '"\(.number) \(.url)"'
```
Expected: `wc -c` under 65536; a PR number and URL read back. The PR body must carry the
closing keywords `Closes #94`, `Closes #92`, `Closes #88`, `Closes #91` and `Closes #87`,
plus `Closes #90` **only if** the measurement or the fix actually closes it, and
`Closes #82` **only if** both the GREEN and the RED exist. An issue whose evidence is
incomplete gets a comment, not a keyword.

- [ ] **Step 6: Comment on each issue**

One comment per issue, each quoting the arm's own output rather than describing it, and
each naming the run it came from. #44 additionally gets the `FontListManager` consequence
if arm (n5) was RED.

```bash
for n in 82 87 88 90 91 92 94; do
  gh issue comment "$n" -R lang315/camoufox --body-file ".superpowers/sdd-fonts3/comment-$n.md"
done
gh issue view 82 -R lang315/camoufox --json comments --jq '.comments[-1].body' | head -20
```
Read at least one comment back to confirm it posted with the text intended.

- [ ] **Step 7: Commit the documentation**

```bash
git add CLAUDE.md docs/superpowers/specs/2026-09-10-fonts-round3-design.md \
        docs/superpowers/plans/2026-09-10-fonts-round3.md
git commit -m "docs: fonts round 3 outcome, and what is still ungated

Rewrites CLAUDE.md's 'Still ungated' paragraph against what this round actually
closed, and records the Outcome of the spec and the plan: which conditionals
fired, every deviation with its reason, and each arm's final verdict with the
run it was read from.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push origin fix/fonts-round3
```

---

## Notes for the implementer

**The three states, again.** More than half of this plan's failure modes come from an arm
that cannot tell "this binary predates the log kind I read" from "the kind exists but not
for my context". Build `34236331658` emits **zero** `CAMOU-FL` lines of any kind —
verified with `git show 8990915:patches/font-list-spoofing.patch | grep -c CAMOU-FL`, which
prints `0` — and `34432908522` emits ten kinds but none of the four this round adds. An
arm that reports SETUP-INVALID on either fails the step for a reason no re-run can change.

**`P0R2_84` will fail, and that is not a signal.** Five arms in `EXPECTED_GREEN` are RED
on the pre-#93 artifact. Read `(n1)` and `(n4)` out of its log and leave the table alone.

**Do not hardcode a context id.** Run 34213805428 happened to use `ctx=6`; the id depends
on how many contexts preceded the arm in that run. Every arm reads it off a log line.

**Balanced hunk context.** GNU `patch` charges the difference between leading and trailing
context against a max-2 fuzz budget, so a hunk with 7 leading and 1 trailing context lines
is rejected even at the exactly correct line of a pristine file. `git apply --check` is not
a valid pre-flight — it accepts hunks GNU patch rejects. This cost round 2 an 80-minute
build.

**`git clean -fdq` after every `make revert`.** `font-list-spoofing.patch` **creates**
`dom/base/FontListManager.{h,cpp}`; a bare reset leaves them as untracked files, the
creation hunks then land on existing files, and `--forward` makes GNU patch skip them
without a word. The "clean" dry-run you would read is not what `make dir` sees.

**Splice, do not copy, when a patch has a header or a non-canonical section order.**
`font-hijacker.patch` has a 38-line prose header; `speech-voices-spoofing.patch` has
sections in an order `git diff` will re-sort. `font-list-spoofing.patch` has neither, so
it takes the regenerated file wholesale after a section-list guard.

**Every commit message and PR line is a claim someone acts on later.** This repo's
feedback loops are 40–95 minutes; reading back a sha, an output tail or a run list takes
seconds. Round 2 put a sha that existed nowhere in the repo into two commit messages on a
pushed branch, and dispatched a duplicate 90-minute build from a misread notification.

---

## Self-review

**1. Spec coverage.** Every requirement in the design maps to a task:

| Spec | Task |
|---|---|
| A1 (#94), pref memo at ctx 0, two-gate read filter, `pref-fallback`, `fontlist` | 3, Steps 2–7 |
| A2 (#88/#92), accessor, helper + table, `FindGenericFamilies`, `AddGenericFonts`, `GetDefaultFontLocked`, `GetDefaultFont`, `generic-map`, `default-unfiltered` | 4, Steps 2–7 |
| A3 (#91), `SetStatus` / `Status()` / `Load()` | 5, Steps 3–5 |
| A4 (#90), conditional `RoverfoxStorageManager` | 6, Steps 2–3 |
| A5 (#82), no new code — measurement and diagnostic only | 2 Step 5, 7 Step 5 |
| B0, `FONTCONFIG_FILE`, triage routing, counters, run 1's named outputs | 1, Steps 2–8; the signature half of the routing lands in 2, Step 1 |
| B1 | 2, Step 2 |
| B2 | 2, Step 3 |
| B3 | 2, Step 4 — both GREEN shapes, quoted from §B3 at `3798c59` |
| B4 | 2, Step 5 |
| B5 | 2, Step 6 |
| B6 | 7, Step 5 |
| B7 | 2, Step 7 |
| B8 | 8, Steps 3–4 |
| C, evidence and closure, PR under 65,536 bytes, appendix as a comment | 9, Steps 4–6 |
| D, out of scope, stated | Global Constraints (context 0) and 9 Step 2 (the rest) |

**2. Placeholder scan.** No `TBD`, no "similar to Task N", no "add error handling". Every
C++ edit shows the code and the surrounding context to place it against. Every command
states its expected output. The values that genuinely cannot be known before a run —
hunk counts, run ids, widths, the B5 and B6 verdicts — are each written as "record" or
"read back from `<command>`", never invented. `<P0R1>`, `<SMOKE_P1>`, `<BUILD_LINUX>`,
`<FIX_SHA>` and `<N>` are placeholders **for values a step produces**, and each has a
step that produces it.

**3. Type and name consistency.** `CamouIsFamilyAllowed` is declared in Task 3 Step 2,
defined in Step 3, and called in Tasks 3 and 4 with the same three-parameter signature
throughout (third parameter defaulted, so §A2's two-argument calls compile).
`CamouGenericCandidate` is declared and defined in Task 4 with `(FontVisibilityProvider*,
StyleGenericFontFamily, nsACString&, nsACString&)` at all three call sites.
`kind_total` and `LOG_START` are defined in Task 1 Step 4; `one_page_list_arg` and
`_ctx_tok` in Task 2 Step 2, and both are used later in the same heredoc by Steps 3–7.
`_ctx_of` and `_file_of` are arm (h3)'s own locals. Arm tags `(n1)`, `(n2)`, `(h3)`,
`(n4)`, `(n5)`, `(n7)` are consistent across the arms, `EXPECTED_RED`, `EXPECTED_GREEN`
and the readback tables. The four log format strings in the "Log line contract" table are
the strings Tasks 3 and 4 emit and the strings Task 2's arms parse, and every parse of a
last-position field (`key=`, `families=`, `family=`, `resolved=`) reads to end of line
rather than to the next space, because family names contain spaces.

Task 8's edits name only symbols that exist in
`build-tester/scripts/probe_windows_fonts.py`: `check(label, cond)` (the closure at
`:695`), `judge`, `_v`, `EPS`, `_names_from_file`, `Path`, and `_canned`'s nested
`run(...)`, whose call sites are all rewritten together because its two new parameters are
positional and required. `cp_status` is a new closure inside `self_test`, defined beside
the cases that use it.

**Log-window reads are pinned three ways.** Every arm that reads `camou_fl` output takes
its reads before any reference launch, filters by the fixture context's `ctx=`, and —
where the spec says "the following line" — by the log file basename and list position too.
`camou_fl` sorts by file name, not by time, so `[-1]` means "last line of the
last-sorting file"; arms (h3) and (n4) each state that in a comment beside the code that
compensates for it.

**Deviations from the spec, each stated where it applies rather than absorbed.** Three:

1. §A2 gives `CamouIsFamilyAllowed` two arguments. `GenerateFontListKey` is **protected**
   (`gfxPlatformFontList.h:1002`, under the `protected:` at `:777`), so `gfxTextRun.cpp`
   cannot lowercase a key the way in-class callers do. The accessor takes a defaulted
   third parameter that hands the lowercased key back, so §A2's two-argument calls compile
   unchanged. Stated in Task 3's Interfaces block.
2. §A2's `generic-map` bullet asks for the line on **every** context-scoped generic
   resolution. `GetDefaultFontLocked` originally logged only when the helper answered;
   it now logs the decline too, which is why Task 4's readback expects four `generic-map`
   emit lines in `gfxPlatformFontList.cpp` rather than three.
3. The candidate rows are `nullptr`-terminated rather than sized with `std::size`, which
   lives in `<iterator>` and is not included by `gfxPlatformFontList.cpp` (its only
   standard include is `<numeric>`). No new include, same semantics. Stated in Task 4
   Step 3.

**No longer a deviation.** Arm (h3)'s two GREEN shapes were written here first, as a
consequence of A2 removing the `CAMOU-FL default` observable that §B3 originally made the
whole verdict. Spec commit `3798c59` adopts them, including the "shape (ii) only when
`generic-map` lines exist in the run" condition that `kind_total("generic-map")`
implements, so Task 2 Step 4 now quotes §B3 rather than departing from it. The same commit
pins the Linux `fonts.conf`, adds the `Tinos`/`Arimo`/`Cousine` assertion and writes the
guard's blind spot into §B0; Task 1 Steps 2–3 and Task 9 Step 4 already carried all three.

**Resolved in the spec while this plan was being written.** Two, neither requiring a plan
change beyond the pin:

- `919096e` — §A2's last bullet gave `generic-map` without the `step=` field its own
  helper bullet requires, the one format the spec review flagged to reconcile at
  patch-writing time. It is now `CAMOU-FL generic-map ctx=%u generic=%d step=%s key=%s`,
  the string this plan's "Log line contract" already carried, so all six emit sites in
  Task 4 and the parser in Task 2 Step 3 agree with the spec as written.
- `3798c59` — §B3's two GREEN shapes and §B0's pinned Linux conf, `Tinos`/`Arimo`/
  `Cousine` assertion and stated blind spot, all of which this plan had already
  implemented in response to the plan review. Both passages are now quoted verbatim at
  their implementation sites (Task 1 Step 3, Task 2 Step 4).

---

## Outcome

Written after the work landed, against `fix/fonts-round3` at `df0bdad` — the last
commit of the measurement work, the 37th above `main` at `c8c42ef`, 6 files
changed, 9,350 insertions and 207 deletions. The commit carrying this section is
the one after it. Where this section and the plan above disagree, this section is
what happened.

### Which tasks ran

| task | state | commits |
|---|---|---|
| 1 — B0 launch, triage, counters, Phase 0 run 1 | complete | `b167dea` … `749eb62` |
| 2 — six RED-first arms | complete | `2227cd0` … `3a65e60` |
| 3 — A1 (#94) | complete | `9421a93` |
| 4 — A2 (#88, #92) | complete | `9d0f3b8` |
| 5 — A3 (#91) | complete | `261b9fd` |
| 6 — A4 (#90) | **SKIPPED** | — |
| 7 — builds, smoke, B6 | complete | `c7b1ff1`, `9465029`, `25a04b8`, `b09c695` |
| 8 — B8 Windows (#87) | complete | `df0bdad` |
| 9 — docs, PR, issue comments | this section | — |

**Task 6 was skipped because GATE: B5 came back GREEN.** Run 34513429414 read a
13,362-voice `espeak-ng` registry, split it into two disjoint halves of 6,681, and
each context read roughly 6,480 names all from its own half and none from the
other's. The plan makes A4 conditional on B5 going RED; it did not, so #90 closes on
the measurement with no code change. The gate verdict is recorded in
`.superpowers/sdd-fonts3/gate-b5.md`, which is read by matching the anchored pattern
`^GATE:` — an earlier version of that file said an unanchored grep was safe, which
was false because the file discusses all three outcomes.

**Step 5's B6 fired.** The trigger was resolved YES in
`.superpowers/sdd-fonts3/gate-b4-phase0.md`: on both pre-fix binaries the donor
reached the U+FFFD carrier through `mFonts` at exit 4 and `SystemFindFontForChar`
was never taken, so neither could supply #82's RED. The diagnostic build
34534150529 at `c7b1ff1` drops exactly one statement, the RED reproduced on run
34544937587, and `9465029` reverts it exactly (`git diff 261b9fd 9465029` is empty
over the whole tree).

### Final run ids

| run | workflow | head sha | conclusion | role |
|---|---|---|---|---|
| 34432908522 | Build and Release | `163ee25` | success | the Phase 0 Linux binary, a verified stand-in for `main` |
| 34496121342 | Smoke Fingerprint | `749eb62` | success | Task 1's green Phase 0 run |
| 34513429414 | Smoke Fingerprint | `f0aeb0d` | success | GATE: B5 GREEN |
| 34519345704 | Smoke Fingerprint | `3a65e60` | success | **authoritative Phase 0**, 24/24 |
| 34531660206 | Build and Release | `261b9fd` | success | BUILD_LINUX |
| 34531671179 | Build and Release | `261b9fd` | success | BUILD_WINDOWS, never smoked |
| 34534150529 | Build and Release | `c7b1ff1` | success | BUILD_B6, the diagnostic |
| 34538378696 | Smoke Fingerprint | `25a04b8` | failure | first Phase 1 attempt |
| 34543794646 | Smoke Fingerprint | `25a04b8` | failure | first B6 attempt |
| 34544934746 | Smoke Fingerprint | `b09c695` | **success** | **SMOKE_P1**, on build 34531660206 |
| 34544937587 | Smoke Fingerprint | `b09c695` | failure, by design | **SMOKE_B6**, on build 34534150529 |
| 34450188525 | Build and Release | `c8c42ef` | success | the #87 Windows baseline |

Every id read back with `gh run view <id> --json status,conclusion,headSha`. Which
build each smoke consumed was read from the `gh run download` argument inside that
smoke's own log, because `gh run view` does not expose the `run_id` input.

### Final arm verdicts, run 34544934746

Zero setup-invalid, zero unexpected red. `(b)`, `(b2)`, `(b2r)`, `(e)`, `(g)`,
`(h)`, `(h3)`, `(i)`, `(i2)`, `(j)`, `(k)`, `(n1)`, `(n2)`, `(n4)`, `(n5)` and
`(n7)` all GREEN; `(f)` and `(j2)` RED and absorbed by `KNOWN_UNMEASURABLE` with
their signatures matched rather than by a bare tag. Counters: `fontlist` 3715,
`generic-map` 101, `pref-fallback` 545, `default-unfiltered` 0, `default` 0, over
30,065 CAMOU-FL lines.

### Deviations from the plan

**Phase 0 took ten dispatches to re-baseline, nine of them superseded, and four
arms changed shape.** The plan budgets one. Confining the launch to the bundle with `FONTCONFIG_FILE` removed
DejaVu from the font universe, and four arms had been resting on it:

- Arm (a) and arm (b) both hit a width-reference collision on MS Gothic once the
  fallback face changed. Rule unified in a `collided_families()` helper
  (`5b22523`, `aa67f7b`, `20085b1`, `c0ced3c`).
- Arm (b)'s third macOS-only probe family is now **chosen at runtime** from Optima,
  Palatino and Helvetica by a width-and-pixel precheck, because Geneva turned out
  never to render. The run picked Optima. Issue #95 was filed for Geneva and is not
  closed by this round (`f0d8ace`).
- Arm (f) moved its probe codepoint from U+6F22 to U+FF71, which fixed its
  bisection but not its discriminator; it remains known-unmeasurable by advance,
  with U+FFE8 recorded as the candidate fixture for a later round.
- Arms (i) and (i2) moved from "broken setup" to a verdict, and produced the
  round's sharpest Phase 0 finding: a context whose list refuses every CJK family
  was being served U+FF71 by Microsoft YaHei, named by per-family rasterisation
  after advance alone could not tell five candidates apart (`11f39c2`, `a79ba89`,
  `042e44d`).

**Four other fixtures were wrong and were fixed against a run rather than argued**
(`2ac18e4`, `03bf4fb`, `85c3700`, `372792b`): (n1)'s tofu-floor description, (n2)'s
same-kind reference families, (n4)'s carrier (Menlo collides with the floor at 43,
swapped for Lucida Grande), and (n7)'s bare `await` on `f.loaded`, which raced a
5-second timer.

**Two controls died of the fixes being correct, and both were repaired in
`b09c695`** against real failing runs rather than synthetic ones. Arm (h)'s Windows
positive control: with #92 fixed the win `sans-serif` *is* Segoe UI, so advance and
pixels cannot separate "resolved the face-name lookup" from "fell back to that
generic"; the verdict moved to the `CAMOU-FL facename … allowed=0/1` log line,
attributed by `set n=` (574 families against 107) rather than by the answer. Arm
(n4)'s donor pick: with the refusal dropped the victim's own `sys-fallback` line
also names the carrier, so `[-1]` collapsed donor and victim onto one context;
changed to `[0]`, with the same-context refusal kept and still reachable. That
second failure was predicted in writing, from the arm's own source, before the run
landed.

**Four defects in the task briefs were corrected by the implementers rather than
inherited.** Each is recorded here because sibling briefs carry the same shapes:

1. **The per-section `awk` guard was vacuous.** `s="diff --git a/$sec"` never
   matches a real `diff --git a/X b/X` line. Fixed to include `" b/$sec"`, then
   proven both live (9 sections, 14–133 lines each, identical) and discriminating
   (3 gfx sections, 33–115 changed lines).
2. **The briefs' "no fuzz or offset on any gfx/thebes file" commit line was
   false** of the whole stack, which carries 216 fuzz-or-offset lines over 46
   patches. Replaced with the measured truth. Against the pre-round-3 baseline
   **exactly one line changes**: `system-ui-font-spoofing.patch`'s single hunk moves
   from `offset 281` to `offset 407`, the net lines this round adds above its
   pristine anchor at 2245. `font-hijacker.patch`'s six lines and
   `window-setter-seal.patch`'s fourteen are byte-identical before and after, and
   the two edited patches apply at zero fuzz and zero offset on their own hunks.
3. **Task 7 Step 4's `default-unfiltered` expectation was backwards.** The brief
   said all four new kinds must be non-zero. All three emit sites sit on the
   fail-open tail, so **zero is the healthy value** and non-zero is a finding. The
   correction was written against the applied tree before the run, and the run read
   zero.
4. **Task 8's `choose_codepoint` selects nothing on any host.**
   `bundle/fonts/macos/LastResort.otf` declares family `.LastResort` with a
   format-13 cmap covering all 1,114,112 codepoints, and the brief unioned it into
   the exclusion set. Fixed by applying the brief's own dot-prefix skip to both
   loops, which takes the candidate count from 0 to 10. The brief's rule was run
   verbatim first and the resulting `overall: UNSCORED` / `NOT RUN` artifact kept as
   evidence.

**One regeneration artifact, proven equivalent rather than explained away.**
Rewriting `font-list-spoofing.patch` moved an untouched hunk header from
`-1851,15` to `-1851,14` — a Myers realignment over a run of braces, not a
correction of an off-by-one. Proven by applying the old and the new section to
separate copies of `first-checkpoint` and confirming the new-applied file is
byte-identical to the live edited one.

**One prediction was falsified and is kept rather than dropped.** Arm (j) was
expected RED on the diagnostic build, on the theory that its own GREEN rested on
the same refusal. It stayed GREEN, and `phase1-readback.md` §A2a had recorded
before the run that a (j) which stays GREEN means the standing note about (j)
needs revisiting. Read off the run: (j)'s donor settles U+FFFD at Tahoma's 47, a
family in its own list that resolves through `mFonts`, so system fallback is never
taken; the arm's window carries `['ctx=7 resolved=none']` and no `fffd-cache`
line, and the run's single `fffd-cache` line is in (n4)'s content process.
**(j) does not read this cache on this bundle**, so its verdict is not evidence
about the gate either way. The mechanism the prediction assumed was not
identified.

### Carried out of this round

- **The third triage state for diagnostic-branch arms was never implemented.** An
  arm that reaches its diagnostic branch still prints a row the triage table renders
  as an ordinary green. Arm (n4)'s Phase 0 row is the live example; its
  `EXPECTED_RED` entry carries an explicit caveat instead.
- **`system-ui` is unmeasured.** `generic=7` appears zero times in the 5.2 MB
  `camou-fl.txt` of run 34544934746. Task 4's carried concern — whether the
  sans-serif row answers instead of the system-ui spoof for a context with a list,
  and whether Linux emits two `generic-map` lines for it — needs a fixture that asks
  for `system-ui`.
- **Arm (f) is still unmeasurable by advance**; U+FFE8 or a pixel discriminator is
  the way forward.
- **Arm (j2) is still unmeasurable**, so #82 rests on (n4) alone.
- **The Windows build 34531671179 was never smoked**, and macOS was never measured.
- Task 8 carried two minors: font file handles are never closed through the bundle
  walks, and the artifact SHA corroboration lives only in the probe JSONs.

