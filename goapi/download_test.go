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

func TestDownloadOnDownload(t *testing.T) {
	if os.Getenv("CAMOUFOX_BIN") == "" {
		t.Skip("set CAMOUFOX_BIN to run")
	}

	// Serve a plain-text attachment.
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/file.txt" {
			w.Header().Set("Content-Disposition", `attachment; filename="file.txt"`)
			w.Header().Set("Content-Type", "text/plain")
			_, _ = w.Write([]byte("download content"))
			return
		}
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte(`<html><body><a id="dl" href="/file.txt">dl</a></body></html>`))
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

	dlDir := t.TempDir()
	if err := bc.SetDownloadOptions(ctx, camoufox.DownloadOptions{
		Behavior:     "saveToDisk",
		DownloadsDir: dlDir,
	}); err != nil {
		t.Fatalf("SetDownloadOptions: %v", err)
	}

	p, err := bc.NewPage(ctx)
	if err != nil {
		t.Fatalf("page: %v", err)
	}
	defer p.Close(ctx)

	if err := p.Goto(ctx, srv.URL, camoufox.GotoOptions{WaitUntil: camoufox.WaitUntilLoad, Timeout: 10 * time.Second}); err != nil {
		t.Fatalf("goto: %v", err)
	}

	var (
		wg sync.WaitGroup
		dl *camoufox.Download
	)
	wg.Add(1)
	_ = bc.OnDownload(func(d *camoufox.Download) {
		dl = d
		wg.Done()
	})

	el, err := p.QuerySelector(ctx, "#dl")
	if err != nil || el == nil {
		t.Fatalf("QuerySelector: %v, el=%v", err, el)
	}
	if err := el.Click(ctx); err != nil {
		t.Fatalf("Click: %v", err)
	}

	created := make(chan struct{})
	go func() { wg.Wait(); close(created) }()
	select {
	case <-created:
	case <-time.After(10 * time.Second):
		t.Fatal("OnDownload never fired")
	}

	if dl.SuggestedFileName != "file.txt" {
		t.Errorf("SuggestedFileName=%q, want file.txt", dl.SuggestedFileName)
	}

	waitCtx, waitCancel := context.WithTimeout(ctx, 15*time.Second)
	defer waitCancel()
	if err := dl.Wait(waitCtx); err != nil {
		t.Fatalf("Wait: %v", err)
	}
}
