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
import collections, hashlib, json, os, time
from pathlib import Path
import harness

HERE = Path(__file__).parent

TARGETS = [
    "https://www.facebook.com/",
    "https://www.instagram.com/",
    "https://www.threads.net/",
]
SETTLE = 8  # real pages have no __done__ expando; let fingerprinting JS run

# This harness is NOT the browser the product ships. Every artifact carries this
# list so no reader mistakes one for the other.
LAUNCH_DIFFERS_FROM_SHIPPED = [
    "no CAMOU_CONFIG: harness.py:49-50 unsets it, so the site is served the real "
    "host UA, platform and screen -- and Meta selects the JS it serves on what it sees",
    "no addons: pythonlib/camoufox/utils.py:1079 calls add_default_addons (uBlock "
    "Origin, addons.py:19) on the shipped launch path; a bare Marionette launch loads none",
    "no BrowserForge fingerprint (pythonlib path only)",
    "no generated fontconfig (pythonlib path only)",
    "harness.py:12-13 forces webgl.force-enabled and webgl.enable-webgl2, and sets "
    "media.peerconnection.ice.obfuscate_host_addresses=False, switching off a "
    "privacy protection the product ships with",
    "headless: harness.py:52 hardcodes headless=True. Headless Firefox has no GL "
    "context, which is why the two webgl prefs above are forced; a webgl entry here "
    "is produced under those forced prefs, not under a shipped headful session",
]

CAVEAT_LOGGED_OUT = (
    "Logged out, instagram.com and threads.net serve a login wall. A surface set "
    "collected there may describe the wall's bundle rather than the application. "
    "An empty set does not mean the site reads nothing."
)


def _sha256(p):
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def provenance():
    binary = harness.default_binary()
    p = Path(binary)
    if not p.is_file():
        raise SystemExit(
            f"binary not found: {binary}\n"
            "harness.py:3's BIN_DEFAULT points at /tmp/cfx_sync4, which no longer "
            "exists on any current host. Set CFX_BIN to the extracted build."
        )
    out = {
        "binary": binary,
        "binary_sha256": _sha256(p),
        "build_run_id": os.environ.get("CFX_BUILD_RUN", "unset"),
        "launch_differs_from_shipped": LAUNCH_DIFFERS_FROM_SHIPPED,
    }
    # The launched binary is a ~72KB launcher stub on macOS; hashing it alone does
    # not identify a build, since the stub can be byte-identical across builds whose
    # patched C++ differs. Hash the payload beside it as well.
    for name in ("XUL", "libxul.so", "xul.dll"):
        payload = p.parent / name
        if payload.is_file():
            out["payload"] = name
            out["payload_sha256"] = _sha256(payload)
            break
    else:
        out["payload"] = "not found beside the binary -- provenance is the stub only"
    return out


def measure(url):
    """One target, one fresh Session.

    The fresh Session is load-bearing, not hygiene: harness.py:93-96 reads the
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
        "provenance": provenance(),
        "caveat": CAVEAT_LOGGED_OUT,
        "targets": [measure(url) for url in TARGETS],
    }
    assert len(out["targets"]) == len(TARGETS)
    blob = json.dumps(out, indent=2)
    (HERE / "recon_fb_live.json").write_text(blob)
    print(blob)


main()
