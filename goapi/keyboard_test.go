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

func TestKeyboardShiftA(t *testing.T) {
	if os.Getenv("CAMOUFOX_BIN") == "" {
		t.Skip("set CAMOUFOX_BIN to run")
	}

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte(`<html><body><input id="inp" type="text"></body></html>`))
	}))
	defer srv.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	b, err := camoufox.Launch(ctx, camoufox.WithExecutablePath(os.Getenv("CAMOUFOX_BIN")), camoufox.WithHeadless(true))
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

	if err := p.Goto(ctx, srv.URL); err != nil {
		t.Fatalf("goto: %v", err)
	}

	if err := p.Focus(ctx, "#inp"); err != nil {
		t.Fatalf("focus: %v", err)
	}

	kb := p.Keyboard()
	if err := kb.Down(ctx, "Shift"); err != nil {
		t.Fatalf("shift down: %v", err)
	}
	if err := kb.Press(ctx, "KeyA"); err != nil {
		t.Fatalf("press KeyA: %v", err)
	}
	if err := kb.Up(ctx, "Shift"); err != nil {
		t.Fatalf("shift up: %v", err)
	}

	val, err := p.Evaluate(ctx, "document.getElementById('inp').value")
	if err != nil {
		t.Fatalf("evaluate: %v", err)
	}
	if s, _ := val.(string); s != "A" {
		t.Errorf("expected input.value == %q, got %q", "A", s)
	}
}
