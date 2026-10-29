package camoufox_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
)

const popupSite = `<html><body>
<a id="blank" href="/child" target="_blank">blank</a>
<button id="open" onclick="window.open('/child')">open</button>
</body></html>`

func popupServer() *httptest.Server {
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		if r.URL.Path == "/child" {
			_, _ = w.Write([]byte(`<html><body>child</body></html>`))
			return
		}
		_, _ = w.Write([]byte(popupSite))
	}))
}

func launchPages(t *testing.T) (context.Context, *camoufox.Browser) {
	t.Helper()
	bin := browserBinary(t)
	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	t.Cleanup(cancel)
	b, err := camoufox.Launch(ctx, camoufox.WithExecutablePath(bin), camoufox.WithHeadless(true))
	if err != nil {
		t.Fatalf("launch: %v", err)
	}
	t.Cleanup(func() { _ = b.Close() })
	return ctx, b
}

func nextPage(t *testing.T, ch <-chan *camoufox.Page) *camoufox.Page {
	t.Helper()
	select {
	case p := <-ch:
		return p
	case <-time.After(15 * time.Second):
		t.Fatal("no OnPage call within 15 s")
		return nil
	}
}

func hasPage(bc *camoufox.BrowserContext, p *camoufox.Page) bool {
	for _, q := range bc.Pages() {
		if q == p {
			return true
		}
	}
	return false
}

func TestPopupsAppearInOnPageAndPages(t *testing.T) {
	srv := popupServer()
	defer srv.Close()
	ctx, b := launchPages(t)
	bc, err := b.NewContext(ctx)
	if err != nil {
		t.Fatal(err)
	}
	opener, err := bc.NewPage(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if got := bc.Pages(); len(got) != 1 || got[0] != opener {
		t.Fatalf("Pages() after NewPage = %d pages, want exactly the NewPage page", len(got))
	}
	seen := make(chan *camoufox.Page, 4)
	cancel := bc.OnPage(func(p *camoufox.Page) { seen <- p })
	defer cancel()
	if err := opener.Goto(ctx, srv.URL); err != nil {
		t.Fatal(err)
	}

	for _, sel := range []string{"#open", "#blank"} {
		if err := opener.Click(ctx, sel); err != nil {
			t.Fatalf("click %s: %v", sel, err)
		}
		popup := nextPage(t, seen)
		if popup == opener {
			t.Fatalf("%s: OnPage got the opener, not the popup", sel)
		}
		if !hasPage(bc, popup) {
			t.Errorf("%s: the popup is not in Pages()", sel)
		}
		// OnPage fires once the page's first document exists, which for a
		// popup is about:blank; the navigation to /child follows.
		var got any
		for end := time.Now().Add(10 * time.Second); time.Now().Before(end) && got != "child"; time.Sleep(50 * time.Millisecond) {
			got, err = popup.Evaluate(ctx, "document.body.innerText")
		}
		if err != nil || got != "child" {
			t.Errorf("%s: popup body = %v, %v; want child", sel, got, err)
		}
	}
	if len(seen) != 0 {
		t.Errorf("%d extra OnPage calls: a page was reported twice", len(seen))
	}
}

func TestClosedPopupLeavesPages(t *testing.T) {
	srv := popupServer()
	defer srv.Close()
	ctx, b := launchPages(t)
	bc, _ := b.NewContext(ctx)
	opener, err := bc.NewPage(ctx)
	if err != nil {
		t.Fatal(err)
	}
	seen := make(chan *camoufox.Page, 1)
	defer bc.OnPage(func(p *camoufox.Page) { seen <- p })()
	if err := opener.Goto(ctx, srv.URL); err != nil {
		t.Fatal(err)
	}
	if err := opener.Click(ctx, "#open"); err != nil {
		t.Fatal(err)
	}
	popup := nextPage(t, seen)
	if err := popup.Close(ctx); err != nil {
		t.Fatal(err)
	}
	deadline := time.Now().Add(10 * time.Second)
	for hasPage(bc, popup) && time.Now().Before(deadline) {
		time.Sleep(50 * time.Millisecond)
	}
	if hasPage(bc, popup) {
		t.Error("the closed popup is still in Pages()")
	}
	if !hasPage(bc, opener) {
		t.Error("the opener left Pages() when the popup closed")
	}
}

func TestNewPageAppearsOnceAndOnPageSeesIt(t *testing.T) {
	ctx, b := launchPages(t)
	bc, _ := b.NewContext(ctx)
	calls := make(chan *camoufox.Page, 4)
	defer bc.OnPage(func(p *camoufox.Page) { calls <- p })()
	p, err := bc.NewPage(ctx)
	if err != nil {
		t.Fatal(err)
	}
	n := 0
	for _, q := range bc.Pages() {
		if q == p {
			n++
		}
	}
	if n != 1 {
		t.Errorf("NewPage's page is in Pages() %d times, want 1", n)
	}
	if got := nextPage(t, calls); got != p {
		t.Error("OnPage got a different Page than NewPage returned")
	}
	time.Sleep(500 * time.Millisecond)
	if len(calls) != 0 {
		t.Errorf("%d extra OnPage calls for one NewPage", len(calls))
	}
}

func TestContextsDoNotCross(t *testing.T) {
	srv := popupServer()
	defer srv.Close()
	ctx, b := launchPages(t)
	a, _ := b.NewContext(ctx)
	other, _ := b.NewContext(ctx)
	pa, err := a.NewPage(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := other.NewPage(ctx); err != nil {
		t.Fatal(err)
	}
	seenA := make(chan *camoufox.Page, 4)
	seenOther := make(chan *camoufox.Page, 4)
	defer a.OnPage(func(p *camoufox.Page) { seenA <- p })()
	defer other.OnPage(func(p *camoufox.Page) { seenOther <- p })()
	if err := pa.Goto(ctx, srv.URL); err != nil {
		t.Fatal(err)
	}
	if err := pa.Click(ctx, "#open"); err != nil {
		t.Fatal(err)
	}
	popup := nextPage(t, seenA)
	if hasPage(other, popup) {
		t.Error("a popup of one context is in the other context's Pages()")
	}
	time.Sleep(500 * time.Millisecond)
	if len(seenOther) != 0 {
		t.Error("the other context's OnPage fired for a popup of the first")
	}
	if len(other.Pages()) != 1 {
		t.Errorf("other context holds %d pages, want 1", len(other.Pages()))
	}
}
