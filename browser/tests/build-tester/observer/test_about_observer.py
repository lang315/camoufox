"""about:observer: absent when disarmed, lists what the observer saw when armed,
and unreachable from web content either way (additions-register-no-new-chrome-package).
"""
import json
import time
from pathlib import Path
import harness

HERE = Path(__file__).parent
PAGE_FILE = "resource://gre/modules/AboutObserver.html"
MISSING_FILE = "resource://gre/modules/NoSuchObserverFile.html"


def open_tab(s, url):
    s.m.navigate(url)
    time.sleep(2.5)


def disarmed():
    with harness.serve(HERE) as port, harness.Session(arm=False) as s:
        errs = {}
        for name in ("observer", "doesnotexist"):
            try:
                s.m.navigate(f"about:{name}")
                errs[name] = "loaded"
            except Exception as e:
                errs[name] = str(e).split("\n")[0].replace(name, "<name>")
        with s.m.using_context("chrome"):
            contract = s.m.execute_script(
                "return '@mozilla.org/network/protocol/about;1?what=observer' in Cc;"
            )
    print("disarmed:", errs, "| about:observer contract registered:", contract)
    assert not contract, "disarmed: the about:observer contract is registered"
    assert errs["observer"] == errs["doesnotexist"], errs
    assert "malformedURI" in errs["observer"], errs
    print("PASS: disarmed, about:observer fails like an unknown about: page")


def armed():
    with harness.serve(HERE) as port, harness.Session(arm=True) as s:
        s.navigate(f"http://127.0.0.1:{port}/probe_all_surfaces.html")
        s.wait_done(30)
        s.snapshot()
        open_tab(s, "about:observer")
        rows = s.m.execute_script(
            "return [...document.querySelectorAll('#rows tr')].map(tr => [...tr.cells].slice(0, 3).map(c => c.textContent)"
            ".concat(tr.querySelector('summary').textContent));"
        )
        print("armed rows:", rows)
        mine = [r for r in rows if r[0] == "127.0.0.1"]
        assert mine, f"no row for the probe page's site: {rows}"
        assert {"canvas", "screen"} <= set(mine[0][2].split(", ")), mine
        assert int(mine[0][3]) >= 1, mine
        assert "touched or not touched" in s.m.execute_script("return document.body.innerText"), "caveat missing"
        raw = json.loads(s.m.execute_script("return document.getElementById('raw').textContent"))
        assert any(r["key"]["site"] == "127.0.0.1" for r in raw)
        with s.m.using_context("chrome"):
            who = s.m.execute_script(
                "const b = gBrowser.selectedBrowser;"
                "return {remoteType: b.remoteType, origin: b.contentPrincipal.origin, system: b.contentPrincipal.isSystemPrincipal};"
            )
        print("armed page runs as:", who)
        assert not who["system"], f"about:observer has the system principal: {who}"
        print("PASS: armed, about:observer lists the page's site with canvas and screen and its requests")

        s.navigate(f"http://127.0.0.1:{port}/about_observer_reach.html")
        real = [f"about:observer", PAGE_FILE]
        control = ["about:doesnotexist", MISSING_FILE]
        for (r, c) in zip(real, control):
            res = s.m.execute_async_script(
                "const done = arguments[arguments.length - 1];"
                "window.wrappedJSObject.__reach(arguments[0], arguments[1]).then(v => done(JSON.parse(JSON.stringify(v))));",
                script_args=[r, c],
            )
            print(f"reach {r}  vs control {c}:")
            for how, v in res.items():
                norm = lambda x: x["message"].replace(r, "<url>").replace(c, "<url>")
                same = (v["real"]["type"], norm(v["real"])) == (v["control"]["type"], norm(v["control"]))
                print(f"  {how:7s} real={v['real']['type']}: {norm(v['real'])!r}  control={v['control']['type']}: {norm(v['control'])!r}  same={same}")
                assert same, f"{how} {r}: {v}"
            for how, v in res.items():
                assert v["real"]["type"] != "ok", f"{how} reached {r}"
        navigate = {}
        for url in ("about:observer", "about:doesnotexist"):
            s.navigate(f"http://127.0.0.1:{port}/about_observer_reach.html")
            outcome = s.m.execute_script(
                "try { window.wrappedJSObject.location = arguments[0]; return 'no error'; }"
                " catch (e) { return e.name + ': ' + e.message; }",
                script_args=[url],
            )
            time.sleep(1.5)
            stayed = s.m.get_url().startswith("http://127.0.0.1")
            navigate[url] = (outcome.replace(url, "<url>"), stayed)
            print(f"location = {url!r}: {outcome!r}, stayed on the page: {stayed}")
        assert navigate["about:observer"] == navigate["about:doesnotexist"], navigate
        assert navigate["about:observer"][1], "navigated to about:observer"
        print("PASS: web content fails to reach about:observer or its file exactly as it fails for a made-up name")


disarmed()
armed()
