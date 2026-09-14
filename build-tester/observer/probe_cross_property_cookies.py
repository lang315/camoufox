"""#117/#119 -- does instagram.com's `datr` carry the same VALUE as
facebook.com's, or only the same name?

Two flows, one artifact: the DIRECT-VISIT arms (#117) open each property by
its own URL, and the HANDOFF arm (#119) reaches instagram.com through a
facebook.com-originated navigation. The direct visit is the state in which
cross-property identity sync is least likely to fire, so it bounds that flow
and not the properties in general; the handoff arm is what tests the rest.

#114 found a cookie named `datr` on both `.facebook.com` and `.instagram.com`,
but could not compare them: each target ran in its own fresh profile and the
harness captures names and hosts only. `docs/observer/fb-identity-hygiene.md`
(see its `## Rules` section) treats `datr` as the linkage cookie. If one browser
identity spanned both properties, those rules would need a fifth entry.

This is the OPPOSITE flow from recon_fb_live.py, which uses a fresh Session per
target precisely so cookies cannot cross-attribute. That script is not touched.

NO COOKIE VALUE LEAVES CHROME SCOPE. The comparison runs inside the browser and
returns a verdict only -- names, hosts, scope fingerprints, booleans and counts.

TWO PROPERTIES A NAIVE READING WOULD CONFLATE
---------------------------------------------
`values_identical: false` is only meaningful if the entries compared are (a) one
per host and (b) in the same cookie jar. Both are checked, because either can
fail while the other holds.

(a) CARDINALITY. A value set built over every entry reports two distinct values
    for `{fb: A, fb: B, ig: A}` -- hosts 2, distinct 2 -- the same tuple as a
    genuine cross-property difference, while actually meaning instagram's `datr`
    EQUALS one of facebook's. `entries == len(hosts)` excludes this, and it is a
    real proof rather than an enumeration: both derive from one array and every
    row contributes exactly one host, so by pigeonhole the equality holds iff
    every host has exactly one row. Per `CookieStorage.cpp` (`CookieKey` is
    baseDomain + OriginAttributes, then exact host/path/name) the only axes that
    can duplicate a (host, name) are `path` and `OriginAttributes`; secure,
    httpOnly, sameSite and expiry replace rather than duplicate, schemeMap is
    merged, and private-browsing cookies are excluded from the enumeration.

(b) COMPARABILITY. Cardinality says nothing about whether two rows live in the
    same jar. CHIPS is enabled by default and stores a `Partitioned` cookie in a
    partitioned jar independent of context, so
    `{fb: A (partitionKey=instagram.com), ig: B (unpartitioned)}` passes (a)
    cleanly while comparing two different jars -- a difference that says nothing
    about how many identities were issued. `oa_suffixes` records every entry's
    OriginAttributes suffix (values-free) and `same_partition` requires them to
    agree.

PREMISE, VERIFIED RATHER THAN ASSUMED
--------------------------------------
Every `harness.Session()` gets a fresh temporary profile: `Marionette(...)` is
constructed with no `profile=`, so `GeckoInstance` keeps its `profile=None`
default and `_update_profile(None)` takes the `tempfile.mkdtemp()` +
`create_new=True` branch. This matters -- were a profile reused, the second
visit order would re-find the first one's two ~2-year `datr` cookies and "both
orders agree" would be circular. It cannot be back-filled from the single-target
arm: `cfxdiffer`/`cfxsame` are set without `Expires`, so they are session
cookies and would vanish on restart even in a reused profile.
"""
import http.server, json, time, urllib.parse
from pathlib import Path
import harness

HERE = Path(__file__).parent

FB = "https://www.facebook.com/"
IG = "https://www.instagram.com/"
SETTLE = 8
SHIM = "https://l.facebook.com/l.php?u="

# Group the profile's cookies by name; for any name on 2+ hosts report the
# cardinality and jar-comparability facts above. Values are compared here and
# discarded here -- only booleans, counts and scope fingerprints cross out.
_PAIR_JS = """
try {
  let by = {};
  for (let c of Services.cookies.cookies) {
    let oa = ChromeUtils.originAttributesToSuffix(c.originAttributes);
    (by[c.name] = by[c.name] || []).push({
      host: c.host, value: c.value, oa: oa, scope: c.host + c.path + oa,
    });
  }
  let out = [];
  for (let name of Object.keys(by)) {
    let rows = by[name];
    let hosts = [...new Set(rows.map(e => e.host))].sort();
    if (hosts.length < 2) continue;
    let vals = new Set(rows.map(e => e.value));
    let oas = [...new Set(rows.map(e => e.oa))].sort();
    let onePerHost = rows.length === hosts.length;
    let samePartition = oas.length === 1;
    out.push({
      name: name, hosts: hosts, entries: rows.length,
      scopes: [...new Set(rows.map(e => e.scope))].sort(),
      oa_suffixes: oas,
      one_entry_per_host: onePerHost,
      same_partition: samePartition,
      comparable: onePerHost && samePartition,
      values_identical: vals.size === 1,
      distinct_values: vals.size,
    });
  }
  out.sort((a, b) => a.name.localeCompare(b.name));
  return JSON.stringify(out);
} catch (e) { return 'ERR:' + e; }
"""


def pairs(s):
    with s.m.using_context("chrome"):
        raw = s.m.execute_script(_PAIR_JS)
    if raw.startswith("ERR:"):
        raise RuntimeError("pairs: " + raw)
    return json.loads(raw)


def comparator_selftest():
    """Validate the INSTRUMENT before trusting it on the subject.

    127.0.0.1 and localhost are distinct cookie hosts served by one local
    server, so two cookie names can carry a known-unequal and a known-equal pair
    of values in a single session. Without this, `values_identical: true` cannot
    be told apart from a comparator that always says true, nor `false` from one
    that always says false.

    Its asserts stay inline deliberately: the comparator is a precondition, not
    an arm. A comparator that has stopped discriminating makes every result
    below it meaningless, so nothing past a failure here is worth preserving.
    Contrast `single_target_sanity`, whose failure is itself data.

    The read path is the same instrument as the real arm -- `document.cookie`
    and `Set-Cookie` differ only in how a row enters the jar; by the time
    `_PAIR_JS` enumerates, a host cookie and a domain cookie are the same
    struct. What it does NOT exercise is cardinality or partitioning, which is
    why those are checked explicitly rather than trusted to this.
    """
    with harness.serve(HERE) as port, harness.Session() as s:
        for host, differing in (("127.0.0.1", "AAA"), ("localhost", "BBB")):
            s.navigate(f"http://{host}:{port}/timing_probe.html")
            s.eval_content(
                f"document.cookie = 'cfxdiffer={differing}; path=/';"
                "document.cookie = 'cfxsame=SAME; path=/';"
            )
        found = {p["name"]: p for p in pairs(s)}

    out = {}
    for name, expect in (("cfxdiffer", False), ("cfxsame", True)):
        got = found.get(name)
        assert got, f"selftest: no {name} pair; comparator saw {sorted(found)}"
        assert got["values_identical"] is expect, \
            f"selftest {name}: comparator said {got}, expected identical={expect}"
        assert got["comparable"], f"selftest {name}: synthetic pair not comparable: {got}"
        out[name] = got
    return out


def visit(order):
    """One profile, both properties, in the given order."""
    with harness.Session() as s:
        for url in order:
            s.navigate(url)
            time.sleep(SETTLE)
        found = pairs(s)
    return {
        "order": order,
        "shared_name_pairs": found,
        "datr": next((p for p in found if p["name"] == "datr"), None),
        "hosts_seen_in_jar": sorted({h for p in found for h in p["hosts"]}),
    }


def single_target_sanity():
    """Does facebook.com ALONE populate an `.instagram.com` cookie?

    The only non-synthetic control here, and what licenses the whole
    attribution: if facebook.com's own page seeded an `.instagram.com` `datr`
    through an embedded resource or a host variant, the two-visit runs'
    instagram `datr` could not be attributed to the instagram visit, and
    `values_identical: false` would be a statement about embeds rather than
    about the two properties.

    It REGISTERS rather than asserts. A failure here is exactly the run whose
    visit arms you most want on disk -- the facebook-alone host list is what
    separates an intra-facebook pair from a cross-property one -- so an assert
    at this point would discard the evidence needed to interpret it.
    """
    with harness.Session() as s:
        s.navigate(FB)
        time.sleep(SETTLE)
        found = pairs(s)
    return {
        "shared_name_pairs": found,
        "datr_pair": next((p for p in found if p["name"] == "datr"), None),
    }


def _spans_both(pair):
    if not pair:
        return False
    hosts = pair["hosts"]
    return (any(h.endswith("facebook.com") for h in hosts)
            and any(h.endswith("instagram.com") for h in hosts))



# --- #119: the handoff arm ------------------------------------------------
#
# #117/#118 opened each property by its own URL. This arm reaches instagram.com
# THROUGH facebook.com, and records the navigation that got it there, because a
# redirect that 404s and an interstitial that never forwards both produce the
# same `values_differ` as a genuine negative.
#
# Why document hops and not the observer's own request rows: Collector.ingestNet
# records every page-triggered request (`additions/observer/NetHook.sys.mjs`),
# so an instagram.com pixel embedded on a facebook.com page enters those rows
# looking exactly like an arrival at instagram.com. Only
# `externalContentPolicyType === TYPE_DOCUMENT` separates "the browser navigated
# there" from "the page fetched something from there".
#
# The recorder's rows are stashed on the Collector singleton because that object
# is what survives between Marionette execute_script calls -- each call gets a
# fresh sandbox, so a plain closure or sandbox global is gone by the next call.
# The property is namespaced, memory-only, and never read by the browser itself.
_NAV_REC_START = """
try {
  let {getCollector} = ChromeUtils.importESModule('resource://gre/modules/TrackingObserver.sys.mjs');
  let c = getCollector();
  if (!c) return 'ERR:no collector -- observer not armed';
  if (c.__cfxNav) {
    try { Services.obs.removeObserver(c.__cfxNav.obs, 'http-on-modify-request'); } catch (e) {}
  }
  let rec = { rows: [] };
  rec.obs = {
    QueryInterface: ChromeUtils.generateQI(['nsIObserver']),
    observe(subject) {
      try {
        let ch = subject.QueryInterface(Ci.nsIHttpChannel);
        if (ch.loadInfo.externalContentPolicyType !== Ci.nsIContentPolicy.TYPE_DOCUMENT) return;
        // redirects/referrer are what separate a hop the SERVER carried from a hop
        // the driver typed. Without them a two-navigate arm reads as one traversal.
        let redirects = 0, referrer = null, trigger = null;
        try { redirects = ch.loadInfo.redirectChain.length; } catch (e) {}
        try { referrer = ch.referrerInfo?.originalReferrer?.spec ?? null; } catch (e) {}
        // WHO sent the browser here: a system principal is this driver typing a URL,
        // a content principal is a page navigating the browser itself. That is the
        // difference between a handoff and a direct visit wearing its shape, and it
        // holds whether the page used a 30x, a meta refresh or location.replace.
        try {
          let tp = ch.loadInfo.triggeringPrincipal;
          trigger = tp?.isSystemPrincipal ? 'system' : (tp?.originNoSuffix ?? null);
        } catch (e) {}
        rec.rows.push({ url: ch.URI.spec, method: ch.requestMethod, ts: Date.now(),
                        redirects: redirects, referrer: referrer, triggered_by: trigger });
      } catch (e) {}
    },
  };
  c.__cfxNav = rec;
  Services.obs.addObserver(rec.obs, 'http-on-modify-request');
  return 'OK';
} catch (e) { return 'ERR:' + e; }
"""

_NAV_REC_READ = """
try {
  let {getCollector} = ChromeUtils.importESModule('resource://gre/modules/TrackingObserver.sys.mjs');
  let c = getCollector();
  return JSON.stringify(c && c.__cfxNav ? c.__cfxNav.rows : null);
} catch (e) { return 'ERR:' + e; }
"""

_IG_LINKS_JS = """
let out = [];
for (let a of document.querySelectorAll('a[href]')) {
  if (/instagram/i.test(a.href)) out.push(a.href);
}
return JSON.stringify(out);
"""


def nav_record_start(s):
    with s.m.using_context("chrome"):
        r = s.m.execute_script(_NAV_REC_START)
    if r != "OK":
        raise RuntimeError("nav recorder: " + str(r))


def nav_chain(s):
    with s.m.using_context("chrome"):
        raw = s.m.execute_script(_NAV_REC_READ)
    if raw.startswith("ERR:"):
        raise RuntimeError("nav chain: " + raw)
    rows = json.loads(raw)
    if rows is None:
        raise RuntimeError("nav chain: recorder stash gone -- it did not survive the session")
    return sorted(rows, key=lambda r: r["ts"])


def _host(url):
    try:
        return urllib.parse.urlparse(url).hostname or ""
    except ValueError:
        return ""


def _is(url, suffix):
    h = _host(url)
    return h == suffix or h.endswith("." + suffix)


def _carried_by_facebook(chain):
    a = _arrival(chain)
    return bool(a) and bool(a["source"]) and _is(a["source"], "facebook.com")


def _arrival(chain):
    """The hop that landed on instagram.com, and what put the browser there.

    Three mechanisms, and only the first two are a handoff:

    `server_redirect` -- a 30x carried it, so the source is the previous hop.
    `page_navigation` -- a document navigated the browser itself (meta refresh,
        location.replace, a script), so the source is its triggering principal.
        facebook's link shim turns out to use this rather than a 30x: the l.php
        document arrives with `redirects: 0` and hands the browser on itself.
    `driver_typed` -- a system principal opened it, i.e. THIS probe typed the URL.
        That is a direct visit wearing a handoff's shape, and the case the whole
        check exists to reject.
    """
    for i, r in enumerate(chain):
        if not _is(r["url"], "instagram.com"):
            continue
        trigger = r.get("triggered_by")
        if r.get("redirects", 0) > 0 and i > 0:
            return {"hop": r["url"], "mechanism": "server_redirect", "source": chain[i - 1]["url"]}
        if trigger and trigger != "system":
            return {"hop": r["url"], "mechanism": "page_navigation", "source": trigger}
        return {"hop": r["url"], "mechanism": "driver_typed", "source": None}
    return None


def arrival_selftest():
    """The handoff discriminator must be able to answer NO.

    A passing run never exhibits the case this check exists to reject -- the probe
    typing instagram.com's URL itself, which reaches the same final URL with the
    same cookie jar and would read as a handoff on URL order alone. Proved against
    synthetic chains rather than waited for. The `redirects` field is proved
    separately and for real by chain_recorder_selftest, against live 30x hops.
    """
    cases = {
        "server_redirect": [
            {"url": "https://www.facebook.com/", "redirects": 0, "triggered_by": "system"},
            {"url": "https://l.facebook.com/l.php?u=x", "redirects": 0, "triggered_by": "system"},
            {"url": "https://www.instagram.com/", "redirects": 1, "triggered_by": "system"}],
        "page_navigation": [
            {"url": "https://l.facebook.com/l.php?u=x", "redirects": 0, "triggered_by": "system"},
            {"url": "https://www.instagram.com/", "redirects": 0,
             "triggered_by": "https://l.facebook.com"}],
        "driver_typed": [
            {"url": "https://www.facebook.com/", "redirects": 0, "triggered_by": "system"},
            {"url": "https://www.instagram.com/", "redirects": 0, "triggered_by": "system"}],
    }
    got = {k: _arrival(v) for k, v in cases.items()}
    assert got["server_redirect"]["source"] == "https://l.facebook.com/l.php?u=x", got
    assert got["page_navigation"]["source"] == "https://l.facebook.com", got
    assert got["driver_typed"]["source"] is None, got
    for k in cases:
        assert got[k]["mechanism"] == k, got
    return got


class _RedirectHandler(http.server.SimpleHTTPRequestHandler):
    """Two real 302s ahead of a served file, for the recorder self-test."""

    NEXT = {"/hop1": "/hop2", "/hop2": "/timing_probe.html"}

    def do_GET(self):
        nxt = self.NEXT.get(self.path)
        if nxt is None:
            return super().do_GET()
        self.send_response(302)
        self.send_header("Location", nxt)
        self.end_headers()

    def log_message(self, *a):
        pass


def chain_recorder_selftest():
    """Validate the recorder against a chain whose shape is known in advance.

    Without this, an empty or one-entry chain from the real arm cannot be told
    apart from a recorder that never fired -- which is the exact failure #119
    exists to prevent. A local server emits two real 302s, so the expected
    answer is three document hops in order.

    Asserts inline, like comparator_selftest: a dead recorder makes every chain
    below it meaningless, so nothing past a failure here is worth preserving.
    """
    with harness.serve(HERE, handler=_RedirectHandler) as port, harness.Session() as s:
        nav_record_start(s)
        s.navigate(f"http://127.0.0.1:{port}/hop1")
        time.sleep(1)
        chain = nav_chain(s)
    paths = [urllib.parse.urlparse(r["url"]).path for r in chain]
    assert paths == ["/hop1", "/hop2", "/timing_probe.html"], \
        f"recorder selftest: expected the 3-hop redirect chain, got {paths}"
    # The page fetches timing_parity_probe.js and favicon.ico over the same hops and
    # neither appears above: that is the TYPE_DOCUMENT filter doing the thing the
    # observer's own request rows could not do.
    redirects = [r["redirects"] for r in chain]
    assert redirects == [0, 1, 2], \
        f"recorder selftest: redirect depth misread on a known 30x chain: {redirects}"
    return {"hops": paths, "recorded": len(chain), "redirects": redirects,
            "triggered_by": [r["triggered_by"] for r in chain]}


def handoff():
    """Reach instagram.com through a facebook.com-originated navigation.

    Vector: follow an outbound link the logged-out facebook.com page actually
    publishes. If it publishes none -- which a logged-out homepage plausibly
    does not -- fall back to facebook's link shim built by hand, and say which
    was used. Finding no link is itself a recorded result; stopping there would
    leave the arm with nothing to say about a handoff.

    `real_link` follows the href as published. A click handler that rewrites the
    href at click time would not be exercised, so this is the link as the page
    serves it, not every transformation facebook's JS could apply to it.

    The arm issues TWO driver navigations -- facebook.com, then the extracted href.
    The step from the facebook page to the shim is therefore typed, with no click and
    no Referer; only the step from the shim to instagram.com is facebook's own doing.
    Each hop records `redirects`, `referrer` and `triggered_by`, so which steps the
    driver typed and which facebook performed is visible in the artifact instead of
    being implied by the order of the URLs.
    """
    with harness.Session() as s:
        nav_record_start(s)
        s.navigate(FB)
        time.sleep(SETTLE)
        links = json.loads(s.eval_content(_IG_LINKS_JS))
        if links:
            vector, target = "real_link", links[0]
        else:
            vector, target = "constructed_shim", SHIM + urllib.parse.quote(IG, safe="")
        s.navigate(target)
        time.sleep(SETTLE)
        final_url = s.eval_content("return location.href;")
        chain = nav_chain(s)
        found = pairs(s)

    return {
        "vector_used": vector,
        "ig_links_on_facebook_page": len(links),
        "navigated_to": target,
        "final_url": final_url,
        "navigation_chain": chain,
        # `chain[0]` is this arm's own navigate(FB) -- a facebook host there is true by
        # construction and would stay true if the page published a bare instagram href,
        # i.e. if no handoff happened at all. The readable question is what carried the
        # ARRIVAL: the instagram hop must be the far side of a server redirect whose
        # source is a facebook-controlled host.
        "facebook_host_after_entry": any(_is(r["url"], "facebook.com") for r in chain[1:]),
        "arrival": _arrival(chain),
        "arrival_carried_by_facebook": _carried_by_facebook(chain),
        "arrived_on_instagram": _is(final_url, "instagram.com"),
        "shared_name_pairs": found,
        "datr": next((p for p in found if p["name"] == "datr"), None),
        "hosts_seen_in_jar": sorted({h for p in found for h in p["hosts"]}),
    }


def main():
    out = {
        "issues": [117, 119],
        "provenance": harness.provenance(),
        "caveats": [
            "Logged out. `datr` is documented as being tied to `c_user` at login "
            "(docs/observer/fb-tracking-recon.md:30-46); whether that binding is "
            "per-property needs an account and is out of scope.",
            "The `runs` arms are DIRECT-URL VISITS: each property is opened by its "
            "own URL, with no navigation between them. That is the state in which "
            "cross-property identity sync is LEAST likely to fire, so a `values_differ` "
            "from those two arms bounds that flow and not the properties in general. "
            "The `handoff` arm is the one that navigates between them.",
            "The handoff arm follows the outbound link as the logged-out page "
            "publishes it, or facebook's link shim built by hand when the page "
            "publishes none. A click handler that rewrites the href at click time is "
            "not exercised, and `vector_used` says which route the run took.",
            "A difference is readable only where `comparable` is true: one entry "
            "per host and one OriginAttributes suffix across them. A pair with "
            "`comparable: false` spans two different cookie jars and says nothing "
            "about how many identities were issued.",
        ],
        "comparator_selftest": comparator_selftest(),
        "chain_recorder_selftest": chain_recorder_selftest(),
        "arrival_selftest": arrival_selftest(),
        "single_target_sanity": single_target_sanity(),
        "runs": [visit([FB, IG]), visit([IG, FB])],
        "handoff": [handoff(), handoff()],
    }

    a, b = (r["datr"] for r in out["runs"])
    both = bool(a) and bool(b)
    out["verdict"] = {
        "datr_pair_spans_both_properties_both_orders":
            _spans_both(a) and _spans_both(b),
        "comparable_both_orders": both and a["comparable"] and b["comparable"],
        "values_differ_both_orders":
            both and not a["values_identical"] and not b["values_identical"],
        "values_identical_both_orders":
            both and a["values_identical"] and b["values_identical"],
        "order_dependent": both and a["values_identical"] != b["values_identical"],
    }

    # Readable only where the navigation actually crossed AND the pair is comparable;
    # either one false makes the value comparison a statement about something else.
    # Both runs must satisfy it, for the same reason the direct-visit verdict needs
    # both orders: one arm carries no replication.
    def _readable(h):
        d = h["datr"]
        return (h["arrival_carried_by_facebook"] and h["arrived_on_instagram"]
                and bool(d) and _spans_both(d) and d["comparable"])

    hs = out["handoff"]
    h_ok = all(_readable(h) for h in hs)
    out["verdict"]["handoff_navigation_crossed_both_runs"] = all(
        h["arrival_carried_by_facebook"] and h["arrived_on_instagram"] for h in hs)
    out["verdict"]["handoff_readable_both_runs"] = h_ok
    out["verdict"]["handoff_values_differ_both_runs"] = h_ok and all(
        not h["datr"]["values_identical"] for h in hs)
    out["verdict"]["handoff_values_identical_both_runs"] = h_ok and all(
        h["datr"]["values_identical"] for h in hs)
    out["verdict"]["handoff_vectors_used"] = [h["vector_used"] for h in hs]

    # Registered, not asserted: every arm reaches disk before anything is judged.
    tripwires = []
    if out["single_target_sanity"]["datr_pair"]:
        tripwires.append(
            "facebook.com alone produced a datr pair -- the instagram datr in the "
            "visit runs cannot be attributed to the instagram visit")
    for r in out["runs"]:
        if not _spans_both(r["datr"]):
            tripwires.append(
                f"{r['order']}: no datr pair spanning both properties (hosts seen: "
                f"{r['hosts_seen_in_jar']}) -- a navigation may have silently failed")
        elif not r["datr"]["comparable"]:
            tripwires.append(
                f"{r['order']}: datr pair not comparable ({r['datr']}) -- "
                "cardinality or partitioning differs, verdict unreadable")
    for i, h in enumerate(hs):
        hd = h["datr"]
        if not h["navigation_chain"]:
            tripwires.append(
                f"handoff[{i}]: empty navigation chain -- the recorder did not fire, so "
                "nothing about this arm's route is known (its selftest passed, so "
                "suspect the run)")
        if not h["arrival_carried_by_facebook"]:
            tripwires.append(
                f"handoff[{i}] ({h['vector_used']}): nothing facebook-controlled put the "
                f"browser on instagram.com (arrival: {h['arrival']}; chain: "
                f"{[r['url'] for r in h['navigation_chain']]}) -- this is a direct visit, "
                "not a handoff")
        if not h["arrived_on_instagram"]:
            tripwires.append(
                f"handoff[{i}] ({h['vector_used']}): final URL is {h['final_url']}, not "
                "on instagram.com -- an interstitial or consent wall never forwarded")
        elif not (hd and _spans_both(hd)):
            tripwires.append(
                f"handoff[{i}]: no datr pair spanning both properties (hosts in jar: "
                f"{h['hosts_seen_in_jar']})")
        elif not hd["comparable"]:
            tripwires.append(
                f"handoff[{i}]: datr pair not comparable ({hd}) -- verdict unreadable")
    out["tripwires"] = tripwires

    blob = json.dumps(out, indent=2)
    (HERE / "probe_cross_property_cookies.json").write_text(blob)
    print(blob)
    if tripwires:
        raise SystemExit("TRIPWIRES:\n  " + "\n  ".join(tripwires))


if __name__ == "__main__":
    main()
