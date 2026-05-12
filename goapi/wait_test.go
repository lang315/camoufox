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

func TestWaitForVisible(t *testing.T) {
	if os.Getenv("CAMOUFOX_BIN") == "" {
		t.Skip("set CAMOUFOX_BIN to run")
	}

	// Page that adds a visible element after 200ms.
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte(`<html><body>
<div id="late" style="display:none;width:100px;height:50px">present</div>
<script>setTimeout(function(){ document.getElementById('late').style.display='block'; }, 200);</script>
</body></html>`))
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

	el, err := p.WaitFor(ctx, "#late", camoufox.WaitForOptions{
		State:   camoufox.WaitVisible,
		Timeout: 5 * time.Second,
	})
	if err != nil {
		t.Fatalf("WaitFor: %v", err)
	}
	if el == nil {
		t.Fatal("expected ElementHandle, got nil")
	}
}
