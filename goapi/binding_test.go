package camoufox_test

import (
	"context"
	"encoding/json"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
)

// A binding lives in the isolated world, which page script cannot see, so
// page script reaches it through a CustomEvent on document. bindingScript
// reports each new document and relays the events.
const bindingScript = `window.report('doc:' + location.host);
document.addEventListener('goapi-ev', function (e) { window.report(e.detail); });`

// bindingPage fires "page:<typeof window.report>" when it loads and, on a click
// of #b, "click:<host>" to the first binding and "other:<host>" to the second.
const bindingPage = `<html><body>
<button id="b" onclick="document.dispatchEvent(new CustomEvent('goapi-ev', {detail: 'click:' + location.host}));
  document.dispatchEvent(new CustomEvent('goapi-ev2', {detail: 'other:' + location.host}))">b</button>
<script>document.dispatchEvent(new CustomEvent('goapi-ev', {detail: 'page:' + typeof window.report}));</script>
</body></html>`

func bindingServer(t *testing.T) *httptest.Server {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte(bindingPage))
	}))
	t.Cleanup(srv.Close)
	return srv
}

func hostOf(url string) string {
	return strings.TrimSuffix(strings.TrimPrefix(url, "http://"), "/")
}

// localhostURL is the same server under the name "localhost": another origin,
// so a navigation to it is cross-origin.
func localhostURL(t *testing.T, srv *httptest.Server) string {
	t.Helper()
	_, port, err := net.SplitHostPort(hostOf(srv.URL))
	if err != nil {
		t.Fatal(err)
	}
	return "http://localhost:" + port + "/"
}

func bindingPageFor(t *testing.T, opts ...camoufox.Option) (context.Context, *camoufox.BrowserContext, *camoufox.Page) {
	t.Helper()
	bin := browserBinary(t)
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	t.Cleanup(cancel)
	b, err := camoufox.Launch(ctx, append([]camoufox.Option{camoufox.WithExecutablePath(bin), camoufox.WithHeadless(true)}, opts...)...)
	if err != nil {
		t.Fatalf("launch: %v", err)
	}
	t.Cleanup(func() { b.Close() })
	bc, err := b.NewContext(ctx)
	if err != nil {
		t.Fatalf("context: %v", err)
	}
	p, err := bc.NewPage(ctx)
	if err != nil {
		t.Fatalf("page: %v", err)
	}
	t.Cleanup(func() { p.Close(ctx) })
	return ctx, bc, p
}

func gotoLoad(t *testing.T, ctx context.Context, p *camoufox.Page, url string) {
	t.Helper()
	if err := p.Goto(ctx, url, camoufox.GotoOptions{WaitUntil: camoufox.WaitUntilLoad}); err != nil {
		t.Fatalf("goto %s: %v", url, err)
	}
}

func expectPayload(t *testing.T, ch <-chan string, want string) {
	t.Helper()
	deadline := time.After(10 * time.Second)
	for {
		select {
		case got := <-ch:
			if got == want {
				return
			}
		case <-deadline:
			t.Fatalf("no call with payload %q within 10s", want)
		}
	}
}

// expectPayloads waits until every wanted payload has arrived, in any order.
func expectPayloads(t *testing.T, ch <-chan string, wants ...string) {
	t.Helper()
	missing := map[string]bool{}
	for _, w := range wants {
		missing[w] = true
	}
	deadline := time.After(10 * time.Second)
	for len(missing) > 0 {
		select {
		case got := <-ch:
			delete(missing, got)
		case <-deadline:
			t.Fatalf("no call with payloads %v within 10s", missing)
		}
	}
}

func expectNothing(t *testing.T, ch <-chan string) {
	t.Helper()
	select {
	case got := <-ch:
		t.Fatalf("unexpected call with payload %q", got)
	case <-time.After(1500 * time.Millisecond):
	}
}

func collect() (chan string, func(string)) {
	ch := make(chan string, 64)
	return ch, func(s string) { ch <- s }
}

func TestExposeBindingReceivesScriptInitScriptAndPageEvent(t *testing.T) {
	ctx, _, p := bindingPageFor(t)
	srv := bindingServer(t)
	ch, fn := collect()
	cancel, err := p.ExposeBinding(ctx, "report", bindingScript, fn)
	if err != nil {
		t.Fatalf("ExposeBinding: %v", err)
	}
	defer cancel()
	if err := p.AddInitScript(ctx, `window.report('init:' + location.host)`); err != nil {
		t.Fatalf("AddInitScript: %v", err)
	}
	gotoLoad(t, ctx, p, srv.URL)
	host := hostOf(srv.URL)
	expectPayload(t, ch, "doc:"+host)  // the binding's own script
	expectPayload(t, ch, "init:"+host) // an init script of the same world
	if err := p.Click(ctx, "#b"); err != nil {
		t.Fatalf("click: %v", err)
	}
	expectPayload(t, ch, "click:"+host) // a main-world CustomEvent relayed by the script
}

func TestExposeBindingSurvivesReload(t *testing.T) {
	ctx, _, p := bindingPageFor(t)
	srv := bindingServer(t)
	ch, fn := collect()
	cancel, err := p.ExposeBinding(ctx, "report", bindingScript, fn)
	if err != nil {
		t.Fatalf("ExposeBinding: %v", err)
	}
	defer cancel()
	gotoLoad(t, ctx, p, srv.URL)
	host := hostOf(srv.URL)
	expectPayload(t, ch, "doc:"+host)
	if err := p.Reload(ctx); err != nil {
		t.Fatalf("reload: %v", err)
	}
	expectPayload(t, ch, "doc:"+host)
	if err := p.Click(ctx, "#b"); err != nil {
		t.Fatalf("click: %v", err)
	}
	expectPayload(t, ch, "click:"+host)
}

func TestExposeBindingSurvivesCrossOriginNavigation(t *testing.T) {
	ctx, _, p := bindingPageFor(t)
	srv := bindingServer(t)
	other := localhostURL(t, srv)
	ch, fn := collect()
	cancel, err := p.ExposeBinding(ctx, "report", bindingScript, fn)
	if err != nil {
		t.Fatalf("ExposeBinding: %v", err)
	}
	defer cancel()
	gotoLoad(t, ctx, p, srv.URL)
	expectPayload(t, ch, "doc:"+hostOf(srv.URL))
	gotoLoad(t, ctx, p, other)
	host := hostOf(other)
	expectPayload(t, ch, "doc:"+host)
	if err := p.Click(ctx, "#b"); err != nil {
		t.Fatalf("click: %v", err)
	}
	expectPayload(t, ch, "click:"+host)
}

func TestExposeBindingCancelStopsDelivery(t *testing.T) {
	ctx, _, p := bindingPageFor(t)
	srv := bindingServer(t)
	ch, fn := collect()
	cancel, err := p.ExposeBinding(ctx, "report", bindingScript, fn)
	if err != nil {
		t.Fatalf("ExposeBinding: %v", err)
	}
	gotoLoad(t, ctx, p, srv.URL)
	host := hostOf(srv.URL)
	if err := p.Click(ctx, "#b"); err != nil {
		t.Fatalf("click: %v", err)
	}
	expectPayload(t, ch, "click:"+host) // delivered before cancel
	cancel()
	if err := p.Click(ctx, "#b"); err != nil {
		t.Fatalf("click after cancel: %v", err)
	}
	expectNothing(t, ch)
}

func TestExposeBindingsOnOnePageDoNotCross(t *testing.T) {
	ctx, _, p := bindingPageFor(t)
	srv := bindingServer(t)
	reports, reportFn := collect()
	others, otherFn := collect()
	cancelReport, err := p.ExposeBinding(ctx, "report", bindingScript, reportFn)
	if err != nil {
		t.Fatalf("ExposeBinding report: %v", err)
	}
	defer cancelReport()
	otherScript := `document.addEventListener('goapi-ev2', function (e) { window.other(e.detail); });`
	cancelOther, err := p.ExposeBinding(ctx, "other", otherScript, otherFn)
	if err != nil {
		t.Fatalf("ExposeBinding other: %v", err)
	}
	defer cancelOther()
	gotoLoad(t, ctx, p, srv.URL)
	if err := p.Click(ctx, "#b"); err != nil {
		t.Fatalf("click: %v", err)
	}
	host := hostOf(srv.URL)
	expectPayload(t, reports, "click:"+host)
	expectPayload(t, others, "other:"+host)
	for len(reports) > 0 {
		if got := <-reports; strings.HasPrefix(got, "other:") {
			t.Fatalf("report received %q, a call to other", got)
		}
	}
	for len(others) > 0 {
		if got := <-others; !strings.HasPrefix(got, "other:") {
			t.Fatalf("other received %q, a call to report", got)
		}
	}
}

func TestExposeBindingRejectsEmptyAndDuplicateNames(t *testing.T) {
	ctx, _, p := bindingPageFor(t)
	_, fn := collect()
	if _, err := p.ExposeBinding(ctx, "", "", fn); err == nil {
		t.Fatal("empty name: want an error")
	}
	cancel, err := p.ExposeBinding(ctx, "report", "", fn)
	if err != nil {
		t.Fatalf("ExposeBinding: %v", err)
	}
	if _, err := p.ExposeBinding(ctx, "report", "", fn); err == nil {
		t.Fatal("duplicate name: want an error")
	} else if !strings.Contains(err.Error(), "report") {
		t.Fatalf("duplicate error does not name the binding: %v", err)
	}
	// Juggler has no removeBinding, so a cancelled name stays bound in the page and stays taken.
	cancel()
	if _, err := p.ExposeBinding(ctx, "report", "", fn); err == nil {
		t.Fatal("a cancelled name is still bound in the page: want an error")
	}
}

// The stealth property: window[name] exists only in the isolated world. The
// isolated world's own reading is the control, and can differ from the page's.
func TestExposeBindingIsInvisibleToPageScript(t *testing.T) {
	ctx, _, p := bindingPageFor(t, camoufox.WithMainWorldEval(true))
	srv := bindingServer(t)
	ch, fn := collect()
	script := bindingScript + "\nwindow.report('iso:' + typeof window.report);"
	cancel, err := p.ExposeBinding(ctx, "report", script, fn)
	if err != nil {
		t.Fatalf("ExposeBinding: %v", err)
	}
	defer cancel()
	mwInit := `mw:document.dispatchEvent(new CustomEvent('goapi-ev', {detail: 'mwinit:' + typeof window.report}))`
	if err := p.AddInitScript(ctx, mwInit); err != nil {
		t.Fatalf("AddInitScript: %v", err)
	}
	gotoLoad(t, ctx, p, srv.URL)
	// The init script runs at document start, before the page's own script, so the order is not fixed.
	expectPayloads(t, ch,
		"iso:function",     // control: the isolated world sees it
		"page:undefined",   // page script does not
		"mwinit:undefined") // neither does a main-world init script
	if v, err := p.Evaluate(ctx, "mw:typeof window.report"); err != nil || v != "undefined" {
		t.Fatalf("mw: evaluate read %v, %v; want undefined", v, err)
	}
}

func TestSetBypassCSPLetsAPageReachALocalServer(t *testing.T) {
	ctx, bc, p := bindingPageFor(t)
	var hits atomic.Int64
	target := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		w.Header().Set("Access-Control-Allow-Origin", "*")
	}))
	defer target.Close()
	page := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		w.Header().Set("Content-Security-Policy", "connect-src 'none'")
		_, _ = w.Write([]byte(`<html><body><script>
fetch(` + "`" + target.URL + "`" + `).then(function () { document.title = 'reached'; },
  function () { document.title = 'blocked'; });
</script></body></html>`))
	}))
	defer page.Close()

	title := func() string {
		deadline := time.Now().Add(10 * time.Second)
		for time.Now().Before(deadline) {
			if v, err := p.Evaluate(ctx, "document.title"); err == nil && v != "" {
				return v.(string)
			}
			time.Sleep(100 * time.Millisecond)
		}
		return ""
	}
	gotoLoad(t, ctx, p, page.URL)
	if got := title(); got != "blocked" || hits.Load() != 0 {
		t.Fatalf("without bypass: title %q, server hits %d; want blocked and 0", got, hits.Load())
	}
	if err := bc.SetBypassCSP(ctx, true); err != nil {
		t.Fatalf("SetBypassCSP: %v", err)
	}
	gotoLoad(t, ctx, p, page.URL)
	if got := title(); got != "reached" || hits.Load() == 0 {
		t.Fatalf("with bypass: title %q, server hits %d; want reached and at least 1", got, hits.Load())
	}
}

// fhtool's bridge: a main-world init script dispatches a CustomEvent at once, and
// a capture listener the binding's script added in the isolated world relays it.
const relayScript = `document.addEventListener('goapi-ev', function (e) { window.report(String(e.detail)); }, true);`
const mwDispatch = `mw:document.dispatchEvent(new CustomEvent('goapi-ev', {detail: 'mw:' + location.host}))`

func TestExposeBindingRelaysAMainWorldCustomEventIntact(t *testing.T) {
	ctx, _, p := bindingPageFor(t, camoufox.WithMainWorldEval(true))
	srv := bindingServer(t)
	ch, fn := collect()
	cancel, err := p.ExposeBinding(ctx, "report", relayScript, fn)
	if err != nil {
		t.Fatalf("ExposeBinding: %v", err)
	}
	defer cancel()
	want := `step {"k":"v","n":[1,2]} "quoted" \u00fcn\u00ef`
	init := "mw:document.dispatchEvent(new CustomEvent('goapi-ev', {detail: " + jsLiteral(want) + "}))"
	if err := p.AddInitScript(ctx, init); err != nil {
		t.Fatalf("AddInitScript: %v", err)
	}
	gotoLoad(t, ctx, p, srv.URL)
	expectPayload(t, ch, want)
}

// By FrameTree.js, world ” bindings and their scripts run before world ”
// init scripts, and mw: scripts are world ” scripts: the first dispatch of a
// document is delivered, on the first document and after a reload and a
// cross-origin navigation.
func TestExposeBindingListenerIsInPlaceBeforeTheFirstMainWorldInitScript(t *testing.T) {
	ctx, _, p := bindingPageFor(t, camoufox.WithMainWorldEval(true))
	srv := bindingServer(t)
	other := localhostURL(t, srv)
	ch, fn := collect()
	cancel, err := p.ExposeBinding(ctx, "report", relayScript, fn)
	if err != nil {
		t.Fatalf("ExposeBinding: %v", err)
	}
	defer cancel()
	if err := p.AddInitScript(ctx, mwDispatch); err != nil {
		t.Fatalf("AddInitScript: %v", err)
	}
	gotoLoad(t, ctx, p, srv.URL)
	expectPayload(t, ch, "mw:"+hostOf(srv.URL))
	if err := p.Reload(ctx); err != nil {
		t.Fatalf("reload: %v", err)
	}
	expectPayload(t, ch, "mw:"+hostOf(srv.URL))
	gotoLoad(t, ctx, p, other)
	expectPayload(t, ch, "mw:"+hostOf(other))
}

// The control for the test above: a listener added late misses the dispatch,
// so that test can go red.
func TestExposeBindingALateListenerMissesTheMainWorldInitScript(t *testing.T) {
	ctx, _, p := bindingPageFor(t, camoufox.WithMainWorldEval(true))
	srv := bindingServer(t)
	ch, fn := collect()
	late := `setTimeout(function () { ` + relayScript + ` }, 1500);`
	cancel, err := p.ExposeBinding(ctx, "report", late, fn)
	if err != nil {
		t.Fatalf("ExposeBinding: %v", err)
	}
	defer cancel()
	if err := p.AddInitScript(ctx, mwDispatch); err != nil {
		t.Fatalf("AddInitScript: %v", err)
	}
	gotoLoad(t, ctx, p, srv.URL)
	time.Sleep(3 * time.Second)
	for len(ch) > 0 {
		if got := <-ch; strings.HasPrefix(got, "mw:") {
			t.Fatalf("a listener added after 1.5s received the init-time dispatch %q", got)
		}
	}
}

func jsLiteral(s string) string {
	b, _ := json.Marshal(s)
	return string(b)
}
