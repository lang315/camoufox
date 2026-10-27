package camoufox_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"testing"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
)

func TestEvaluateMainWorld(t *testing.T) {
	bin := browserBinary(t)

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte(`<html><body><script>window.secret = 42;</script></body></html>`))
	}))
	defer srv.Close()

	open := func(t *testing.T, ctx context.Context, opts ...camoufox.Option) *camoufox.Page {
		t.Helper()
		opts = append([]camoufox.Option{
			camoufox.WithExecutablePath(bin),
			camoufox.WithHeadless(true),
		}, opts...)
		b, err := camoufox.Launch(ctx, opts...)
		if err != nil {
			t.Fatalf("launch: %v", err)
		}
		t.Cleanup(func() { _ = b.Close() })
		bc, err := b.NewContext(ctx)
		if err != nil {
			t.Fatalf("new context: %v", err)
		}
		p, err := bc.NewPage(ctx)
		if err != nil {
			t.Fatalf("new page: %v", err)
		}
		if err := p.Goto(ctx, srv.URL); err != nil {
			t.Fatalf("goto: %v", err)
		}
		return p
	}

	t.Run("disabled by default", func(t *testing.T) {
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		p := open(t, ctx)

		_, err := p.Evaluate(ctx, "mw:1")
		if err == nil || !strings.Contains(err.Error(), "Main world evaluation is disabled") {
			t.Fatalf(`Evaluate("mw:1") error = %v, want "Main world evaluation is disabled"`, err)
		}
	})

	t.Run("enabled", func(t *testing.T) {
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		p := open(t, ctx, camoufox.WithMainWorldEval(true))

		if v, err := p.Evaluate(ctx, "window.secret"); err != nil || v != nil {
			t.Errorf("isolated window.secret = %v, %v; want nil, nil", v, err)
		}
		if v, err := p.Evaluate(ctx, "mw:window.secret"); err != nil || v != float64(42) {
			t.Errorf("main-world window.secret = %v, %v; want 42, nil", v, err)
		}

		v, err := p.Evaluate(ctx, `mw:({n: window.secret, list: [1, "a", null], nested: {ok: true}})`)
		if err != nil {
			t.Fatalf("object round-trip: %v", err)
		}
		want := map[string]any{
			"n":      float64(42),
			"list":   []any{float64(1), "a", nil},
			"nested": map[string]any{"ok": true},
		}
		if !reflect.DeepEqual(v, want) {
			t.Errorf("object round-trip = %#v, want %#v", v, want)
		}

		v, err = p.Evaluate(ctx, `mw:(() => { const o = {a: 1}; return [o, o]; })()`)
		if wantShared := []any{map[string]any{"a": float64(1)}, map[string]any{"a": float64(1)}}; err != nil || !reflect.DeepEqual(v, wantShared) {
			t.Errorf("shared reference = %#v, %v; want %#v, nil", v, err, wantShared)
		}

		if v, err := p.Evaluate(ctx, `mw:(() => { const o = {}; o.self = o; return o; })()`); err == nil || !strings.Contains(err.Error(), "cycle") {
			t.Errorf("cyclic result = %#v, %v; want an error that names the cycle", v, err)
		}

		if v, err := p.Evaluate(ctx, "mw:Promise.resolve(window.secret)"); err != nil || v != float64(42) {
			t.Errorf("main-world promise = %v, %v; want 42, nil", v, err)
		}

		if _, err := p.Evaluate(ctx, `mw:(() => { throw new Error("boom") })()`); err == nil || !strings.Contains(err.Error(), "boom") {
			t.Errorf("throwing expression error = %v, want it to mention boom", err)
		}
	})
}
