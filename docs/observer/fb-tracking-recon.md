# Facebook tracking recon — the two channels + logged-in observation

How Facebook tracks a browser, observed empirically against the beta.28 build via
the real pythonlib launch (a user logged into their own account manually — no
credentials ever handled by tooling; all captured values redacted to names/schema).
Companion to `fb-beacon-generation.md` (the static `fbevents.js` reverse-engineering)
and `fb-identity-hygiene.md` (the cookie-linkage playbook).

## The two channels

FB tracks through two distinct client-side channels — not one "pixel":

| | **Pixel `/tr`** (3rd-party sites) | **Falco `/ajax/bz`** (first-party, on facebook.com) |
|---|---|---|
| Source | `connect.facebook.net/en_US/fbevents.js` (public) | facebook.com main-site JS ("Falco" logger) |
| When | Any site embedding a pixel | Logged into facebook.com |
| Reads | screen WxH, URL, referrer, iframe context, UA family, (Android-Chrome only) client-hints | encoded signal payload per event |
| Params | `fbp`/`fbc`/`eid` + beacon `id/ev/dl/rl/sw/sh/cd[]` (see `fb-beacon-generation.md`) | batched events with encoded `e` payloads |
| camoufox default | **blocked** (bundled uBlock Origin blocks `connect.facebook.net`) | first-party → runs; fingerprint is spoofed-but-coherent |

**Headline:** the client-side fingerprint surface FB's Pixel actually reads is much
smaller than folklore ("the FB pixel fingerprints everything") suggests — it is
essentially `screen.width/height` + URL/referrer + UA family. No canvas, WebGL,
timezone, language, `hardwareConcurrency`, or `devicePixelRatio` reads were found in
`fbevents.js`. The heavy linkage is **cookies (`datr`) + server-side**, not client
surface reads.

## Logged-in cookies (observed, names only — values never captured)

A logged-in facebook.com session sets (`.facebook.com`):

| Cookie | Role |
|---|---|
| `c_user` | user id — who you are |
| `xs` | session secret (auth token) |
| `datr` | **browser id, ~2yr — binds this browser to the account, survives logout** |
| `dbln` | device-based-login token (remembers the device) |
| `sb` | secure-browser id |
| `fr` | ad-targeting / ad-graph linkage |
| `presence` | chat/presence telemetry |
| `wd` | window dimensions (device signal) |
| `locale` | language/region |

`datr` is the load-bearing linkage cookie: set before login, then tied to `c_user`
at login, and persistent for ~2 years — so it re-links the same browser across
logout/login. This is why per-identity profile isolation matters (`fb-identity-hygiene.md`).

## Falco `/ajax/bz` — first-party telemetry

The logged-in behavioral/telemetry beacon (uBlock does **not** block it — it is
first-party). POST body is `multipart/form-data`; the decoded (redacted) shape:

```
{ ts, q: [ { app_id, trigger, webSessionId, user, posts: [
    [ "<event>", { e:<encoded payload>, s:<webSessionId>, t:<ts>, a:<app-version>, b:<bitfield> }, <ts>, <flag>, <seq> ]
] } ] }
```

Events observed (all fired at **login / session-init**, `user:"0"` before auth completes):

| Event (`falco:*`) | Purpose |
|---|---|
| `qe2_js_exposure` | A/B-test (Quick Experiment) exposure logging |
| `bd_pdc_signals` | browser-data / privacy-data-collection signals (device/browser signal gathering) |
| `ods_web_batch` | operational metrics / counters |

Each event carries a `webSessionId` that links all events in a session, precise
timestamps, and an encoded `e` payload (the actual signal data). The `e` blob was
**not decoded** — it is a login-time signal, and decoding a live sample would require
capturing it unredacted during a fresh authentication.

**Observed firing behavior:** `/ajax/bz` fired during the fresh-login flow only. On an
already-established (persisted) session, normal browsing — scroll + cross-page
navigation, headless and headful, three attempts — produced **zero** `/ajax/bz` posts.
So the `bd_pdc_signals` collection is session-establishment-gated, not continuous.

## camoufox's position

- **3rd-party Pixel is blocked by default** (bundled uBlock Origin) → the `/tr` beacon
  never fires on 3rd-party sites → no cross-site pixel fingerprinting for a default user.
- **First-party facebook.com tracking runs**, but the fingerprint camoufox presents is
  spoofed and coherent (`build-tester/observer/audit_coherence.py`: 12/12), so the
  device signals FB reads (`screen`, `wd`) match the claimed profile.
- **Ephemeral profile by default** (`persistent_context=False`) → closing the browser
  wipes `datr`/`c_user`/`xs`, so a session leaves no persistent linkage unless the user
  opts into `user_data_dir`.

## Method / reproduction

Real pythonlib + Playwright launch (`executable_path` → the binary, `ff_version=152`).
The user logs in manually in a headful window; tooling captures `page.on("request")`
(host + path + param keys only) and polls `context.cookies()` (names + kind + length
only) — **no cookie values, no POST bodies, no query values are ever written to disk**.
`/ajax/bz` bodies are multipart-parsed and redacted to the event schema. Session
capture is logged-out-representative; a logged-in run is operator-driven and single.
