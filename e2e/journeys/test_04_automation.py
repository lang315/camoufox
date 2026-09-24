"""Journey 4: the things a scraper does all day: sign in, browse an SPA,
upload, download, cross-origin frames, popups and dialogs."""

import hashlib
import json
from urllib.parse import parse_qs

import pytest

from oracle.docs import cite
from util import wait_for, wait_out
from web.server import DOWNLOAD_SHA


def posts(site, path):
    return [r for r in site.seen(path) if r["method"] == "POST"]


@pytest.mark.parametrize("humanize", [False, True], ids=["plain", "humanize"])
def test_sign_in_and_shop(drv, site, humanize, check):
    print(cite("trusted_input"), cite("humanize") if humanize else "")
    b = drv.launch(humanize=humanize)
    ctx = b.new_context()
    page = ctx.new_page()

    page.goto(site.url("/login"))
    before = len(posts(site, "/login"))
    page.click("#go")
    check("required" in page.eval("document.getElementById('err').textContent"), "empty form stopped by validation")
    check(len(posts(site, "/login")) == before, "nothing was posted")

    page.type("#user", "alice")
    page.type("#pass", "s3cret")
    page.click("#go")
    wait_for(page, "location.pathname === '/account'")
    check(page.eval("document.getElementById('welcome').textContent") == "Welcome alice", "signed in")
    trusted = json.loads(parse_qs(posts(site, "/login")[-1]["body"].decode())["trusted"][0])
    check(trusted["n"] > 0 and trusted["all"], f"every input event the page saw was isTrusted ({trusted})")
    check(any(c["name"] == "session" for c in ctx.cookies()), "session cookie stored in the context")

    carts = len(site.seen("/shop/cart"))
    page.goto(site.url("/shop"))
    page.hover("#menu")
    check(page.eval("!document.getElementById('cart-link').hidden"), "hover opened the menu")
    target = page.eval("document.querySelectorAll('.item').length + 5")  # exists only after scrolling
    wait_for(page, f"(window.scrollTo(0, document.body.scrollHeight), !!document.querySelector('.add[data-id=\"{target}\"]'))")
    page.click(f'.add[data-id="{target}"]')
    page.click("#cart-link")
    wait_for(page, "location.pathname === '/shop/cart'")
    check(f"Item {target}" in page.eval("document.getElementById('cart').textContent"), "the item is in the cart")
    check(len(site.seen("/shop/cart")) == carts, "the SPA route change made no request")
    b.close()
    check.done()


def test_upload_and_download(drv, site, tmp_path, check):
    f = tmp_path / "hello.txt"
    f.write_bytes(b"e2e upload " * 1000)
    b = drv.launch()
    page = b.new_context().new_page()
    page.goto(site.url("/upload"))
    page.upload("#file", f)
    page.click("#send")
    got = wait_out(page)
    check(got == [{"name": "hello.txt", "sha256": hashlib.sha256(f.read_bytes()).hexdigest()}], f"server received {got}")
    page.goto(site.url("/download"))
    data = page.download("#dl")
    check(hashlib.sha256(data).hexdigest() == DOWNLOAD_SHA, f"downloaded {len(data)} bytes with the served hash")
    b.close()
    check.done()


def frames(driver, site):
    b = driver.launch(headless=True)
    page = b.new_context().new_page()
    page.on_dialog("e2e")
    page.goto(site.url("/frames"))
    page.click("#pop")
    page.click("#dialogs")
    got = wait_out(page)
    b.close()
    return got


def test_frames_popups_and_dialogs_match_reference(drv, ref, site, check):
    got, want = frames(drv, site), frames(ref, site)
    print(f"camoufox: {got}\nreference: {want}")
    check(got == want, "same outcome as Playwright's Firefox (oracle B)")
    check(got["child"]["origin"] == site.url2("").rstrip("/"), "the child frame is cross-origin")
    check(got["dialogs"] == {"alert": True, "confirm": True, "prompt": "e2e"}, "dialogs answered as asked")
    check.done()


def test_evaluate_is_invisible_to_the_page(drv, site, check):
    print(cite("isolated_eval"))
    b = drv.launch()
    page = b.new_context().new_page()
    page.goto(site.url("/"))
    page.eval("window.__e2e_probe = 1; document.documentElement.dataset.fromEval = '1'")
    page.click("#peek")
    got = wait_out(page)
    check(got["attr"] == "1", "control: the evaluate ran in this document (it changed the DOM)")
    check(got["probe"] == "undefined", f"the page cannot see the evaluate's global (typeof = {got['probe']!r})")
    b.close()
    check.done()
