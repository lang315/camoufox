"""The smallest journey: launch, open a page, read it back. If this fails, the driver is the problem."""


def test_open_a_page(drv, site):
    b = drv.launch()
    page = b.new_context().new_page()
    page.goto(site.url("/login"))
    assert page.eval("document.title") == "Sign in"
