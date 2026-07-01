package camoufox_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
)

// TestSetInputFilesDirect tests branch A: direct SetInputFiles on an ElementHandle.
func TestSetInputFilesDirect(t *testing.T) {
	if os.Getenv("CAMOUFOX_BIN") == "" {
		t.Skip("set CAMOUFOX_BIN to run")
	}

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte(`<html><body><input id="f" type="file"></body></html>`))
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

	if err := p.Goto(ctx, srv.URL, camoufox.GotoOptions{WaitUntil: camoufox.WaitUntilLoad, Timeout: 10 * time.Second}); err != nil {
		t.Fatalf("goto: %v", err)
	}

	el, err := p.QuerySelector(ctx, "#f")
	if err != nil || el == nil {
		t.Fatalf("QuerySelector: %v, el=%v", err, el)
	}

	// Create a temporary file to "upload".
	tmp := filepath.Join(t.TempDir(), "upload.txt")
	if err := os.WriteFile(tmp, []byte("hello"), 0o600); err != nil {
		t.Fatalf("write temp: %v", err)
	}

	if err := el.SetInputFiles(ctx, []string{tmp}); err != nil {
		t.Fatalf("SetInputFiles: %v", err)
	}

	// Verify file name visible via JS.
	got, err := p.Evaluate(ctx, `document.getElementById('f').files[0].name`)
	if err != nil {
		t.Fatalf("Evaluate: %v", err)
	}
	if got != "upload.txt" {
		t.Errorf("expected files[0].name=upload.txt, got %v", got)
	}
}

// TestOnFileChooser tests branch B: OnFileChooser intercept. The playwright
// patch hooks HTMLInputElement::InitFilePicker so clicking an <input type=file>
// fires Page.fileChooserOpened instead of opening the native file dialog.
func TestOnFileChooser(t *testing.T) {
	if os.Getenv("CAMOUFOX_BIN") == "" {
		t.Skip("set CAMOUFOX_BIN to run")
	}

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte(`<html><body>
<input id="f" type="file">
<script>document.getElementById('f').addEventListener('click',function(){});</script>
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

	if err := p.Goto(ctx, srv.URL, camoufox.GotoOptions{WaitUntil: camoufox.WaitUntilLoad, Timeout: 10 * time.Second}); err != nil {
		t.Fatalf("goto: %v", err)
	}

	tmp := filepath.Join(t.TempDir(), "chosen.txt")
	if err := os.WriteFile(tmp, []byte("chosen"), 0o600); err != nil {
		t.Fatalf("write temp: %v", err)
	}

	var wg sync.WaitGroup
	wg.Add(1)
	sub := p.OnFileChooser(func(fc *camoufox.FileChooser) {
		defer wg.Done()
		if err := fc.SetFiles(ctx, []string{tmp}); err != nil {
			t.Errorf("SetFiles: %v", err)
		}
	})
	defer p.Off(sub)

	el, err := p.QuerySelector(ctx, "#f")
	if err != nil || el == nil {
		t.Fatalf("QuerySelector: %v, el=%v", err, el)
	}
	if err := el.Click(ctx); err != nil {
		t.Fatalf("Click: %v", err)
	}

	done := make(chan struct{})
	go func() { wg.Wait(); close(done) }()
	select {
	case <-done:
	case <-time.After(10 * time.Second):
		t.Fatal("fileChooser handler never fired")
	}
}
