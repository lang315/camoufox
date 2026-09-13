"""#117 -- does instagram.com's `datr` carry the same VALUE as facebook.com's,
or only the same name?

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
import json, time
from pathlib import Path
import harness

HERE = Path(__file__).parent

FB = "https://www.facebook.com/"
IG = "https://www.instagram.com/"
SETTLE = 8

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


def main():
    out = {
        "issue": 117,
        "provenance": harness.provenance(),
        "caveats": [
            "Logged out. `datr` is documented as being tied to `c_user` at login "
            "(docs/observer/fb-tracking-recon.md:30-46); whether that binding is "
            "per-property needs an account and is out of scope.",
            "DIRECT-URL VISITS ONLY. Each property is opened by its own URL, with "
            "no navigation between them -- no link shim, no `?next=` handoff, no "
            "page embedding the other property. That is the state in which any "
            "cross-property identity sync is LEAST likely to fire, so a result of "
            "`values_differ` bounds this flow, not the properties in general.",
            "A difference is readable only where `comparable` is true: one entry "
            "per host and one OriginAttributes suffix across them. A pair with "
            "`comparable: false` spans two different cookie jars and says nothing "
            "about how many identities were issued.",
        ],
        "comparator_selftest": comparator_selftest(),
        "single_target_sanity": single_target_sanity(),
        "runs": [visit([FB, IG]), visit([IG, FB])],
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
    out["tripwires"] = tripwires

    blob = json.dumps(out, indent=2)
    (HERE / "probe_cross_property_cookies.json").write_text(blob)
    print(blob)
    if tripwires:
        raise SystemExit("TRIPWIRES:\n  " + "\n  ".join(tripwires))


main()
