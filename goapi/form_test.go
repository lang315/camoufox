package camoufox_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
)

func TestFillForm(t *testing.T) {
	if os.Getenv("CAMOUFOX_BIN") == "" {
		t.Skip("set CAMOUFOX_BIN to run")
	}

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte(`<html><body>
<form>
  <label for="name">Name</label>
  <input id="name" name="name" type="text">
  <input placeholder="Email" type="email" id="email">
</form>
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

	n, err := p.FillForm(ctx, map[string]string{
		"Name":  "Alice",
		"Email": "a@b.com",
	})
	if err != nil {
		t.Fatalf("FillForm: %v", err)
	}
	if n != 2 {
		t.Errorf("expected 2 fields filled, got %d", n)
	}

	nameVal, err := p.Evaluate(ctx, `document.getElementById('name').value`)
	if err != nil {
		t.Fatalf("evaluate name: %v", err)
	}
	if nameVal != "Alice" {
		t.Errorf("name: expected 'Alice', got %v", nameVal)
	}

	emailVal, err := p.Evaluate(ctx, `document.getElementById('email').value`)
	if err != nil {
		t.Fatalf("evaluate email: %v", err)
	}
	if emailVal != "a@b.com" {
		t.Errorf("email: expected 'a@b.com', got %v", emailVal)
	}
}

