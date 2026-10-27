package camoufox_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
)

func TestQueryXPath(t *testing.T) {
	bin := browserBinary(t)

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte(`<html><body>
<div data-id="a">x</div>
<div data-id="b">y</div>
</body></html>`))
	}))
	defer srv.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	b, err := camoufox.Launch(ctx,
		camoufox.WithExecutablePath(bin),
		camoufox.WithHeadless(true))
	if err != nil {
		t.Fatalf("launch: %v", err)
	}
	defer b.Close()

	bc, err := b.NewContext(ctx)
	if err != nil {
		t.Fatalf("context: %v", err)
	}
	p, err := bc.NewPage(ctx)
	if err != nil {
		t.Fatalf("page: %v", err)
	}
	defer p.Close(ctx)

	if err := p.Goto(ctx, srv.URL, camoufox.GotoOptions{WaitUntil: camoufox.WaitUntilDOMContentLoaded}); err != nil {
		t.Fatalf("goto: %v", err)
	}

	els, err := p.QueryXPath(ctx, `//div[@data-id='b']`)
	if err != nil {
		t.Fatalf("QueryXPath: %v", err)
	}
	if len(els) != 1 {
		t.Fatalf("expected 1 element, got %d", len(els))
	}

	// Verify it's the right element by reading its text content.
	text, err := els[0].TextContent(ctx)
	if err != nil {
		t.Fatalf("TextContent: %v", err)
	}
	if text != "y" {
		t.Errorf("expected text 'y', got %q", text)
	}
}
