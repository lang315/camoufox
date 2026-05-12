package camoufox_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
)

func TestQueryResilient(t *testing.T) {
	if os.Getenv("CAMOUFOX_BIN") == "" {
		t.Skip("set CAMOUFOX_BIN to run")
	}

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte(`<html><body>
<button id="btn">Submit</button>
</body></html>`))
	}))
	defer srv.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	b, err := camoufox.Launch(ctx,
		camoufox.WithExecutablePath(os.Getenv("CAMOUFOX_BIN")),
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

	// Primary selector fails (non-existent), fallback by text succeeds.
	el, err := p.QueryResilient(ctx, []camoufox.Selector{
		{Kind: camoufox.KindCSS, Value: "#does-not-exist"},
		{Kind: camoufox.KindText, Value: "Submit"},
	})
	if err != nil {
		t.Fatalf("QueryResilient: %v", err)
	}
	if el == nil {
		t.Fatal("expected non-nil element")
	}
	text, err := el.TextContent(ctx)
	if err != nil {
		t.Fatalf("TextContent: %v", err)
	}
	if strings.TrimSpace(text) != "Submit" {
		t.Errorf("expected 'Submit', got %q", text)
	}
}
