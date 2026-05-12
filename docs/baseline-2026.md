# Camoufox Fingerprint Baseline — 2026-05-12

Measurements taken against **Camoufox 150.0.2-beta.25** (prebuilt mac arm64 from the
official GitHub release) using `goapi/example/baseline` with `WithOS("windows")` and the
default fingerprint generator. Host: macOS arm64 (Apple Silicon).

The baseline establishes pre-patch numbers so the WebRTC + canvas patch work has measurable
acceptance targets.

## How to reproduce

```
cd goapi
CAMOUFOX_BIN=/path/to/camoufox/Camoufox.app/Contents/MacOS/camoufox \
  go run ./example/baseline -n 10 -out ../docs/baseline-after.csv
```

Use `-offline` to skip the network oracles (CreepJS / BrowserLeaks / AmIUnique) and only
exercise the in-page `client_eval` probe.

## Sample results (offline, n=5)

CSV at `docs/baseline-before.csv`. Per-vector summary:

| Vector | Sessions | Unique values | Notes |
|---|---|---|---|
| `client_eval.canvas_hash` | 5 | **3** | 2D fillRect + fillText canvas. macOS host produces some collisions because CoreText renders deterministically; on more diverse hosts uniqueness rises. Even at 3/5 the canvas hash is strongly identifying within OS+host cluster. |
| `client_eval.canvas_len` | 5 | 1 | All 4934 bytes — `toDataURL` length is stable per drawing. |
| `client_eval.ua` | 5 | 2 | Two different rv: versions emitted by the preset sampler (147, 148). Expected — preset rotation. |
| `client_eval.platform` | 5 | 1 | All `Win32`. Spoof working. |
| `client_eval.tz` | 5 | 1 | All `Asia/Ho_Chi_Minh` — host timezone leaks (no proxy configured in this run). |

Network oracles (CreepJS / BrowserLeaks / AmIUnique) not yet sampled — full 10-session run
with all four probes recommended before pinning final numbers.

## Phase-7 acceptance targets

After the canvas + WebRTC patches land (`patches/canvas-spoofing.patch` and the extensions
to `patches/webrtc-ip-spoofing.patch`), the same harness must produce:

### Canvas
| Vector | Pre-patch | Target | Rationale |
|---|---|---|---|
| `client_eval.canvas_hash` | 3 unique / 5 | **≥ 5 unique / 5** | Per-context seed mixed with content hash → every launch should differ. Strict equality across two reads in the same session also required (verified separately by `goapi/example/canvas`). |
| `client_eval.canvas_len` | 1 | **1** (unchanged) | `toDataURL` byte-length must not depend on the noise (or the noise itself becomes a fingerprint). |
| `browserleaks_canvas.crc` (when run online) | TBD | **uniformly distributed across 10 launches** | Identical drawing → 10 distinct CRCs that don't reveal a Camoufox-specific signature. |
| `browserleaks_canvas.uniq` | TBD | Population-blending (cf. real Firefox Win clusters) | Score should align with a *common* fingerprint class, not be lowest-possible uniqueness. |

### WebRTC
| Vector | Pre-patch | Target | Patch |
|---|---|---|---|
| `browserleaks_webrtc.public_ip` | host real public IP | spoofed value (`webrtc:ipv4`) | already in `webrtc-ip-spoofing.patch` |
| `browserleaks_webrtc.local_ip` | host real RFC1918 (or absent) | spoofed (`webrtc:localipv4`) or absent | P4-T2 + P5-T1 |
| `browserleaks_webrtc.mdns` | host UUID `.local` | **absent** | P5-T1 (disable `media.peerconnection.ice.obfuscate_host_addresses`) |
| `browserleaks_webrtc.fp` (DTLS) | real cert thumbprint | **unchanged** (documented out of scope) | n/a |
| any `fe80::` in candidates | host EUI-64 derived | fabricated per-context `fe80::<hash(userContextId)>` | P4-T1 |

### Determinism (separate test, `goapi/example/canvas`)
| Property | Requirement |
|---|---|
| Two `toDataURL()` calls on the same canvas in the same `BrowserContext` | byte-identical |
| Same drawing in two `BrowserContext`s | non-equal |
| Same drawing across two launches with identical `canvas:seed` and `userContextId` | byte-identical |
| Canvas with `seed == 0` (unset) | pristine, no perturbation |

### Real-app non-regression
| Test | Pass criterion |
|---|---|
| Three.js spinning-cube demo | renders identically to vanilla Firefox (pixel diff < 0.5%); intermediate FBO `readPixels` untouched |
| Jitsi/Whereby room (two participants) | media exchanged within 5s |
| Any page with `gl.readPixels` against default FBO | output differs per-context, identical within-context |

## Notes

- The full 10-session network run was deferred for the initial baseline; the offline n=5
  set already shows the canvas-hash determinism problem clearly. Run the network oracles
  before declaring the post-patch numbers final.
- macOS arm64 is a friendly host (few WebGL drivers, CoreText is uniform). Linux + Intel
  iGPU hosts produce much more entropy out of the box — re-baseline on Linux when the
  Phase 1 Docker build pipeline is wired.
- AmIUnique uniqueness ratios depend on AmIUnique's own corpus; treat as an oracle, not a
  ground truth.
