# Patch Dependencies

Quick reference for the shared infrastructure patches build on. `scripts/patch.py`
applies every `patches/**/*.patch` in order of file name, so the
`playwright/0-*` and `playwright/1-*` patches go first and the rest follow
alphabetically. Each patch is generated against a tree with every earlier one
applied, and many hunks use an earlier patch's lines as context, so they apply
only in that order. The dependencies below are the ones a patch needs to
compile.

## camoucfg (MaskConfig)

`additions/camoucfg/MaskConfig.hpp` reads the spoofing config (`CAMOU_CONFIG` /
`camoufox.cfg`) through `MaskConfig::GetBool()`, `GetString()`, `GetUint32()`
and friends. `GetBool()` is false for an unset key; `GetOptionalBool()` is for
the rare caller that must tell unset from false. `SpoofedOSFor()` is the one
reading of a `navigator.platform` as an OS. `GetSpoofedOS()` is the launch's,
for process-wide decisions only (`font-hijacker.patch`'s bundled fonts, the
WebRTC host socket's port range in `webrtc-ip-spoofing.patch`); anything a page
can observe asks `NavigatorManager::GetSpoofedOS()` (`navigator-spoofing.patch`)
for its own context's OS, which is that context's `navigator.platform` when it
set one and the launch's otherwise.
`scripts/copy-additions.sh` copies it into the source tree before any patch
applies. A patch that calls MaskConfig from a directory whose `moz.build` does
not already see `/camoucfg` must add `LOCAL_INCLUDES += ["/camoucfg"]` itself.

Config keys are declared in `settings/properties.json`; a key a patch reads must
be listed there.

### Patches that read config

| Patch | Config keys |
|-------|-------------|
| `audio-context-spoofing.patch` | `AudioContext:sampleRate`, `AudioContext:outputLatency`, `AudioContext:maxChannelCount` |
| `canvas-spoofing.patch` | `canvas:seed`, `canvas:noiseDensity`, `canvas:noiseStrength` |
| `chromeutil.patch` | `debug` |
| `css-media-spoofing.patch` | `cssMedia:colorGamut`, `cssMedia:prefersColorScheme`, `cssMedia:dynamicRange` |
| `fingerprint-injection.patch` | `navigator.*`, `screen.*`, `window.*` |
| `font-hijacker.patch` | `fonts`, `navigator.platform` |
| `font-other-names-sync.patch` | `font-list-spoofing.patch` for `gfxPlatformFontList::CamouGenericTableApplies()` |
| `font-system-fonts-css2.patch` | `navigator.platform`, `window.devicePixelRatio` |
| `force-default-pointer.patch` | `navigator.maxTouchPoints` |
| `geolocation-spoofing.patch` | `geolocation:*` |
| `locale-spoofing.patch` | `locale:*`, `navigator.language` |
| `media-codec-spoofing.patch` | `media:spoof_codecs` (bypasses `PDMFactory::Supports()` in `MP4Decoder`/`MatroskaDecoder` so `canPlayType()`/`isTypeSupported()` don't leak system codec libraries), `mediaCapabilities:canPlayType`, `mediaCapabilities:decodingInfo` |
| `media-device-spoofing.patch` | `mediaDevices:*` |
| `navigator-spoofing.patch` | `navigator.*` |
| `network-patches.patch` | `headers.*`, `navigator.userAgent` |
| `no-css-animations.patch` | `instantAnimations` |
| `screen-orientation-spoofing.patch` | `screen:orientation`, `screen:orientationAngle` |
| `screen-spoofing.patch` | `screen.*` |
| `system-ui-font-spoofing.patch` | `navigator.platform` |
| `timezone-spoofing.patch` | `timezone` |
| `touchscreen-fingerprint-spoofing.patch` | `navigator.maxTouchPoints` |
| `voice-spoofing.patch` | `voices`, `voices:blockIfNotDefined` |
| `webgl-spoofing.patch` | `webGl:*`, `webGl2:*` |
| `webrtc-ip-spoofing.patch` | `navigator.platform` (the host socket's port range). The per-context addresses are `webrtc_ipv4_<ctx>` and `webrtc_ipv6_<ctx>` in `RoverfoxStorageManager`, set by `setWebRTCIPv4`/`setWebRTCIPv6` |
| `webrtc-ip-spoofing2.patch` | `webrtc:localipv4`, `webrtc:localipv6` |
| `webrtc-launch-ip-fallback.patch` | `webrtc:ipv4`, `webrtc:ipv6`, read when a context set no address of its own (#163) |
| `windows-keyboard.patch` | `input:windowsKeyboard` (launch-wide: the shortcut tables and GTK's key handling are process-level) |
| `zz-stock-cost-parity.patch` | `navigator.hardwareConcurrency`, `navigator.maxTouchPoints`, `screen.*`, `window.screenX`, `window.screenY` (re-orders the getters above so stock's work runs first) |

To regenerate the list: `grep -l 'MaskConfig::' patches/*.patch`.

### Includes another patch provides

Some patches call MaskConfig from a file or directory that an earlier patch
already set up, and do not add the include or `LOCAL_INCLUDES` themselves:

| Patch | Relies on |
|-------|-----------|
| `force-default-pointer.patch` | `screen-spoofing.patch` for `MaskConfig.hpp` in `layout/style/nsMediaFeatures.cpp`; `font-hijacker.patch` for `/camoucfg` in `layout/style/moz.build` |
| `media-device-spoofing.patch` | `audio-context-spoofing.patch` for `/camoucfg` in `dom/media/moz.build` |
| `system-ui-font-spoofing.patch` | `font-hijacker.patch` for `MaskConfig.hpp` in `gfx/thebes/gfxPlatformFontList.cpp` and `/camoucfg` in `gfx/thebes/moz.build` |
| `touchscreen-fingerprint-spoofing.patch` | `navigator-spoofing.patch` for `MaskConfig.hpp` in `dom/base/Navigator.cpp` |
| `font-list-spoofing.patch` | `anti-font-fingerprinting.patch` for `gfxFontGroup::mUserContextId` |
| `audio-observer-hook.patch` | `audio-context-spoofing.patch` for `/camoucfg` in `dom/media/webaudio/moz.build`; the tracking observer's `AccessObserverDom.hpp` |
| `cross-process-storage.patch` | `font-list-spoofing.patch` for `FontListManager::OnFontListStored()`, which its storage-pref callback calls |
| `font-substitutes-gate.patch` | `font-hijacker.patch` for `MaskConfig.hpp` in `gfx/thebes/gfxDWriteFontList.cpp`; `font-list-spoofing.patch` for `gfxPlatformFontList::CamouIsFamilyAllowed()` and `FontListManager::ContextIdFor()`; `navigator-spoofing.patch` for `NavigatorManager::GetSpoofedOS()` |
| `font-system-fonts-css2.patch`, `system-ui-font-spoofing.patch`, `webrtc-ip-spoofing.patch`, `zz-stock-cost-parity.patch` | `navigator-spoofing.patch` for `NavigatorManager::GetSpoofedOS()` |
| `windows-keyboard.patch` | `touchscreen-fingerprint-spoofing.patch` for `/camoucfg` in `dom/events/moz.build` |

## RoverfoxStorageManager

Per-context values set from Playwright (WebRTC IP, timezone,
screen, navigator, WebGL, font list, voices, ...) are kept in
`RoverfoxStorageManager`, which `cross-process-storage.patch` adds under
`dom/base/` with its cross-process put IPC. Every content process reads it:
a context's documents can land in any of them, and only the first document
calls the setter. The same patch provides the guard and removal every setter
uses (`IsSetterOffered`, `MarkSetterUsed`, `RemoveSetter`), and
`window-setter-seal.patch` adds its seal check to `IsSetterOffered`. When a
context's font list (`fontlist_<id>`) reaches a process, the storage-pref
callback hands it to `FontListManager::OnFontListStored()`, which flushes that
process's font caches.

`RoverfoxStorageManager::UserContextId()` is the one way a patch finds the
context a value is stored under: the principal of the node, document or window
at hand. A browsing context is not used, because a document created by
`document.implementation.createHTMLDocument()` or `DOMParser` has none, while it
shares its creator's principal. A value is stored only under its own context;
nothing writes a fallback copy under context 0.

## Backports

These patches carry upstream Firefox changes that `browser/upstream.sh`'s
version does not have yet. Drop each one when the Firefox it moves to ships
the change.

| Patch | Upstream change |
|-------|-----------------|
| `remote-security-settings.patch` | The startup import of the bundled OneCRL list into certificate storage, from mozilla-firefox's `release` branch ([Bug 2084311](https://bugzilla.mozilla.org/show_bug.cgi?id=2084311)), and the `security-state/onecrl.json` dump of Firefox 158.0.1. Camoufox turns Remote Settings off, so without the import a fresh profile has no revocations. |

## Playwright

Everything else is written against a tree that already has
`playwright/0-playwright.patch` and `playwright/1-leak-fixes.patch` applied.
