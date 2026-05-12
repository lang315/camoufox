package camoufox_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"sync"
	"testing"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
)

func TestDialogDismiss(t *testing.T) {
	if os.Getenv("CAMOUFOX_BIN") == "" {
		t.Skip("set CAMOUFOX_BIN to run")
	}

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte(`<html><body><script>alert('hello');</script></body></html>`))
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

	var wg sync.WaitGroup
	wg.Add(1)
	var gotDialog *camoufox.Dialog
	sub := p.OnDialog(func(d *camoufox.Dialog) {
		gotDialog = d
		_ = d.Dismiss(ctx)
		wg.Done()
	})
	defer p.Off(sub)

	// Goto blocks on load; alert() prevents load from firing — run in goroutine.
	go func() {
		_ = p.Goto(ctx, srv.URL, camoufox.GotoOptions{WaitUntil: camoufox.WaitUntilLoad, Timeout: 10 * time.Second})
	}()

	done := make(chan struct{})
	go func() { wg.Wait(); close(done) }()
	select {
	case <-done:
	case <-time.After(10 * time.Second):
		t.Fatal("dialog handler never fired")
	}

	if gotDialog == nil {
		t.Fatal("expected dialog, got nil")
	}
	if gotDialog.Type != "alert" {
		t.Errorf("expected type alert, got %q", gotDialog.Type)
	}
	if gotDialog.Message != "hello" {
		t.Errorf("expected message %q, got %q", "hello", gotDialog.Message)
	}
}
