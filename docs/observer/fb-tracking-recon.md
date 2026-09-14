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
timestamps, and an encoded `e` payload (the actual signal data).

### Session-establishment gating, with a denominator (#121)

`/ajax/bz` fires during the fresh-login flow and not during ordinary browsing of an
already-established session. Re-measured on `152.0.4-beta.31` (build run
`34744383071`, payload `XUL` sha256 `db0f5da4b657c438…`), driven through the real
pythonlib + Playwright launch with uBlock Origin loaded as it ships:

| arm | `/ajax/bz` | total requests through the listener |
|---|---|---|
| fresh login, clean profile | **15** | — |
| established session, browsing | **0** | 379 |
| established session, second run | **0** | 347 |

The denominator is the point. The earlier beta.28 note reported this from three
attempts with no request count, and a bare zero cannot be told apart from a listener
that never fired — this document reported exactly such a zero twice before the counter
existed. Several hundred requests reaching the listener while none of them is
`/ajax/bz` makes the zero a statement about Facebook rather than about the instrument.

### Message shape

Across the fresh-login arm, the multipart parts and their counts:

```
q x15   ts x15   blob x13   post_0 x12   post_1 x1

app_id        numeric-string(16)
webSessionId  string(20)
user          numeric-string(1)      -- "0"-length, i.e. pre-auth
trigger       string(19), string(20)
posts[].a     string(27)
posts[].b     list[2]
posts[].d     string(91)
posts[].e     string(241), string(924)
posts[].r     int
posts[].s     string(20)
posts[].t     int
```

New against the shape above: the fields **`d`** and **`r`**, and the multipart parts
**`blob`**, **`post_0`**, **`post_1`**. `user` being one character long is consistent
with these firing before authentication completes.

### The `e` payload: characterized, not decoded

| | 241-char | 924-char |
|---|---|---|
| alphabet | printable ASCII | printable ASCII |
| distinct characters | 68 | 39 |
| entropy per character | 5.787 | 4.783 |
| ceiling for that alphabet | 6.087 | 5.285 |
| strict base64 / base64url | rejected | rejected |

**It is not base64.** Sixty-eight distinct characters exceed the sixty-five in the
base64url set including `=`. Two earlier attempts here appeared to decode it only
because Python's `base64.b64decode` defaults to `validate=False`: it silently discards
out-of-alphabet characters and returns bytes from whatever remains, so it "succeeds" on
data that is not base64 at all. Both sizes are rejected under `validate=True`.

**There are two encodings under one field name.** A 68-symbol alphabet and a 39-symbol
one are not one format at two sizes. Each reaches 90–95% of its own alphabet's entropy
ceiling — dense, but structured rather than random.

So a standard container decode is not the route; anyone continuing should look for a
custom alphabet rather than reach for base64.

### What this does not cover

Only `/ajax/bz` was captured. Nothing here describes the other `/ajax/` paths the
control arms saw — `/ajax/bootloader-endpoint/`, `/ajax/qm/`,
`/ajax/webstorage/process_keys/`, and `/ajax/bnzai`, the last of which appears in no
other document in this repository and was not investigated.

One profile, one account, one host, one day. The fresh-login arm ran once; only the
established-session arm is replicated.

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
capture is logged-out-representative; a logged-in run is operator-driven, and the
fresh-login arm is single while the established-session arm is replicated.

Path filtering bounds the **disk artifact** only. Every POST body a session makes,
the login POST included, transits browser, driver and capture-process memory before
any filter runs; this design does not and cannot prevent that. Raw captures are never
opened by an agent, are read only by a standalone analyzer whose output is the
redacted shape above, live outside this repository under a private directory excluded
from search indexing and backups, and are swept after thirty days.
