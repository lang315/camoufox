# `scripts/rehearse-patch.sh`

Dry-runs a single patch from `patches/` against a **real, freshly-fetched
Firefox 152.0.4 tree** (not the local `camoufox-*/` working copy), so a
patch can be verified for correctness *before* `make dir` / `scripts/patch.py`
ever touches it. Applying against actual upstream source — rather than
against whatever partially-patched state happens to be on disk locally —
is what makes the rehearsal trustworthy: it catches drift against the
pinned FF152 release, not just drift against a stale local checkout.

## Usage

```bash
FETCH="curl -fsSL" scripts/rehearse-patch.sh <patch-basename>
```

`<patch-basename>` is the filename of a patch under `patches/` (searched
recursively, so patches under `patches/playwright/`, `patches/librewolf/`,
etc. are found by basename alone — e.g. `css-media-spoofing.patch`).

The script:

1. Parses the target patch's diff headers to find every file it **edits**
   (`--- a/...` paired with `+++ b/...`) and every file it **creates**
   (`--- /dev/null` paired with `+++ b/...`).
2. Walks `patches/**/*.patch` in sort order up to (not including) the
   target patch, and treats any earlier patch that touches one of the
   target's edited files as a **prerequisite** — it must be applied first
   so the target patch sees the tree in the state it actually expects,
   not pristine upstream.
3. Fetches every edited file (target's + prerequisites') from
   `hg.mozilla.org` at tag `FIREFOX_152_0_4_RELEASE` into a scratch tree
   at `.rehearse/<patch>/tree`. Files the target patch *creates* are
   skipped (they don't exist upstream by definition).
4. Applies prerequisites (best-effort, errors ignored — they're only
   there to put the tree in the right shape) then applies the target
   patch for real with `gpatch -p1 --forward -l --binary`, capturing
   `rc` and full output.
5. Parses the apply output plus the resulting tree for five signals and
   prints one summary line + exits 0 only if **all five** are clean.

Left behind on both success and failure: `.rehearse/<patch>/tree` (the
applied — or partially-applied — tree) and `.rehearse/<patch>/apply.out`
(raw patch-tool output), for inspection. The script does not clean these
up; a subsequent run for the same patch removes and recreates them
(`rm -rf "$WORK"` at the top).

## The gate

```
rejects==0 AND skipped==0 AND wrongpath==0 AND fuzz==0 AND max|offset|<=2
```

All five conditions must hold for the script to exit 0. Each one exists
because it catches a *different* failure mode that the others miss:

- **`rejects==0`** — no `.rej` files were left in the tree. A `.rej` file
  means `gpatch` could not apply a hunk at all and saved the rejected
  hunk to the side. This is the baseline "did it even apply" check, but
  it is not sufficient on its own (see `skipped` below).

- **`skipped==0`** — no `can't find file`, `ignored`, or `Skipping`
  message in the patch tool's output. This exists because **`patch.py`'s
  own return-code is not trustworthy** for detecting this class of
  failure: a patch tool can decide a hunk/file is unpatchable, print a
  skip/ignore message, and still exit 0 (or the caller's wrapper — e.g.
  `scripts/patch.py` — can mask the real per-hunk outcome behind an
  aggregate success). Grepping the tool's own diagnostic text is the only
  way to catch that class of silent partial-apply.

- **`wrongpath==0`** — none of the files the *target patch itself* edits
  came back `404` from the upstream fetch. This is the r3 addition: a
  `404` on a file the patch declares as an edit target means the patch
  references a path that does not exist in FF152 at all — a "B1-class"
  wrong-path bug (patch was written against a different Firefox
  layout/version, or the path was mistyped, or the file moved/was
  renamed upstream). This is deliberately **distinct from a network
  error**: a `404` on a *prerequisite-only* file (needed only to stage
  an earlier patch, not edited by the target patch) is not counted here,
  and any non-200/non-404 response (real network failure, auth issue,
  etc.) is treated as fatal (`exit 4`) rather than folded into this
  counter — conflating "target names a dead path" with "the network
  hiccuped" would make the gate useless for catching the former.

- **`fuzz==0`** — no hunk applied "with fuzz N" (N > 0). Fuzz means
  `gpatch` had to relax context-line matching to make a hunk fit. A
  fuzzy match can land a hunk in a plausible-looking but wrong location,
  silently corrupting the resulting source — it is exactly the kind of
  "technically applied, semantically wrong" outcome that a bare exit
  code or `rejects==0` check cannot see.

- **`max|offset|<=2`** — the largest absolute line-offset any hunk
  shifted from its recorded position is at most 2. This exists because
  **`fuzz==0` is not the same as "applied at the correct location."** A
  hunk can apply with zero fuzz (context matched exactly) yet still slide
  many lines away from where it was recorded, if identical context
  happens to repeat elsewhere in the file. A small offset (±2 lines) is
  normal churn from unrelated nearby edits upstream; a large offset is a
  signal the hunk likely landed against a *different, coincidentally
  similar* block of code than the one it was meant for.

Together these five catch: total failure (`rejects`), silently-partial
failure (`skipped`), wrong-target failure (`wrongpath`), silently-relaxed
matching (`fuzz`), and silently-mislocated-but-exact matching (`offset`) —
each a distinct way a patch can "apply" without actually doing what it's
supposed to.

## Floor requirements

The script hard-fails fast (before doing any work) if any of these are
missing, rather than producing a confusing downstream error:

- **`gpatch`** (GNU patch) must be on `PATH`. Required specifically
  because `gpatch` supports `--binary` and consistent `--fuzz`/offset
  reporting across platforms; BSD/macOS's stock `patch` does not behave
  identically. Install via Homebrew (`brew install gpatch`) on macOS.
- **bash ≥ 4** — the script uses `mapfile` and associative arrays
  (`declare -A`), both bash-4+ features. macOS ships bash 3.2 by
  default; install a newer bash via Homebrew and invoke the script with
  it explicitly if `/usr/bin/env bash` still resolves to the system one.
- **`FETCH` must be set** — the script has no built-in fetcher; the
  caller supplies the exact command (typically
  `FETCH="curl -fsSL"`). This keeps the script portable across
  environments with different `curl`/`wget`/proxy setups and makes the
  fetch command auditable at the call site rather than hardcoded.
  `$FETCH` is invoked as `$FETCH -w '%{http_code}' -o <file> <url>`, so
  whatever `FETCH` expands to must accept trailing `-w`/`-o` flags the
  way `curl` does.

## Known environment constraint (sandboxed hosts)

Some sandboxed execution environments restrict outbound network access to
an allowlist of hosts that does not include `hg.mozilla.org`. On such a
host this script cannot succeed past the fetch step — every fetch will
fail with a non-200/non-404 response, and the script exits 4
(`FETCH FAIL ...`) rather than silently misreporting. This is expected
and is not a bug in the script; run it on a host with unrestricted (or
`hg.mozilla.org`-allowlisted) egress instead.

**Status of the Step-3 smoke test in this environment:** the smoke test
(`FETCH="curl -fsSL" bash scripts/rehearse-patch.sh css-media-spoofing.patch`,
expected `rc=0 rejects=0 skipped=0 wrongpath=0 fuzz=0 max|offset|=0`) is
**deferred** — it could not be run in the sandbox this script was authored
in, because that sandbox's network allowlist excludes `hg.mozilla.org`.
What *was* verified in that environment: `bash -n scripts/rehearse-patch.sh`
(syntax check) passes with exit 0. The smoke test itself is expected to
run during Tasks 7/8, on a host with real egress to `hg.mozilla.org`.
