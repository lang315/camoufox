# Facebook identity / cookie-linkage hygiene

What Facebook's client-side tracking reads is, on current camoufox, **coherent**
— the device surface it fingerprints (canvas / webgl / screen / navigator, plus
`devicePixelRatio` and window geometry) is spoofed consistently and verified by
`build-tester/observer/audit_coherence.py` (12/12 across Windows/macOS/Linux).
The remaining exposure is **not** the fingerprint — it is **identity linkage via
cookies**, which no fingerprint quality can fix. This is the operational playbook.

## What FB sets (measured logged-out, `build-tester/observer/recon_fb_live.json`)

`.facebook.com` cookies from a single logged-out homepage load:

- `datr` — browser-identity / anti-abuse, ~2-year lifetime. **The linkage cookie.**
- `sb` — secure browser id.
- `fr` — ad-targeting / tracking.
- `dpr`, `wd` — device signals FB *stores* (devicePixelRatio, window dimensions).
- `ps_l`, `ps_n` — login state.

`datr` / `sb` / `fr` are identity linkage: reuse them across sessions and FB
cross-links your identities **regardless of a clean, coherent fingerprint**.

## `datr` is per-property, on a direct visit and through the link shim (#117, #119)

instagram.com sets a cookie named `datr` too (`recon_fb_live.json`). It holds a
different value: one profile visiting both properties ends up holding two
distinct `datr` cookies, on `.facebook.com` and `.instagram.com`, in both visit
orders (`build-tester/observer/probe_cross_property_cookies.json`).

Two things had to be excluded before that difference could be read at all, and
the artifact records both rather than assuming them. The pair is one entry per
host (`entries` equals the host count), so the reading is not two facebook
`datr` values plus a matching instagram one — a shape that yields exactly the
same "two distinct values" tuple while meaning the opposite. And both entries
carry the same OriginAttributes suffix, so they sit in the same cookie jar;
a `Partitioned` cookie under CHIPS would otherwise make the comparison a
difference between jars rather than between identities.

So on both flows measured, a profile carries one browser identity *per property*. The rules
below are unchanged — a fresh profile per identity still resets all of them at
once — but two things follow that were previously assumed. Clearing
facebook.com's cookies alone leaves instagram.com's `datr` intact and still
linking. And a `datr` seen on instagram.com is not evidence of facebook.com
linkage; they are separate identifiers.

Two caveats bound this.

It is logged out: `datr` is documented above as being tied to `c_user` at login,
and whether that binding is per-property needs an account and was not measured.

`values_differ` is a statement about this run, not a guarantee about the
mechanism.

The third caveat that used to sit here — that each property was opened by its
own URL, with no navigation between them — is now measured (#119). Cookie scoping
only stops client-side JS from reading across domains; it says nothing about
whether Meta's servers write one id into both jars, and they own both origins, so
a handoff was the likeliest vector for that even logged out.

A third arm followed the single outbound instagram link the logged-out
facebook.com page publishes. That link arrives already wrapped in facebook's own
link shim, `h=` signature and all, so the run went
`www.facebook.com` → `l.facebook.com/l.php` → `www.instagram.com` through facebook's
own machinery rather than a shim URL built by hand. Both runs arrived on
instagram.com, both `datr` pairs passed the same one-entry-per-host and one-jar
gate, and both still held two distinct values. Going through the shim does not
hand the instagram jar facebook's identifier.

The shim does not redirect. `l.php` answers with `redirects: 0` and a document
that navigates the browser onward itself — the instagram hop carries
`triggered_by: https://l.facebook.com` and a Referer of the `l.php` URL, not a 30x.
That distinction is why the arm records who triggered each hop: what makes this a
handoff is that a facebook-controlled document put the browser on instagram.com,
and a probe typing the URL itself would produce the same three URLs in the same
order with the same final cookie jar.

The chain is recorded as top-level document hops only
(`externalContentPolicyType === TYPE_DOCUMENT`), because the observer's own request
rows would let an instagram.com subresource embedded on a facebook.com page read
exactly like an arrival at instagram.com. Three instrument properties are proved in
the same artifact: the recorder reproduces a local two-redirect chain of known shape
and reads its redirect depth as `[0, 1, 2]`; the arrival test answers `driver_typed`
with no source for a typed visit, which is what it exists to reject; and an
unstarted recorder raises rather than returning an empty chain, so "no hops" cannot
be mistaken for "recorder never fired".

What the handoff arm still does not cover: it follows the href as the page
publishes it, so a click handler that rewrites the href at click time is not
exercised; it is logged out, so a join behind an authenticated session is out of
reach; and server-side joining leaves no client-visible trace at all — two
distinct cookies are not proof of two distinct identities to Meta.

The device-signal cookies behave the opposite way: `dpr` and `wd` hold *identical*
values across both properties, which is expected — they describe one spoofed
device — and serves as a real-world positive control for the comparison, beside
the synthetic one the probe runs against itself.

## The default is already safe

Camoufox's Python API defaults to `persistent_context=False` (`sync_api.py:90`,
`async_api.py:88`) — an ephemeral profile. Every launch starts with no
`datr` / `sb` / `fr`. Keep that default unless you have a specific reason not to.

## Rules

1. **One identity = one fresh profile.** Do not share `persistent_context=True` /
   `user_data_dir=` across identities.
2. **If you must persist**, use a distinct `user_data_dir=` per identity, never
   cross-used. Wiping a persisted profile between identities is what resets `datr`.
3. **One egress IP per identity** (`proxy=`). `datr` + IP correlate; reusing one
   IP across identities links them server-side even with different cookies and a
   different fingerprint.
4. **Do not route TLS through a ClientHello-rewriting proxy.** Camoufox's JA3 is a
   genuine Firefox handshake — a strength (`plan/device-faking-targets.md:140,218`);
   a rewriting proxy regresses an authentic fingerprint into a synthetic one.

## Notes (measured, for provenance)

- `devicePixelRatio` is coherent and host-independent through the real Playwright
  launch (driven by Juggler `overrideDPPX` / `device_scale_factor`, not a JS-getter
  override). This narrows `plan/device-faking-targets.md:56` (#24) — dpr is tracked
  for the real launch path, not merely "already tracked" in general.
- Window geometry (`wd` cookie) is coherent in current pythonlib (the #647/#666
  fix, `spoofs_window_dimensions` + `clamp_window_dimensions`). A stale
  `cloverlabs-camoufox` install shadowing the editable one will exercise pre-fix
  code and fake an incoherence — uninstall it before an editable dev setup
  (`build-tester/run_tests.sh:60` does this).
- `docs/observer/README.md:108-111` carried a stale "canvas-only" observer-scope
  claim; all 7 surfaces are wired (`build-tester/observer/REPORT.md:16-29`, and
  the assert at `build-tester/observer/test_observer_records.py:17-18`). Fixed in
  #113 — `recon_fb_live.json` does not establish this: it records the four
  surfaces facebook.com touched on one load, a different question.
