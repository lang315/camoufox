# Fix plan: macOS-arm64 CI build

## Latest failure (run 25784512151, sha 03a5aa1b)

Step: `Build` (compile leg, 66min into mach build).

19 errors in upstream Firefox source `dom/webauthn/MacOSWebAuthnService.mm`:

```
error: unknown type name 'ASAuthorizationPublicKeyCredentialPRFAssertionInputValues';
       did you mean 'ASAuthorizationPublicKeyCredentialLargeBlobAssertionInput'?
error: property 'prf' not found on object of type 'ASAuthorizationPlatformPublicKeyCredentialRegistration *'
error: use of undeclared identifier 'ASAuthorizationPublicKeyCredentialPRFRegistrationInput'
...
fatal error: too many errors emitted, stopping now [-ferror-limit=]
```

## Root cause

Firefox 146 calls Apple WebAuthn **PRF (Pseudo-Random Function) extension** APIs
introduced in **macOS 15 / iOS 18 / Xcode 16 SDK**. Symbols required:

- `ASAuthorizationPublicKeyCredentialPRFAssertionInputValues`
- `ASAuthorizationPublicKeyCredentialPRFRegistrationInput`
- `.prf` property on `ASAuthorizationPlatformPublicKeyCredentialRegistration`
- `.prf` property on `ASAuthorizationPlatformPublicKeyCredentialAssertion`
- `.prf` property on `ASAuthorizationPlatformPublicKeyCredentialRegistrationRequest`

All gated behind `@available(macOS 15.0, *)` in Apple's `AuthenticationServices` framework.

Runner SDK matrix:

| Runner    | Xcode | SDK    | Has PRF API |
|-----------|-------|--------|-------------|
| macos-13  | 15.2  | 14.2   | no          |
| macos-14  | 15.4  | 14.5   | no          |
| macos-15  | 16.x  | 15.x   | yes         |

Current workflow `runs-on:` pins `macos-14` for arm64 → SDK 14.5 missing the symbols.

**Not a Camoufox patch issue.** No patch touches `MacOSWebAuthnService.mm`; the file is
verbatim upstream Mozilla. The build that succeeded for Linux/Windows skipped this TU
because it is `OS_TARGET=='Darwin'`-gated in `dom/webauthn/moz.build`.

## Fix

Single change: switch the arm64 leg of the matrix to **macos-15**.

```yaml
# .github/workflows/build.yml
runs-on: ${{ matrix.target == 'macos'
             && (matrix.arch == 'arm64' && 'macos-15' || 'macos-13')
             || 'ubuntu-24.04' }}
```

Already committed at sha `06824...`; not yet dispatched.

Why macos-15 over alternatives:

- **Patching MacOSWebAuthnService.mm** to gate PRF behind a runtime `@available` check
  works but mutates upstream Mozilla code for no security/automation reason.
- **`--disable-webauthn`** in mozconfig disables the whole WebAuthn DOM API surface;
  hurts Camoufox parity with regular Firefox.
- **macos-26 / future runner** does not exist yet on hosted GitHub Actions.

`macos-15` is GA on GitHub-hosted runners; no opt-in required.

## Verification

```bash
gh workflow run "Build and Release" --ref main -f build_target=macos-arm64
# wait ~90min
gh run list --workflow="Build and Release" --limit 1
# expect: conclusion=success, artifact CamoufoxBuilds-macos-arm64 uploaded
```

## Remaining risk (post-fix)

If macos-15 dispatch still fails, suspect order of fall-through issues:

1. **Newer Xcode 16 default clang ≥17** — likely OK, satisfies Mozilla check, but our
   workflow still installs `brew llvm@17` and exports `MOZ_LLVM_PREFIX`. Brew prefix may
   be unused / redundant on macos-15; harmless.
2. **Brew bottle availability for `llvm@17` on macos-15** — usually fine; brew autobuilds
   if no bottle.
3. **rustup interaction** — if rust 1.95 too new for Mozilla, downgrade via
   `rustup install 1.84` + `default 1.84`.
4. **Compile-time disk pressure** — macos-15 has ~14GB free; current build needs ~10GB.
   Tight but should fit.
5. **Other macOS 15-only symbol mismatches** — if Firefox 146 references SDK 15-only
   APIs beyond PRF, those would now compile; if it references **SDK 16-only** APIs we'd
   need macos-26 (not available). Probability low.

If any of #1-#5 hits, apply targeted fix and re-dispatch. Do not preemptively change
configuration: each speculative change adds blast radius.

## Out of scope

- macOS x86_64 (Intel) leg — Apple deprecated Intel SDKs at macOS 15; macos-13 still
  works for arm64-via-Rosetta but not for native Intel. Address separately if user wants
  Intel artifacts.
- Cross-compile from Linux back to macOS — abandoned earlier in the session because
  Mozilla CDN returns 403 for SDK fetch from non-Mozilla CI.
