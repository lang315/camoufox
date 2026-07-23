# fbevents.js — How Facebook's Pixel Generates Tracking Parameters

Source analyzed: `https://connect.facebook.net/en_US/fbevents.js`, fetched and saved locally
(397,063 bytes minified). Analyzed programmatically (Node.js string/regex scanning of the
downloaded file — no browser execution). The bundle is **not** Facebook's internal `__d()`
module system; it uses a flat, sequential module registry:

```js
a.ensureModuleRegistered("ModuleName", function(){ return (function(e,t,n,r){ ... })(e,t,n,r) })
```

204 such registrations exist, each independently `require`-able via `a.getFbeventsModules("Name")`.
Module *names* survive minification (only local variables are mangled to single letters), which
is what makes this static analysis tractable — every citation below is a real module name found
by regex-scanning `a.ensureModuleRegistered("<name>",function(){...)` boundaries.

A `fbq.set("moduleEncodings", {"map": {...}})` payload near the end of the file lists all 204
module names against small integers — this is just a lazy-load ID table, not functional code
(it produced several false leads during this analysis, noted where relevant).

---

## 1. `fbp` cookie

**Format:** `fb.<subdomainIndex>.<creationTime>.<payload>[.<appendix>]`

Defined in module **`SignalsFBEventsPixelCookie`** as a class with `pack()`/`unpack()`:

```js
l="fb",s=4,u=5,c=["AQ","Ag","Aw","BA","BQ","Bg"],p="__DOT__",f=/\./g
pack(){
  var e=this.payload!=null?this.payload.replace(f,p):"",
      t=[l,this.subdomainIndex,this.creationTime,e,this.appendix].filter(function(e){return e!=null});
  return t.join(".")
}
```

So the literal `"1"` commonly seen in real `fb.1.<ts>.<rand>` cookies is **not a fixed version
byte** — it is `this.subdomainIndex`, computed fresh per-domain (see below). Any literal `.` in
the payload is escaped to `__DOT__` before joining, and un-escaped on `unpack()`. `unpack()`
requires 4 or 5 dot-separated fields, and if a 5th "appendix" field is present it must be exactly
2 chars (one of `AQ/Ag/Aw/BA/BQ/Bg`, i.e. base64 of a single byte 1–6) or 8 chars — purpose of
this appendix could not be determined further (no write-site found for it).

**`subdomainIndex` algorithm** — module **`SignalsPixelCookieUtils`**, function `P` (exported as
`writeNewCookie`): probes cookie domains from the narrowest to the widest label set until one
actually persists:

```js
function P(n,r){
  for(var o=..., a=e.location.hostname, i=a.split("."), l=new t(r), s=0; s<i.length; s++){
    var u=I(i,s);              // I(e,t) = e.slice(e.length-1-t).join(".")
    l.subdomainIndex=s;
    x(n,l.pack(),u,o);         // writes cookie scoped to domain u
    var c=m.getComparedCookieRaw(n);
    if(c!=null && c!="" && t.unpack(c)!=null) return m.updateCookieCache(n,l.pack()), l;
  }
  return m.updateCookieCache(n,l.pack()), l;
}
```

`s=0` first tries the bare TLD (e.g. `.com`) — browsers reject cookies on public suffixes, so
this fails and the loop advances; `s=1` tries `example.com`, which normally succeeds and yields
`subdomainIndex=1` (why `fb.1.…` is the common case). A site on `www.example.co.uk` would climb
further before a cookie sticks, yielding a higher index. This is a **generic public-suffix probe**,
not a lookup table.

**Cookie attributes** (function `T`, "buildCookieString"):
```js
"".concat(e,"=").concat(t,";")+"expires=".concat(E(o),";")+"domain=.".concat(r,";")+
  (isChrome() ? "SameSite=Lax;" : "") + "path=/"
```
TTL constant `NINETY_DAYS_IN_MS = 2160*60*60*1e3` (90 days) is shared by both fbp and fbc.
Cookie name `"_fbp"`, wire param name `"fbp"` (constants `C="_fbp",b="fbp"` in
`SignalsPixelCookieUtils`).

**Creation trigger not located:** I confirmed the full packing/writing machinery above, but could
not pin down the exact call site that supplies the *initial* payload for a brand-new `_fbp` (i.e.
who calls `writeNewCookie("_fbp", <freshly generated value>)` on first visit). `SignalsPixelCookieUtils`
has exactly one external consumer in the whole bundle (`signalsFBEventsSendEventImpl`, and only for
an unrelated `_fbleid` cookie — see §5). The real orchestration is almost certainly inside the
107KB `SignalsFBEventsShared` chunk, but a targeted grep for `_fbp`/`writeNewCookie`/`subdomainIndex`
inside every plugin I checked (`identity`, `commonincludes`, `opttracking`, `iwlbootstrapper`,
`SignalsFBEventsFBQ`, `SignalsFBEventsConfigStore`, `SignalsFBEvents` core, `SignalsFBEventsAutomaticPageViewEvent`)
came up empty. Flagging as unresolved rather than guessing.

---

## 2. `fbc` cookie

Same `SignalsPixelCookieUtils` module defines the config that drives `fbc`:

```js
f="_fbc", g="fbc", h="fbcs", y="aems", v="fbclid",
S=[{prefix:"", query:"fbclid", ebp_path:"clickID"}],
R={params:S}
```

So `_fbc`/`fbc` (cookie name / wire param name) is built from URL param **`fbclid`** by default,
via a *configurable table* (`S`), not a hardcoded single param — `DEFAULT_FBC_PARAMS`/
`DEFAULT_FBC_PARAM_CONFIG` are exported so a remote config can add more click-id query params
(e.g. per-advertiser). This is corroborated by the remote-config schema in
**`SignalsFBEventsBrowserPropertiesConfigTypedef`**:

```js
fbcParamsConfig: t.allowNull(t.objectWithFields({
  params: t.allowNull(t.arrayOf(t.objectWithFields({
    ebp_path: t.string(), prefix: t.string(), query: t.string()
  })))
})),
enableFbcParamSplitIOS: ..., enableFbcParamSplitAndroid: ..., enableAemSourceTagToLocalStorage: ...
```
i.e. the pixel's per-pixel-ID server config can push additional click-id query params, and can
toggle iOS/Android-specific "fbc param split" behavior and AEM (Aggregated Event Measurement)
local-storage mirroring — all **server-gated, not visible in the static JS**.

Same `pack()`/subdomain-probe/90-day-TTL/`SameSite=Lax` mechanics as fbp apply to fbc (both go
through the same `writeNewCookie`/`writeExistingCookie` functions in `SignalsPixelCookieUtils`).
A generic query-param reader (`new URL(href).searchParams.get(cfg.query)`, found via `.searchParams`
inside `SignalsFBEventsShared`) is consistent with the config-driven design — since the param
*name* (`"fbclid"`) is data, not a literal, it never shows up as a grep-able `?fbclid`/`get("fbclid")`
string, which is why the exact call site is hard to isolate statically (same disclosed gap as §1).

**Guardrail/experiment names directly confirm this area is actively server-tuned** (from
`fbq.set("experiments", [...])` at the end of the file):
```
"send_fbc_when_no_cookie" (passRate 1), "set_fbc_cookie_after_config_load" (passRate 0),
"fix_fbc_fbp_update" (passRate 0), "prioritize_send_beacon_in_url" (passRate 0.5)
```
i.e. Facebook has (or had) A/B-tested: sending `fbc` even without a stored cookie, deferring
fbc-cookie writes until remote config loads, and a bug-fix flag for fbc/fbp update ordering.

---

## 3. The `/tr` beacon — full param structure

Endpoint, from module **`SignalsFBEventsNetworkConfig`**:
```js
{ENDPOINT:"https://www.facebook.com/tr/",
 INSTAGRAM_TRIGGER_ATTRIBUTION:"https://www.instagram.com/tr/",
 TOPICS_API_ENDPOINT:"https://www.facebook.com/privacy_sandbox/topics/registration/"}
```
(An Instagram-specific `/tr/` variant exists, plus a Privacy-Sandbox Topics-API registration
endpoint — the latter is set up but not exercised by the code paths traced below.)

The core param assembly is module **`signalsFBEventsFillParamList`**, function `d(n)`:
```js
S.append("id", m)                 // pixel ID
S.append("ev", d)                 // event name, e.g. "PageView"
S.append("dl", C)                 // document link
S.append("rl", b)                 // referrer link
S.append("if", c)                 // is-iframe boolean
S.append("ts", g)                 // timestamp (ms)
S.append("iw", i())               // is-web-worker boolean
S.append("cd", y)                 // custom-data object (flattened later, see below)
S.append("sw", e.screen.width)
S.append("sh", e.screen.height)
a && S.addRange(a)                // merges in params computed elsewhere (v, r, a, ec, it, coo, eid, ...)
R!=null && S.append("exp", l.getCode())      // active first-gen quick-experiment bucket
E!=null && E.length>0 && S.append("expv2", E) // QEv2 experiment-result params
```
`c` (the `if` value) = `e.top !== e`, i.e. `window.top !== window` — true when the pixel runs
inside an iframe. `C`/`b` (dl/rl) come from `SignalsFBEventsComparedManagers.getComparedURL()`/
`getComparedReferrer()`, which by default just proxy `location.href`/`document.referrer` (see §4).
`g` (`ts`) is `Date.now()`-equivalent, set immediately before this runs, in module
**`signalsFBEventsSendEvent`**: `e.timestamp=new Date().valueOf()`.

The `a && S.addRange(a)` params are computed by a second function (module **`SignalsFBEvents`**,
function `Ke`, `e,n,r,o,i,l` args = pixel, eventName, customData, —, eventData, additionalParams):
```js
u.append("v", t.version)                                              // pixel script version
t._releaseSegment && u.append("r", t._releaseSegment)                  // FB internal rollout segment
u.append("a", e.agent || t.agent)                                     // partner/integration agent id
e && (u.append("ec", e.eventCount), e.eventCount++)                    // per-pixel monotonic event counter
u.append("it", Le)                                                     // "integration type" marker, default -1
var d = e && e.codeless==="false"; u.append("coo", d)                  // codeless-setup opt-out flag
u.append("dpo", dataProcessingOptions.join(",")); u.append("dpoco", country); u.append("dpost", state)
u.append("de", disabledExtensions.join(","))
```
`v` reads `fbq.version` at send time (falls back to the literal string `"unknown"` if unset — I
could not confirm the exact numeric value baked into this build; a `"3.32.2"` string exists
elsewhere in the file inside an unrelated internal `versions` telemetry array, so I'm not
asserting it's the pixel version). `ec` is **purely an in-memory counter**, not derived from any
browser surface — it counts how many events this pixel object has fired this page-load.

`cd` (custom data) is appended as a raw JS object; the *serialization* layer
(module **`SignalsParamList`**, method `_appendObject`) is what turns it into wire params:
```js
_appendObject(t,n,o){
  for (var a in n) if (hasOwn(n,a)) {
    var i = "".concat(t,"[").concat(encodeURIComponent(a),"]");   // "cd[value]", "cd[currency]", ...
    this._append({name:i, value:n[a]}, "shallow", o)
  }
}
```
So `{value:9.99,currency:"USD"}` becomes `cd[value]=9.99&cd[currency]=USD` — one bracket level of
flattening; a nested object inside a `cd` field would fall back to a JSON-stringified string
rather than recursing further.

Final serialization (module **`SignalsEventPayload`**, `toQueryString`):
```js
toQueryString(){ var e=[]; this.forEach(function(t,n){ e.push(t+"="+encodeURIComponent(n)) }); return e.join("&") }
```
— key not encoded, value always `encodeURIComponent`-ed.

**Additional params observed but not in the requested list:**
- `rqm` — request method marker (`"GET"`/`"FGET"`/`"SB"`/`"formPOST"`/`"fetch"`), i.e. the pixel
  reports back over the wire *how it sent the beacon* (see §6).
- `dlc`/`rlc` — `"1"` flags set when `dl`/`rl` changed since the previous event on this page
  (SPA-navigation detection), from `signalsFBEventsSendEventImpl`: `documentLink !== getComparedURL() && append("dlc","1")`.
- `ie[c]` — set to `1` when a plugin overwrites a custom-param value that already existed
  (internal QA/conflict signal).
- `chmd`/`chpv`/`chfv` — Client-Hints params, Android-Chrome-only (§4).

---

## 4. Surface → param mapping

| Browser surface read | How it's read | Beacon param |
|---|---|---|
| `location.href` | `SignalsFBEventsURLManager.getURL()` → falls back to `n.href` (`n`=location) unless a registered override provider exists | `dl` |
| `document.referrer` | `SignalsFBEventsURLManager.getReferrer()` → falls back to `t.referrer` (`t`=document) | `rl` |
| `window.top !== window` | `signalsFBEventsFillParamList`: `c = e.top !== e` | `if` |
| `screen.width` / `screen.height` | direct property read in `signalsFBEventsFillParamList` | `sw` / `sh` |
| `navigator.sendBeacon` (feature test) | `signalsFBEventsSendBeacon`: `!e.navigator.sendBeacon` gate | transport choice, reported as `rqm=SB` |
| `navigator.userAgent` (regex for FB in-app browser) | `signalsFBEventsSendGET`: matches `Android`+`FB_IAB`/`Instagram`, or `iPhone`/`iPad`+`FBIOS`/`Instagram`/`MessengerForiOS`/`MessengerLiteForiOS` | raises the GET-request size ceiling from 2048 → 32768 bytes (no direct param, but changes whether GET vs fallback transport is used) |
| `navigator.userAgentData` + `getHighEntropyValues(["model","platformVersion","fullVersionList"])` (Android Chrome only, gated by UA sniff) | plugin **`SignalsFBEvents.plugins.clienthint`** | `chmd` (model), `chpv` (platformVersion), `chfv` (Chrome brand's full version, picked out of `fullVersionList`) |
| `Math.random()` (+ `Date.now()`) | `generateEventId` module | auto `eid` when no developer override (§5) |
| `document.cookie` (`_fbp`/`_fbc`) | `SignalsFBEventsRawCookieOps`/`CookieManager` → `SignalsPixelCookieUtils` | `fbp`, `fbc` |
| in-memory per-pixel counter (not a DOM surface) | `e.eventCount++` in `SignalsFBEvents` module `Ke()` | `ec` |
| `navigator.sendBeacon`/`fetch` feature detection, UA Chrome check | `signalsFBEventsGetIsChrome`, used to pick beacon vs. GET-only for non-Chrome | affects transport, surfaces as `rqm` |

Client Hints is the one genuinely async, opt-in-feeling surface read:
```js
h="chmd",y="chpv",C="chfv"
n.set(h,String(t.model)); n.set(y,String(t.platformVersion));
/* pick Chrome entry from fullVersionList */ n.set(C,String(r))
...
e.navigator.userAgentData.getHighEntropyValues(["model","platformVersion","fullVersionList"])
  .then(...)               // registered as an "asyncParamFetcher" keyed "clientHint"
```
This is gated behind `checkIsAndroidChrome(navigator.userAgent)` — it never fires on desktop or
non-Chrome mobile — and its async nature is *why* the event queue/batching gate exists (§6).

**Not read at all, as far as this static pass could tell:** `navigator.language`, timezone
(`Intl.DateTimeFormat`/`getTimezoneOffset`), `navigator.hardwareConcurrency`, WebGL/Canvas,
`devicePixelRatio`, `navigator.platform`. The identifiable "device/browser fingerprint" surface
in this build is materially smaller than folk knowledge of "the FB pixel" suggests — it's
essentially screen WxH, iframe/worker context, UA-sniffed browser family, and (Android Chrome
only) three Client-Hint fields, plus whatever the site's own `fbq('track', ..., customData)`
call supplies as `cd[...]`.

---

## 5. Event dedup (`eid`)

Module **`generateEventId`**:
```js
function e(){
  var e=new Date().getTime(),
      t="xxxxxxxsx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g,function(t){
        var n=(e+Math.random()*16)%16|0; return e=Math.floor(e/16), (t==="x"?n:n&3|8).toString(16)
      });
  return t
}
function t(t,n){ var r=e(); return (n!=null?n:"none")+"."+(t!=null?t:"none")+"."+r }
```
Note the template has a literal, non-substituted `s` baked into it
(`"xxxxxxxsx-xxxx-4xxx-yxxx-..."` — the replace regex is `/[xy]/g`, which never touches `s`), so
generated IDs look like a UUIDv4 with a fixed `s` at position 9, not a real UUID. The inner
`e()` is a **timestamp-seeded pseudo-UUIDv4** (mixes `Date.now()` into the RNG stream), not
`crypto.getRandomValues`.

The only call site with a fully-confirmed argument order (module `signalsFBEventsSendEventImpl`,
handling a Lead-event-specific `_fbleid` cookie, unrelated to normal `eid` but sharing the same
generator):
```js
v(t && t.VERSION || "undefined", "LCP")   // v = generateEventId
```
→ output shape `"LCP.<VERSION>.<uuid-ish>"`, confirming the function signature is
`generateEventId(firstArg, secondArg) → secondArg + "." + firstArg + "." + <random>`.

**Developer override** — module **`handleEventIdOverride`**:
```js
function t(t,n,r,o,a){
  if (t!=null && (t.eventID!=null || t.event_id!=null)) {
    var s = /* extracted eventID/event_id, unwrapped if object-shaped */;
    s==null && (n.event_id!=null||n.eventID!=null) && logConsoleWarn(...); // "should be in 4th param" warning
    r.containsKey("eid")
      ? (s==null||s.length==0 ? logUserError({type:"NO_EVENT_ID"}) : r.replaceEntry("eid", s))
      : r.append("eid", s);
  }
}
```
This only runs any logic at all when the caller supplied an explicit `eventID`/`event_id` — i.e.
this is strictly an *override*, not the primary generator. Confirmed by
`signalsFBEventsSendEvent`'s driver function `f(e,o)`:
```js
e.customData = {...e.customData}; e.timestamp = new Date().valueOf();
var a = eidAlreadySet ? existingEidValue : null;
if (a==null || a==="") {
  e.customParams = e.customParams || new ParamList;
  e.id!=null && SignalsFBEventsEvents.setEventId.trigger(String(e.id), e.customParams, e.eventName);
}
```
— i.e. if no `eid` is present yet, a `SetEventIDEvent` bus is triggered to auto-populate one
(this bus ultimately wraps `generateEventId`, per module dependency graph, though I could not
isolate the exact listener line that calls it for the *general* case — same category of gap as
§1/§2, disclosed rather than guessed).

`SignalsEventPayload.getEventId()` normalizes across the 3 wire-key shapes an `eid` might have
been stored under: `["eid", "eid[]", encodeURIComponent("eid[]")]` — first non-empty wins. This
`eid` is what's meant to let the browser-side pixel and a server-side Conversions API call for
the *same logical event* be deduplicated by Facebook.

---

## 6. Transport: GET / POST / sendBeacon / batching

Four transport modules exist; the selection cascade lives in **`signalsFBEventsFireEvent`**,
function `S(e,n)` (`e`=built ParamList):
```js
var isNonChrome = !signalsFBEventsGetIsChrome();
if (isNonChrome && ev==="SubscribedButtonClick" && sendBeacon(e)) { fired("BEACON"); return }
if (sendGET(e, {highFetchPriority, expv2})) { fired("GET"); return }
if (isNonChrome && sendBeacon(e)) { fired("BEACON"); return }
/* shopify-sandbox experiment edge case → sendFormPOST then sendFetch */
sendFormPOST(e); fired("POST");
```
So the real-world order is: **image-pixel GET first (always tried), then `navigator.sendBeacon`
as a fallback (non-Chrome only), then a hidden-iframe form POST as the universal last resort.**
`fetch()` (module `signalsFBEventsSendFetch`) exists and is fully implemented but is only wired
into the cascade behind a Shopify-sandbox experiment gate — in the default path it's dead code.

**GET** (`signalsFBEventsSendGET`) — a **tracking-pixel `<img>`**, not XHR:
```js
l=2048, s=32*1024;  // size ceiling: 2KB normally, 32KB inside FB's own in-app browser (UA-sniffed)
e.set("rqm", forceGet ? "FGET" : "GET");
var f = url + "?" + paramList.toQueryString();
if (ignoreLengthCheck || f.length < ceiling) { new Image().src = f; return true }
return false;   // caller falls through to the next transport
```
`referrerPolicy="origin"` is conditionally set via `SignalsFBEventsShouldRestrictReferrerEvent.trigger(e)`.

**sendBeacon** (`signalsFBEventsSendBeacon`):
```js
n.set("rqm","SB");
navigator.sendBeacon(url, n.toFormData());   // POST-like, browser-managed, survives page unload
```

**Hidden-iframe form POST** (`signalsFBEventsSendFormPOST`) — no size limit:
```js
var l = "fb"+Math.random().toString().replace(".","");   // random iframe/form target name
form.method="post"; form.target=l; form.style.display="none";
/* one hidden <input> per ParamList entry */ form.submit();
r.set("rqm","formPOST");
/* 5s timeout fallback if the iframe never loads */
```

**fetch** (`signalsFBEventsSendFetch`, gated off by default): `mode:"no-cors", credentials:"include",
cache:"no-store", keepalive:true`; GET if the URL is under 2048 chars, otherwise POST with
`application/x-www-form-urlencoded` body; 8-second `AbortController` timeout.

**Batching:** there is no "combine N events into one HTTP request" batching in the default path —
`send_events_in_batch` exists as an experiment name (`passRate: 0`, i.e. currently 0% rollout /
disabled). What *does* exist is an **async-gate queue** (module `SignalsFBEventsAsyncParamUtils`):
```js
function flushAsyncParamEventQueue(e){ e.asyncParamPromisesAllSettled=true; while(e.eventQueue.length){ ...send... } }
Promise.allSettled(fetchers.map(f=>f.request)).then(r => { e.asyncParamPromisesAllSettled=true; ...; flush(e) })
```
Events fired before all registered `asyncParamFetchers` (in practice, just the Android-Chrome
Client-Hints promise, §4) have settled get pushed onto `eventQueue` instead of sent immediately;
once `Promise.allSettled` resolves, the queue drains and each event is sent with the Client-Hint
params merged in. On any page where the Client-Hints fetcher never registers (non-Android-Chrome),
this queue is a no-op and events fire synchronously.

---

## What could not be determined from this static pass

- **Exact fbp/fbc creation call site.** The packing/writing primitives (`SignalsPixelCookieUtils`)
  and the fbc config table (`fbclid` → `DEFAULT_FBC_PARAMS`) are fully confirmed, but the glue
  code that (a) generates the *initial* random fbp payload on first visit, and (b) reads `fbclid`
  from the URL and calls `writeNewCookie("_fbc", ...)`, was not isolated to a specific line. I
  checked every loaded plugin (`identity`, `commonincludes`, `opttracking`) plus `SignalsFBEventsFBQ`,
  `SignalsFBEventsConfigStore`, the core `SignalsFBEvents` module, and grepped the 107KB
  `SignalsFBEventsShared` chunk — none contained it. Likely inside `SignalsFBEventsShared` in a
  region not matched by the specific identifier strings I searched for.
- **The general (non-Lead-event) `eid` auto-generation listener.** I confirmed *that* it's
  triggered (`SignalsFBEventsEvents.setEventId.trigger(pixelId, paramList, eventName)`) and *what
  primitive it must ultimately call* (`generateEventId`, by module dependency graph and one fully
  verified analogous call site), but not the literal `.listen()` registration that connects them.
- **`Le` ("it" param) semantics** — initialized to `-1`, presumably an "integration type" set when
  a partner platform (Shopify/WooCommerce/etc.) self-identifies, but reassignment sites weren't traced.
- **The 90-day-old / `expires`-vs-`max-age` cookie split** is gated behind an experiment
  (`COOKIE_TTL_FIX` / `isInTestPageLoadLevelExperiment`) — which variant a given browser gets is
  server-controlled (allocation/passRate live in the `fbq.set("experiments", [...])` payload, but
  actual per-visitor bucketing is not visible statically).
- **Numeric value of `fbq.version`** (the `v` param) — the code path is confirmed
  (`t.version`, "unknown" fallback) but the live value wasn't confirmed; a `"3.32.2"` string
  exists elsewhere in the file in an apparently-unrelated internal telemetry array, so it is
  *not* cited as the pixel version.
- **PII/Advanced-Matching hashing** (`ud[em]`, `ud[ph]`, SHA-256 via `sha256_with_dependencies_new`,
  `SignalsPixelPIIUtils`) exists and is extensive but is out of scope for this device/browser-surface
  request and wasn't analyzed in depth.
- Server-side behavior generally: every experiment/guardrail listed in `fbq.set("experiments"/"guardrails", [...])`
  is a live remote toggle — the static JS shows the *branches* but not which branch is active for
  any given pixel ID/visitor at request time.

---

## Key module/identifier index

`SignalsFBEventsPixelCookie` (pack/unpack), `SignalsPixelCookieUtils` (writeNewCookie/writeExistingCookie/
readPackedCookie/DEFAULT_FBC_PARAMS), `SignalsFBEventsComparedManagers` (getComparedURL/Referrer/CookieRaw —
thin control/test rollout shim over `SignalsFBEventsURLManager` + `SignalsFBEventsCookieManager` +
`SignalsFBEventsRawCookieOps`), `signalsFBEventsFillParamList`, `SignalsFBEvents` (core `Ke`/`Ye` functions),
`generateEventId`, `handleEventIdOverride`, `signalsFBEventsSendEvent`, `signalsFBEventsSendEventImpl`,
`signalsFBEventsFireEvent` (transport cascade), `signalsFBEventsSendGET`/`SendBeacon`/`SendFormPOST`/`SendFetch`,
`SignalsFBEventsNetworkConfig`, `SignalsFBEventsAsyncParamUtils`, `SignalsFBEvents.plugins.clienthint`,
`SignalsParamList` / `SignalsEventPayload` (serialization), `SignalsFBEventsBrowserPropertiesConfigTypedef`
(remote config schema).
