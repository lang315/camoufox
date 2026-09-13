"""Live recon: drive the armed observer against Meta's three properties (logged
out, one navigation each, no automated loops) to see which of the 7 instrumented
surfaces their real homepages touch. `docs/observer/README.md:6-7` names all
three as the reason this tool exists; before #114 only facebook.com had ever
been measured.

WHAT THIS REPORTS, AND WHAT IT DELIBERATELY DOES NOT
----------------------------------------------------
The finding is `surfaces_touched` -- the SET of surfaces the target reached.
That is a boolean per surface and is invariant to drain cadence.

`drain_windows_active` is NOT a read count and must never be compared across
runs or builds. `additions/camoucfg/AccessObserver.hpp:46-51` collapses each
(userContextId, surface, site) to one record per drain window, and the drain is
a 500ms timer (`additions/observer/TrackingObserverChild.sys.mjs:17`), so the
integer measures when reads clustered against that timer. Two runs of one page
can differ with no change to the browser. It is kept only because the previous
artifact carried it under the misleading name `surfaces_touched`.

The pre-#114 artifact (beta.28, facebook.com only) is preserved in git at blob
4338898, commit 7506bde. It is NOT a baseline for comparison: the binary that
produced it no longer exists, it ran unspoofed at n=1 against a live server, and
its integers are drain-window artifacts. Treat it as carried-over, not measured.
"""
import collections, json, time
from pathlib import Path
import harness

HERE = Path(__file__).parent

TARGETS = [
    "https://www.facebook.com/",
    "https://www.instagram.com/",
    "https://www.threads.net/",
]
SETTLE = 8  # real pages have no __done__ expando; let fingerprinting JS run

CAVEAT_LOGGED_OUT = (
    "Logged out, instagram.com and threads.net serve a login wall. A surface set "
    "collected there may describe the wall's bundle rather than the application. "
    "An empty set does not mean the site reads nothing."
)


def measure(url):
    """One target, one fresh Session.

    The fresh Session is load-bearing, not hygiene: Session.cookies reads the
    whole cookie jar via Services.cookies.cookies, unscoped, so sharing one
    Session across targets would attribute facebook.com's `datr` to the
    instagram.com and threads.net rows.
    """
    with harness.Session() as s:
        s.navigate(url)
        time.sleep(SETTLE)
        snap = s.snapshot()
        cookies = s.cookies()

    assert snap, f"no observer rows from {url} -- blocked, or no surface read before settle"

    surfaces = collections.Counter()
    by_site = {}
    for row in snap:
        surfaces.update(row["surfaces"])
        by_site[row["site"]] = {
            "surfaces_touched": sorted(row["surfaces"]),
            "drain_windows_active": dict(sorted(row["surfaces"].items())),
            "request_count": len(row["requests"]),
        }

    hosts = collections.Counter(r["host"] for row in snap for r in row["requests"])
    return {
        "url": url,
        "surfaces_touched": sorted(surfaces),  # THE finding: the set
        "drain_windows_active": dict(sorted(surfaces.items())),  # NOT read counts
        "by_site": by_site,
        "request_host_counts": dict(hosts.most_common()),
        # Cookies are profile-wide within this Session, not per-site; with one
        # target per Session the profile only ever saw this target.
        "cookie_names": sorted({c["name"] for c in cookies}),
        "cookie_hosts": sorted({c["host"] for c in cookies}),
    }


def main():
    out = {
        "provenance": harness.provenance(),
        "caveat": CAVEAT_LOGGED_OUT,
        "targets": [measure(url) for url in TARGETS],
    }
    assert len(out["targets"]) == len(TARGETS)
    blob = json.dumps(out, indent=2)
    (HERE / "recon_fb_live.json").write_text(blob)
    print(blob)


main()
