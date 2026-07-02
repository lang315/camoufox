# Deep detection-site integration test plan

Goal: drive the real Camoufox binary through goapi against the strongest
public fingerprint / anti-bot oracles and prove that varied fake
fingerprints stay coherent and unflagged. Extends `plan/integration-testing.md`
(driver correctness) and the `botdetect` harness (sannysoft / areyouheadless /
rebrowser) with the deep oracles the user named.

## Success criteria (what "pass" means)

A run passes a site when, for a spoofed OS preset, the site reports:
- no automation / webdriver / headless flag, and
- no *internal* inconsistency (UA vs platform vs WebGL vs fonts vs screen all
  agree), and
- with a matched proxy: IP, timezone, and locale agree with the exit IP.

Some oracles are adversarial by design (Pixelscan, Fingerprint) — they try to
detect *masking itself*. For those, "pass" is graded (no hard automation flag)
and the raw verdict is recorded even when partial. This is expected and is the
point of testing.

## Environment

Primary target: the **Windows-native** binary `D:\cfwin2\app\camoufox.exe`
(launcher-disabled build, PR #13), driven by native Windows Go. Rationale: the
host OS is Windows, so there are no host-leak tells — the Linux+Xvfb run leaked
`platform hints: Sans:Linux`; the Windows binary shows `Segoe UI:Windows`.

Secondary target: Linux binary under Xvfb (`CF_DISPLAY=:99` +
`webgl.force-enabled`), for cross-checking and CI where no Windows host exists.

Proxy: several oracles score IP/timezone/geo consistency and CANNOT pass
without a matched egress. Supply one via `CF_PROXY=scheme://[user:pass@]host:port`
(wires `WithProxy` + `WithGeoIP`, aligning timezone/locale to the exit IP). A
residential or ISP proxy in the fingerprint's claimed region is required for a
clean pass on IPhey / Pixelscan / BrowserLeaks-IP / Cover-Your-Tracks-IP.

## Target oracles

| Oracle | URL | Class | Needs proxy | Interaction |
|---|---|---|---|---|
| Pixelscan | pixelscan.net | consistency + masking | yes (VPN/IP) | auto, ~10s settle |
| CreepJS | abrahamjuliot.github.io/creepjs | fingerprint + headless | no | auto, ~10–120s |
| BrowserLeaks | browserleaks.com/{ip,webrtc,canvas,webgl,fonts,javascript} | leaks | ip/webrtc: yes | per sub-page |
| Cover Your Tracks | coveryourtracks.eff.org | uniqueness + tracking | partial | click "Test", ~20s |
| Fingerprint | fingerprint.com/products/bot-detection (demo) | commercial bot | no | auto, read botd |
| IPhey | iphey.com | consistency (tz/lang/IP) | yes | auto, ~5s settle |

### Per-oracle checks + pass rubric

Pixelscan — reads the consistency verdict and any "masking"/"inconsistent"/
"automation" banners. Pass = consistency shown, no automation flag. Note: known
to flag anti-detect masking patterns; record the masking verdict verbatim.

CreepJS — trust score, `chromium:false`, `0% headless`, lies count, WebGL
confidence, `platform hints`. Pass = 0% headless, no lies on core nav fields,
WebGL/GPU coherent with spoofed OS. (DOM `trust`/`osFromUA` selectors are stale
in the current example; rely on the screenshot + Headless panel, not the text.)

BrowserLeaks — one probe per sub-page:
- `/webrtc`: no real LAN IP; public IP = proxy IP (or masked). Hard tell if real
  private IP leaks.
- `/canvas`: canvas hash present + varies per session (camoufox noise), not a
  known-bot constant.
- `/webgl`: unmasked vendor/renderer = coherent spoofed GPU.
- `/fonts`: font set matches the spoofed OS (Windows vs Mac vs Linux families).
- `/ip` + `/dns`: egress IP + DNS = proxy, no ISP/DNS leak (proxy runs only).

Cover Your Tracks — click "TEST YOUR BROWSER", wait for the result card. Pass =
"randomized fingerprint" (camoufox re-randomizes) OR a high one-in-N; record
bits of identifying info + tracker/ad blocking status.

Fingerprint — read the bot-detection result (`bot: notDetected` / automation
tool list) + visitorId. Pass = bot not detected. This is SOTA commercial; a
detection is a data point, not a harness bug — record it.

IPhey — read the four category badges (Software / IP Address / Location /
Hardware) + overall verdict. Pass (proxy) = all "Trustworthy". Proxyless: IP +
Location will read "Suspicious" (real IP vs spoofed locale) — expected.

## Harness design — `goapi/example/deepcheck`

Reuse the `botdetect` probe framework (`probe{URL,Wait,Settle,Extract,Fields}`)
and extend it:
- add a `Click string` field to probes for oracles needing a button
  (Cover Your Tracks) — click selector, then wait/settle.
- capture a **screenshot per oracle** (`deepcheck-<os>-<oracle>.png`) as primary
  evidence; the extracted CSV fields are secondary (SPA DOM shifts).
- emit `deepcheck-<os>.csv` (session, oracle, field, value) + a `SUMMARY` line
  per oracle with a PASS/PARTIAL/FLAG verdict computed from the fields.
- honor `CAMOUFOX_BIN`, `CF_OS`, `CF_DISPLAY`, `CF_PROXY` (same env contract as
  creepjs/botdetect).

Probes to define: pixelscan, creepjs, browserleaks_webrtc, browserleaks_canvas,
browserleaks_webgl, browserleaks_fonts, browserleaks_ip, coveryourtracks,
fingerprint, iphey. Selectors are best-effort and verified/adjusted at runtime
against the screenshots on first run (SPA markup changes).

## Test matrix

- Binary: Windows-native (primary) × Linux/Xvfb (secondary).
- OS spoof: windows (primary), mac, linux (coverage of UA/fonts/WebGL variance).
- Proxy: none (baseline — expect IP/tz/Location fails) × matched proxy (target).
- Sessions: 3 per cell (distinct random fingerprints), to show variety passes.

Priority cell (run first): Windows-native × os=windows × 3 sessions × {no-proxy,
proxy-if-available}.

## Execution layers

- L1 — launch/connect each binary (already green on Windows .exe + Linux).
- L2 — navigate + extract each oracle; handle SPA settle + the Cover-Your-Tracks
  click; screenshot each.
- L3 — per-oracle PASS/PARTIAL/FLAG from the fields + manual screenshot review.
- L4 — cross-consistency: assert UA/platform/timezone/locale/WebGL/fonts agree
  across oracles and (with proxy) match the exit IP's geo.

## Deliverables

- `goapi/example/deepcheck/main.go` (new harness).
- Per-oracle screenshots (win/mac/linux) + `deepcheck-<os>.csv`.
- A results table: oracle × session × verdict, with the proxyless vs proxy delta.
- Short report: what passes clean, what needs a proxy, what the adversarial
  oracles (Pixelscan/Fingerprint) flag and why.

## Known limits / expectations

- No proxy → IPhey (IP/Location), Pixelscan (VPN/consistency), BrowserLeaks-IP,
  Cover-Your-Tracks-IP will flag the IP/timezone mismatch. This is a config gap,
  not a fingerprint failure. A matched proxy is required to close it.
- Pixelscan and Fingerprint actively hunt for masking/automation; a partial flag
  there is expected and recorded verbatim, not treated as a harness failure.
- Some oracles rate-limit or bot-wall headless traffic; if a page won't render,
  fall back to the virtual-display (Xvfb) path and note it, no silent skips.
