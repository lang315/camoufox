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

func TestElementBoundingBox(t *testing.T) {
	if os.Getenv("CAMOUFOX_BIN") == "" {
		t.Skip("set CAMOUFOX_BIN to run")
	}

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte(`<html><body style="margin:0;padding:0">` +
			`<div id="box" style="position:absolute;left:10px;top:20px;width:100px;height:50px;background:red"></div>` +
			`</body></html>`))
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

	el, err := p.QuerySelector(ctx, "#box")
	if err != nil || el == nil {
		t.Fatalf("querySelector: err=%v, el=%v", err, el)
	}

	box, err := el.BoundingBox(ctx)
	if err != nil {
		t.Fatalf("BoundingBox: %v", err)
	}
	if box.Width < 99 || box.Width > 101 {
		t.Errorf("expected width ~100, got %f", box.Width)
	}
	if box.Height < 49 || box.Height > 51 {
		t.Errorf("expected height ~50, got %f", box.Height)
	}
}
