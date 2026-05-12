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

func TestLocalStorage(t *testing.T) {
	if os.Getenv("CAMOUFOX_BIN") == "" {
		t.Skip("set CAMOUFOX_BIN to run")
	}

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte(`<html><body>storage test</body></html>`))
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

	bc, _ := b.NewContext(ctx)
	p, _ := bc.NewPage(ctx)
	defer p.Close(ctx)

	if err := p.Goto(ctx, srv.URL, camoufox.GotoOptions{WaitUntil: camoufox.WaitUntilDOMContentLoaded}); err != nil {
		t.Fatalf("goto: %v", err)
	}

	// Set via Evaluate, read via LocalStorage.
	if _, err := p.Evaluate(ctx, `localStorage.setItem('foo', 'bar')`); err != nil {
		t.Fatalf("set localStorage: %v", err)
	}

	ls, err := p.LocalStorage(ctx)
	if err != nil {
		t.Fatalf("LocalStorage: %v", err)
	}
	if ls["foo"] != "bar" {
		t.Errorf("expected foo=bar, got %v", ls)
	}
}

func TestSetLocalStorage(t *testing.T) {
	if os.Getenv("CAMOUFOX_BIN") == "" {
		t.Skip("set CAMOUFOX_BIN to run")
	}

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte(`<html><body>storage test</body></html>`))
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

	bc, _ := b.NewContext(ctx)
	p, _ := bc.NewPage(ctx)
	defer p.Close(ctx)

	if err := p.Goto(ctx, srv.URL, camoufox.GotoOptions{WaitUntil: camoufox.WaitUntilDOMContentLoaded}); err != nil {
		t.Fatalf("goto: %v", err)
	}

	want := map[string]string{"alpha": "1", "beta": "2"}
	if err := p.SetLocalStorage(ctx, want); err != nil {
		t.Fatalf("SetLocalStorage: %v", err)
	}

	got, err := p.LocalStorage(ctx)
	if err != nil {
		t.Fatalf("LocalStorage: %v", err)
	}
	for k, v := range want {
		if got[k] != v {
			t.Errorf("key %q: expected %q, got %q", k, v, got[k])
		}
	}

	if err := p.ClearLocalStorage(ctx); err != nil {
		t.Fatalf("ClearLocalStorage: %v", err)
	}
	cleared, err := p.LocalStorage(ctx)
	if err != nil {
		t.Fatalf("LocalStorage after clear: %v", err)
	}
	if len(cleared) != 0 {
		t.Errorf("expected empty after clear, got %v", cleared)
	}
}
