package camoufox_test

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
)

// The page counts the events it sees on the body's dataset, which the isolated
// world reads, and keeps the button below the fold so a click needs a scroll.
const humanizePage = `<html><body style="margin:0">
<input id="i" style="margin:20px">
<div style="height:2500px"></div>
<button id="b" onclick="document.body.dataset.click = event.isTrusted">go</button>
<div style="height:600px"></div>
<script>
const count = (type) => addEventListener(type, (e) => { document.body.dataset[type] = +(document.body.dataset[type] || 0) + (e.isTrusted ? 1 : 1000) }, true);
['mousemove', 'wheel', 'keydown'].forEach(count);
</script></body></html>`

func humanizedRun(t *testing.T, h *camoufox.Humanize) map[string]string {
	t.Helper()
	bin := browserBinary(t)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte(humanizePage))
	}))
	defer srv.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()
	opts := []camoufox.Option{camoufox.WithExecutablePath(bin), camoufox.WithHeadless(true)}
	if h != nil {
		opts = append(opts, camoufox.WithHumanize(h))
	}
	b, err := camoufox.Launch(ctx, opts...)
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
	if err := p.Type(ctx, "#i", "hello world"); err != nil {
		t.Fatalf("type: %v", err)
	}
	if err := p.Click(ctx, "#b"); err != nil {
		t.Fatalf("click: %v", err)
	}
	v, err := p.Evaluate(ctx, `JSON.stringify({...document.body.dataset, value: document.getElementById('i').value, scrollY: scrollY})`)
	if err != nil {
		t.Fatalf("read page: %v", err)
	}
	out := map[string]string{}
	var m map[string]any
	if err := json.Unmarshal([]byte(v.(string)), &m); err != nil {
		t.Fatal(err)
	}
	for k, x := range m {
		out[k] = fmt.Sprint(x)
	}
	return out
}

// A humanized page types and clicks as a person does, and every event is trusted.
func TestHumanizeBrowser(t *testing.T) {
	seed := uint64(11)
	got := humanizedRun(t, &camoufox.Humanize{Seed: &seed})
	if got["value"] != "hello world" {
		t.Errorf("typed %q", got["value"])
	}
	if got["click"] != "true" {
		t.Errorf("the button's click was trusted: %q", got["click"])
	}
	for _, k := range []string{"mousemove", "wheel", "keydown"} {
		var n int
		fmt.Sscan(got[k], &n)
		if n < 5 || n >= 1000 {
			t.Errorf("%s: %q, want several trusted events and no synthetic one", k, got[k])
		}
	}
	if got["scrollY"] == "0" {
		t.Error("the click did not scroll the button into view")
	}
}

// Without WithHumanize a click is one mousemove, as before the option existed.
func TestHumanizeBrowserRawControl(t *testing.T) {
	got := humanizedRun(t, nil)
	if got["mousemove"] != "1" || got["wheel"] != "" {
		t.Errorf("raw: %q mousemove, %q wheel, want one move and no wheel", got["mousemove"], got["wheel"])
	}
}
