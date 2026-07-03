# Plan: fix the cross-OS font-metric leak on Windows

## Symptom

Driving the **Windows** `camoufox.exe` while spoofing **macOS** (`CF_OS=macos`)
passes almost everything — UA, navigator, WebGL (Apple M1), device, screen,
IPhey "Trustworthy" — but **CreepJS reports `platform hints: Segoe UI:Windows`**,
revealing the real Windows host. Same class of leak would apply to Linux spoof
on Windows, or any spoof whose OS ≠ the host running the binary.

## Root cause (proven)

Font-presence probe on the Windows binary:

| spoof | segoe_ui present | helvetica present | calibri present | times present |
|---|---|---|---|---|
| `CF_OS=windows` | **true** | true | true | true |
| `CF_OS=macos` | **false** | **false** | false | true |

Two facts fall out:

1. The font **allowlist works** — under macOS spoof, `Segoe UI` and `Calibri`
   (Windows fonts) are correctly hidden from enumeration
   (`FontListManager::IsFontAllowed`, `patches/font-list-spoofing.patch`).
2. But the spoofed-OS font is **also absent**: `Helvetica` (a macOS UI font)
   `present=false`. `Times New Roman` stays `true` only because it exists on the
   Windows host *and* is allowlisted for macOS.

Why: the Windows build **ships** the macOS fonts (`app/fonts/` = 441 files — Al
Nile, AlBayan, AmericanTypewriter, Apple Braille, …) but **never registers them
with the DirectWrite font backend**. `scripts/package.py` only *copies* the
files into `fonts/` ("Non-linux systems … we walk the fonts/ directory and copy
all files"). On **Linux**, the shipped `fontconfig/` config points Firefox at
`fonts/` so the bundled fonts load. On **Windows** there is **no `fontconfig/`**
and no DirectWrite equivalent wired up, so the bundled fonts sit on disk unused.

Consequence chain:
- `system-ui-font-spoofing.patch` maps `MacIntel → "Helvetica"`.
- Under macOS spoof, `Helvetica` is not loaded (bundle not registered) and the
  Windows host has no Helvetica.
- So `system-ui` / default-sans text **falls back to the real Windows UI font**
  (Segoe UI) and renders with **Segoe UI metrics**.
- CreepJS measures the rendered metrics of the default/system UI font, matches
  the Segoe UI signature → `Segoe UI:Windows`.

The allowlist can hide Windows font **names**, but it cannot supply macOS font
**metrics** when the macOS font files are not loaded into the backend.

## Fix options

### A. Match spoof-OS to host binary (operational, zero code) — recommended default
Run the binary whose OS matches the target: Windows binary → spoof Windows
(fully coherent, proven — `Segoe UI:Windows` is *correct* there); for a macOS
target run the **macOS** binary on a macOS host; Linux → Linux. The host's own
fonts then supply correct metrics and nothing has to be loaded. This is
Camoufox's intended deployment model and needs no rebuild.

### B. Load the bundled fonts into the Windows font backend (the real fix)
Make the Windows build register `app/fonts/` with DirectWrite at startup so the
spoofed-OS fonts are actually renderable, then let the allowlist scope them to
the spoofed OS. After this, `Helvetica` renders with macOS metrics and CreepJS
no longer sees the Windows host.

Implementation:
1. Confirm which loader path Firefox/Windows already has for app-bundled fonts
   (`gfx/thebes/gfxDWriteFontList.cpp` — check for an app-fonts / custom
   `IDWriteFontCollection` path; Firefox has bundled-font support on some
   platforms but desktop Windows may not scan `app/fonts/`).
2. Add a bundled-font loader on Windows: build a DirectWrite custom font
   collection (or `AddFontResourceEx` + `GetSystemFontCollection` refresh) from
   the files in `<app>/fonts/` at font-list init, mirroring what `fontconfig`
   does on Linux. Gate it so only the **spoofed-OS** subset is registered (or
   register all bundled fonts and rely on `IsFontAllowed` to expose only the
   config `fonts` list — simpler, and the allowlist already filters).
3. Ensure `system-ui-font-spoofing.patch`'s target family (`Helvetica` for Mac)
   is present in the bundled set and allowlisted, so system-ui resolves to a
   real, correctly-metric'd font.
4. Do the same audit for the **macOS** build spoofing Windows/Linux (host = Mac,
   symmetric leak): are Windows/Linux fonts bundled + loaded there?

Scope: one C++ patch under `patches/` touching `gfxDWriteFontList.cpp` (+ maybe a
shared bundled-font helper), then a Windows rebuild via CI (the
`--disable-launcher-process` build path already works).

### C. Metric-substitute UI fonts (lighter, approximate)
If bundling/loading the full macOS font set on Windows is too heavy, register a
small set of metric-compatible substitutes for the spoofed-OS **UI** fonts
(e.g. a Helvetica-metric face) so `system-ui` and default sans render with the
target metrics. Cheaper, but only fixes the fonts you substitute — deep font
enumeration can still find gaps. Prefer B if we rebuild anyway.

## Verification

1. Font-presence probe (already written, `example/fontprobe` pattern):
   after the fix, `CF_OS=macos` on the Windows binary should give
   `helvetica_present=true` and `segoe_ui_present=false`.
2. CreepJS Mac-spoof on the Windows binary: `platform hints` must **not** be
   `Segoe UI:Windows` — expect a macOS UI font (Helvetica/`.AppleSystemUIFont`)
   or no Windows-specific hint.
3. Re-run `example/deepcheck CF_OS=macos` on the Windows binary; confirm CreepJS
   + BrowserLeaks fonts stay coherent and IPhey stays Trustworthy.
4. Symmetric check on the macOS binary spoofing Windows/Linux.

## Recommendation

Ship **A** as the documented deployment guidance immediately (match binary/host
to target OS — it is leak-free today). Pursue **B** as the durable fix so a
single binary can spoof any OS without the font-metric leak; it is one gfx patch
plus a rebuild, and the verification is already scripted. Treat **C** as a
fallback only if B's font-loading proves impractical on Windows.

## Update — confirmed diagnosis + applied fix

Confirmed by experiment (no rebuild): installing the bundled Mac marker fonts
(`HelveticaNeue.ttc`, `PingFang.ttc`, `LucidaGrande.ttc`) into the Windows host
made them renderable — `helveticaNeue`/`pingfang`/`lucida` flipped from absent to
present. Proves the fonts are fine; they simply were **not loaded** by the
browser. `about:buildconfig` shows `--enable-bundled-fonts` was never explicitly
passed; the build relied on the WINNT default, which the cross-compile evidently
did not apply (bundled fonts absent in-browser before the manual install).

Fix applied: `assets/windows.mozconfig` now passes `ac_add_options
--enable-bundled-fonts` explicitly. This turns `MOZ_BUNDLED_FONTS` on for the
cross-compiled Windows build so the existing loader (already present in
`gfxDWriteFontList`, gated by `#ifdef MOZ_BUNDLED_FONTS`) registers `app/fonts/`.
Combined with the already-set `gfx.bundled-fonts.activate=1` pref and the shipped
font files, the spoofed-OS fonts should render with correct metrics.

Caveat to verify after rebuild: Windows `FontSubstitutes` maps `Helvetica`→`Arial`
at the GDI layer, and `system-ui-font-spoofing.patch` targets `"Helvetica"` for
Mac. If the bundled Helvetica still loses to the substitution, `system-ui` (and
CreepJS's platform-hint metric) may still fall back. Verification must check
`platform hints` specifically, not just font presence — if it still leaks, the
follow-up is to make the bundled font win over the substitute (or point the
system-ui spoof at a bundled family that has no Windows substitute).
