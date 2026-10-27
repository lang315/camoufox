package camoufox_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
)

func TestWatchMutations(t *testing.T) {
	bin := browserBinary(t)

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte(`<html><body>
<div id="container"></div>
<script>
  setTimeout(function() {
    var d = document.createElement('div');
    d.id = 'added';
    d.textContent = 'hello';
    document.getElementById('container').appendChild(d);
  }, 100);
</script>
</body></html>`))
	}))
	defer srv.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	b, err := camoufox.Launch(ctx,
		camoufox.WithExecutablePath(bin),
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

	if err := p.Goto(ctx, srv.URL, camoufox.GotoOptions{WaitUntil: camoufox.WaitUntilDOMContentLoaded}); err != nil {
		t.Fatalf("goto: %v", err)
	}

	ch, cancelWatch, err := p.WatchMutations(ctx, "", camoufox.MutationOptions{
		ChildList: true,
		Subtree:   true,
	})
	if err != nil {
		t.Fatalf("WatchMutations: %v", err)
	}
	defer cancelWatch()

	select {
	case m := <-ch:
		if m.Type != "childList" {
			t.Errorf("expected childList mutation, got %q", m.Type)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("timed out waiting for mutation")
	}
}
