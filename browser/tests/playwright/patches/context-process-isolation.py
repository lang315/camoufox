"""
Verify Firefox gives each browser context its own web-content process.

Per-context values cached in a content process (fontconfig's family-name
memos, #941/#942, and any other process-wide cache keyed without a context)
leak across identities only when two contexts share one content process.
Firefox 158's SharedWeb pool keys the process by container and private mode,
which is why #942 was not needed on 158.

This guard asserts the property that makes the failure impossible: with the
default process pool, three contexts on one site load their pages in three
web-content processes. It asks the browser (ChromeUtils.requestProcInfo,
through Marionette) which process holds each context's page, so it reads the
same on Linux, macOS and Windows, and a preallocated or extension process
cannot stand in for a context's own. If a future Firefox merges the pools
again, this fails before a font, localStorage or identity leak can hide behind
shared renderer state.

    python browser/tests/playwright/patches/context-process-isolation.py
"""

import functools
import http.server
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import Marionette, free_port, launch_kwargs, marionette_args, marionette_env  # noqa: E402

CONTEXTS = 3
WAIT_S = 60
# Each child process's pid and the documents its windows hold.
PROCESSES = """return ChromeUtils.requestProcInfo().then(info => info.children.map(c => ({
  pid: c.pid, urls: c.windows.map(w => w.documentURI && w.documentURI.spec),
})));"""


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def page_processes(m: Marionette, urls: list[str]) -> dict[str, int]:
    """The pid of the process that holds each of `urls`, for those found."""
    found = {}
    for child in m.js(PROCESSES):
        for url in child["urls"]:
            if url in urls:
                found[url] = child["pid"]
    return found


def main() -> int:
    from camoufox.sync_api import Camoufox

    site = tempfile.mkdtemp()
    Path(site, "index.html").write_text("<!doctype html><meta charset=utf-8><body>isolation</body>", encoding="utf-8")
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(Quiet, directory=site)
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    # One site, so only the per-context pools keep the pages apart.
    urls = [f"http://127.0.0.1:{server.server_address[1]}/index.html?context={i}" for i in range(CONTEXTS)]

    port = free_port()
    try:
        with Camoufox(**launch_kwargs(args=marionette_args(), env=marionette_env(),
                                      firefox_user_prefs={"marionette.port": port},
                                      i_know_what_im_doing=True)) as browser:
            contexts = []
            for url in urls:
                context = browser.new_context()
                context.new_page().goto(url)
                contexts.append(context)

            m = Marionette(port)
            try:
                deadline = time.monotonic() + WAIT_S
                pids = page_processes(m, urls)
                while len(pids) < CONTEXTS and time.monotonic() < deadline:
                    time.sleep(0.25)
                    pids = page_processes(m, urls)
            finally:
                m.close()
    finally:
        server.shutdown()

    print(f"{CONTEXTS} contexts -> {pids}")
    if len(pids) < CONTEXTS:
        print(f"FAIL: the browser named a process for {len(pids)} of {CONTEXTS} pages within {WAIT_S} s")
        return 1
    if len(set(pids.values())) < CONTEXTS:
        print(
            f"FAIL: {CONTEXTS} contexts share {len(set(pids.values()))} web-content process(es); "
            "per-context state can leak through renderer caches"
        )
        return 1
    print("PASS: contexts use separate web-content processes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
