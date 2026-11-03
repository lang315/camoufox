package camoufox_test

import (
	"context"
	"strings"
	"testing"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
)

// call is one delivery of a context binding: the page it came from and its payload.
type call struct {
	page    *camoufox.Page
	payload string
}

func collectCalls() (chan call, func(*camoufox.Page, string)) {
	ch := make(chan call, 64)
	return ch, func(p *camoufox.Page, s string) { ch <- call{p, s} }
}

func expectCall(t *testing.T, ch <-chan call, want string) call {
	t.Helper()
	deadline := time.After(10 * time.Second)
	for {
		select {
		case got := <-ch:
			if got.payload == want {
				return got
			}
		case <-deadline:
			t.Fatalf("no call with payload %q within 10s", want)
		}
	}
}

func TestContextExposeBindingReachesAPopupsFirstDocument(t *testing.T) {
	ctx, bc, p := bindingPageFor(t)
	srv := bindingServer(t)
	calls, fn := collectCalls()
	cancel, err := bc.ExposeBinding(ctx, "report", bindingScript, fn)
	if err != nil {
		t.Fatalf("ExposeBinding: %v", err)
	}
	defer cancel()
	popups := make(chan *camoufox.Page, 4)
	stop := bc.OnPage(func(q *camoufox.Page) { popups <- q })
	defer stop()

	gotoLoad(t, ctx, p, srv.URL)
	host := hostOf(srv.URL)
	if got := expectCall(t, calls, "doc:"+host); got.page != p {
		t.Fatalf("the opener's document was reported by %p, want the opener %p", got.page, p)
	}

	// The popup's binding script runs on its first document, before OnPage reports it.
	other := localhostURL(t, srv)
	if _, err := p.Evaluate(ctx, `window.open(`+"`"+other+"`"+`, '_blank'); true`); err != nil {
		t.Fatalf("window.open: %v", err)
	}
	var popup *camoufox.Page
	select {
	case popup = <-popups:
	case <-time.After(10 * time.Second):
		t.Fatal("OnPage never reported the popup")
	}
	if popup == p {
		t.Fatal("the popup is the opener")
	}
	got := expectCall(t, calls, "doc:"+hostOf(other))
	if got.page != popup {
		t.Fatalf("the popup's document was reported by %p, want the popup %p", got.page, popup)
	}
	if err := popup.Click(ctx, "#b"); err != nil {
		t.Fatalf("click in popup: %v", err)
	}
	if got := expectCall(t, calls, "click:"+hostOf(other)); got.page != popup {
		t.Fatalf("the popup's click was reported by %p, want the popup %p", got.page, popup)
	}
}

func TestContextExposeBindingReachesOpenAndLaterPages(t *testing.T) {
	ctx, bc, open := bindingPageFor(t)
	srv := bindingServer(t)
	calls, fn := collectCalls()
	cancel, err := bc.ExposeBinding(ctx, "report", bindingScript, fn)
	if err != nil {
		t.Fatalf("ExposeBinding: %v", err)
	}
	defer cancel()
	later, err := bc.NewPage(ctx)
	if err != nil {
		t.Fatalf("NewPage: %v", err)
	}
	defer later.Close(ctx)
	host := hostOf(srv.URL)
	gotoLoad(t, ctx, open, srv.URL)
	if got := expectCall(t, calls, "doc:"+host); got.page != open {
		t.Fatalf("the open page was reported by %p, want %p", got.page, open)
	}
	gotoLoad(t, ctx, later, srv.URL)
	for {
		got := expectCall(t, calls, "doc:"+host)
		if got.page == later {
			break
		}
	}
}

func TestContextExposeBindingStaysInItsContext(t *testing.T) {
	bin := browserBinary(t)
	ctx, stop := context.WithTimeout(context.Background(), 60*time.Second)
	defer stop()
	b, err := camoufox.Launch(ctx, camoufox.WithExecutablePath(bin), camoufox.WithHeadless(true))
	if err != nil {
		t.Fatalf("launch: %v", err)
	}
	defer b.Close()
	bound, err := b.NewContext(ctx)
	if err != nil {
		t.Fatalf("NewContext: %v", err)
	}
	other, err := b.NewContext(ctx)
	if err != nil {
		t.Fatalf("NewContext: %v", err)
	}
	srv := bindingServer(t)
	calls, fn := collectCalls()
	cancel, err := bound.ExposeBinding(ctx, "report", bindingScript, fn)
	if err != nil {
		t.Fatalf("ExposeBinding: %v", err)
	}
	defer cancel()
	q, err := other.NewPage(ctx)
	if err != nil {
		t.Fatalf("NewPage: %v", err)
	}
	gotoLoad(t, ctx, q, srv.URL)
	if err := q.Click(ctx, "#b"); err != nil {
		t.Fatalf("click: %v", err)
	}
	select {
	case got := <-calls:
		t.Fatalf("a page of another context delivered %q", got.payload)
	case <-time.After(1500 * time.Millisecond):
	}
}

func TestContextExposeBindingCancelStopsDelivery(t *testing.T) {
	ctx, bc, p := bindingPageFor(t)
	srv := bindingServer(t)
	calls, fn := collectCalls()
	cancel, err := bc.ExposeBinding(ctx, "report", bindingScript, fn)
	if err != nil {
		t.Fatalf("ExposeBinding: %v", err)
	}
	gotoLoad(t, ctx, p, srv.URL)
	host := hostOf(srv.URL)
	if err := p.Click(ctx, "#b"); err != nil {
		t.Fatalf("click: %v", err)
	}
	expectCall(t, calls, "click:"+host)
	cancel()
	if err := p.Click(ctx, "#b"); err != nil {
		t.Fatalf("click after cancel: %v", err)
	}
	select {
	case got := <-calls:
		t.Fatalf("delivery after cancel: %q", got.payload)
	case <-time.After(1500 * time.Millisecond):
	}
}

func TestContextExposeBindingRejectsEmptyAndTakenNames(t *testing.T) {
	ctx, bc, p := bindingPageFor(t)
	_, fn := collectCalls()
	if _, err := bc.ExposeBinding(ctx, "", "", fn); err == nil {
		t.Fatal("empty name: want an error")
	}
	if _, err := p.ExposeBinding(ctx, "onpage", "", func(string) {}); err != nil {
		t.Fatalf("page ExposeBinding: %v", err)
	}
	if _, err := bc.ExposeBinding(ctx, "onpage", "", fn); err == nil || !strings.Contains(err.Error(), "onpage") {
		t.Fatalf("a name bound on an open page: want an error naming it, got %v", err)
	}
	if _, err := bc.ExposeBinding(ctx, "onctx", "", fn); err != nil {
		t.Fatalf("first context binding: %v", err)
	}
	if _, err := bc.ExposeBinding(ctx, "onctx", "", fn); err == nil || !strings.Contains(err.Error(), "onctx") {
		t.Fatalf("a name already bound on the context: want an error naming it, got %v", err)
	}
	if _, err := p.ExposeBinding(ctx, "onctx", "", func(string) {}); err == nil || !strings.Contains(err.Error(), "onctx") {
		t.Fatalf("page binding of a context's name: want an error naming it, got %v", err)
	}
}
