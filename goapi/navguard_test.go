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

func TestNavigateGuarded_success(t *testing.T) {
	if os.Getenv("CAMOUFOX_BIN") == "" {
		t.Skip("set CAMOUFOX_BIN to run")
	}

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte(`<html><head><title>Landing</title></head><body>ok</body></html>`))
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

	err = p.NavigateGuarded(ctx, srv.URL, camoufox.NavGuardOptions{
		ExpectedURLs: []string{srv.URL},
		MaxAttempts:  1,
	})
	if err != nil {
		t.Fatalf("NavigateGuarded: %v", err)
	}
}

func TestNavigateGuarded_botwall(t *testing.T) {
	if os.Getenv("CAMOUFOX_BIN") == "" {
		t.Skip("set CAMOUFOX_BIN to run")
	}

	calls := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		calls++
		if calls == 1 {
			// First visit: bot wall page.
			_, _ = w.Write([]byte(`<html><head><title>Just a moment...</title></head><body>checking</body></html>`))
		} else {
			// Second visit: real page.
			_, _ = w.Write([]byte(`<html><head><title>Landing</title></head><body>ok</body></html>`))
		}
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

	err = p.NavigateGuarded(ctx, srv.URL, camoufox.NavGuardOptions{
		BotWallTitles: []string{"Just a moment..."},
		MaxAttempts:   3,
		Backoff:       10 * time.Millisecond,
	})
	if err != nil {
		t.Fatalf("NavigateGuarded botwall: %v", err)
	}
}
