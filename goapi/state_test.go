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

func TestStateSnapshot(t *testing.T) {
	if os.Getenv("CAMOUFOX_BIN") == "" {
		t.Skip("set CAMOUFOX_BIN to run")
	}

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte(`<html><head><title>State Test</title></head><body>hello</body></html>`))
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

	if err := p.Goto(ctx, srv.URL, camoufox.GotoOptions{WaitUntil: camoufox.WaitUntilLoad}); err != nil {
		t.Fatalf("goto: %v", err)
	}

	st, err := p.StateSnapshot(ctx)
	if err != nil {
		t.Fatalf("StateSnapshot: %v", err)
	}

	if st.URL == "" {
		t.Error("URL should not be empty")
	}
	if st.Title != "State Test" {
		t.Errorf("title: expected 'State Test', got %q", st.Title)
	}
	if st.ReadyState == "" {
		t.Error("ReadyState should not be empty")
	}
	if st.FrameCount < 1 {
		t.Errorf("FrameCount expected >= 1, got %d", st.FrameCount)
	}
	if st.Timestamp.IsZero() {
		t.Error("Timestamp should not be zero")
	}
}
