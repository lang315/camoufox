"""#117 -- does instagram.com's `datr` carry the same VALUE as facebook.com's,
or only the same name?

#114 found a cookie named `datr` on both `.facebook.com` and `.instagram.com`,
but could not compare them: each target ran in its own fresh profile and the
harness captures names and hosts only. `docs/observer/fb-identity-hygiene.md`
treats `datr` as *the* linkage cookie and its playbook at `:29-40` is written as
though that is a facebook.com concern. If one browser identity spans both
properties, the playbook needs to say so.

This is the OPPOSITE flow from recon_fb_live.py, which uses a fresh Session per
target precisely so cookies cannot cross-attribute. That script is not touched.

NO COOKIE VALUE LEAVES CHROME SCOPE. The comparison runs inside the browser and
returns a verdict only -- name, hosts, whether the values are identical, and how
many distinct values there are. A `datr` on a logged-out profile is a browser id
with no account attached, but the harness's no-values rule is kept intact rather
than carved out for one probe.
"""
import json, os, time
from pathlib import Path
import harness

HERE = Path(__file__).parent

FB = "https://www.facebook.com/"
IG = "https://www.instagram.com/"
SETTLE = 8

# Group the profile's cookies by name; for any name on 2+ hosts report whether
# the values agree. Values are compared here and discarded here.
_PAIR_JS = """
try {
  let by = {};
  for (let c of Services.cookies.cookies) {
    (by[c.name] = by[c.name] || []).push({ host: c.host, value: c.value });
  }
  let out = [];
  for (let name of Object.keys(by)) {
    let hosts = [...new Set(by[name].map(e => e.host))].sort();
    if (hosts.length < 2) continue;
    let vals = new Set(by[name].map(e => e.value));
    out.push({ name: name, hosts: hosts,
               values_identical: vals.size === 1, distinct_values: vals.size });
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
    server, so the same cookie name can be given a known-equal or known-unequal
    pair of values. Without this, `values_identical: true` on `datr` cannot be
    told apart from a comparator that always says true -- and a `false` cannot
    be told apart from one that always says false.
    """
    out = {}
    for label, v1, v2, expect in (("differing", "AAA", "BBB", False),
                                  ("identical", "SAME", "SAME", True)):
        with harness.serve(HERE) as port, harness.Session() as s:
            for host, val in (("127.0.0.1", v1), ("localhost", v2)):
                s.navigate(f"http://{host}:{port}/timing_probe.html")
                s.eval_content(f"document.cookie = 'cfxprobe={val}; path=/';")
            got = [p for p in pairs(s) if p["name"] == "cfxprobe"]
        assert len(got) == 1, f"selftest {label}: expected one cfxprobe pair, got {got}"
        assert got[0]["values_identical"] is expect, \
            f"selftest {label}: comparator said {got[0]} but the values were {label}"
        out[label] = got[0]
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
    }


def single_target_sanity():
    """A session that visits only facebook.com must produce no `datr` pair.

    If it does, cookies are reaching the profile from somewhere this probe does
    not model, and every verdict below is unreadable.
    """
    with harness.Session() as s:
        s.navigate(FB)
        time.sleep(SETTLE)
        found = pairs(s)
    datr = next((p for p in found if p["name"] == "datr"), None)
    assert datr is None, f"facebook.com alone produced a datr pair: {datr}"
    return {"shared_name_pairs": found, "datr_pair": None}


def main():
    out = {
        "issue": 117,
        "provenance": harness.provenance(),
        "caveat": (
            "Logged out. `datr` is documented as being tied to `c_user` at login "
            "(docs/observer/fb-tracking-recon.md:30-46); whether that binding is "
            "per-property needs an account and is out of scope. "
            "`values_identical: true` means equal in this run, not equal by "
            "construction -- two independently generated browser ids colliding is "
            "vanishingly unlikely but is not excluded by this measurement."
        ),
        "comparator_selftest": comparator_selftest(),
        "single_target_sanity": single_target_sanity(),
        "runs": [visit([FB, IG]), visit([IG, FB])],
    }

    a, b = (r["datr"] for r in out["runs"])
    out["verdict"] = {
        "datr_pair_seen_both_orders": bool(a) and bool(b),
        "values_identical_both_orders": bool(a) and bool(b)
        and a["values_identical"] and b["values_identical"],
        "order_dependent": bool(a) and bool(b)
        and a["values_identical"] != b["values_identical"],
    }

    blob = json.dumps(out, indent=2)
    (HERE / "probe_cross_property_cookies.json").write_text(blob)
    print(blob)


main()
