// Example: configure download directory, register an OnDownload handler,
// click a link, and wait for the file to land on disk.
//
// Run: CAMOUFOX_BIN=/path/to/firefox go run ./example/download
package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"net/http/httptest"
	"os"
	"sync"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
)

func main() {
	exe := os.Getenv("CAMOUFOX_BIN")
	if exe == "" {
		log.Fatal("set CAMOUFOX_BIN to your camoufox firefox binary")
	}

	// Spin up a tiny HTTP server that serves a text attachment.
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/hello.txt" {
			w.Header().Set("Content-Disposition", `attachment; filename="hello.txt"`)
			w.Header().Set("Content-Type", "text/plain")
			_, _ = w.Write([]byte("Hello from camoufox download example!"))
			return
		}
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte(`<html><body><a id="dl" href="/hello.txt">Download</a></body></html>`))
	}))
	defer srv.Close()

	dlDir, err := os.MkdirTemp("", "camoufox-dl-*")
	if err != nil {
		log.Fatalf("tmp dir: %v", err)
	}
	defer os.RemoveAll(dlDir)

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	b, err := camoufox.Launch(ctx,
		camoufox.WithExecutablePath(exe),
		camoufox.WithHeadless(true),
		camoufox.WithDebug(os.Getenv("DEBUG") != ""),
	)
	if err != nil {
		log.Fatalf("launch: %v", err)
	}
	defer b.Close()

	bc, err := b.NewContext(ctx)
	if err != nil {
		log.Fatalf("new context: %v", err)
	}
	if err := bc.SetDownloadOptions(ctx, camoufox.DownloadOptions{
		Behavior:     "saveToDisk",
		DownloadsDir: dlDir,
	}); err != nil {
		log.Fatalf("SetDownloadOptions: %v", err)
	}

	p, err := bc.NewPage(ctx)
	if err != nil {
		log.Fatalf("new page: %v", err)
	}
	defer p.Close(ctx)

	var (
		wg sync.WaitGroup
		dl *camoufox.Download
	)
	wg.Add(1)
	_ = bc.OnDownload(func(d *camoufox.Download) {
		dl = d
		fmt.Printf("download started: %s (%s)\n", d.SuggestedFileName, d.URL)
		wg.Done()
	})

	if err := p.Goto(ctx, srv.URL, camoufox.GotoOptions{WaitUntil: camoufox.WaitUntilLoad}); err != nil {
		log.Fatalf("goto: %v", err)
	}

	el, err := p.QuerySelector(ctx, "#dl")
	if err != nil || el == nil {
		log.Fatalf("QuerySelector: %v, el=%v", err, el)
	}
	if err := el.Click(ctx); err != nil {
		log.Fatalf("Click: %v", err)
	}

	created := make(chan struct{})
	go func() { wg.Wait(); close(created) }()
	select {
	case <-created:
	case <-time.After(10 * time.Second):
		log.Fatal("timed out waiting for download to start")
	}

	waitCtx, waitCancel := context.WithTimeout(ctx, 15*time.Second)
	defer waitCancel()
	if err := dl.Wait(waitCtx); err != nil {
		log.Fatalf("Wait: %v", err)
	}
	fmt.Printf("download complete: %s\n", dl.Path())
}
