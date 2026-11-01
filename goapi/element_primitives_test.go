package camoufox_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
)

const elementPrimitivesPage = `<html><body>
<div id="outer"><span id="inner">in</span></div>
<span id="sibling">out</span>
<iframe id="frame" srcdoc="<p id='framed'>framed</p>"></iframe>
</body></html>`

func TestElementPrimitives(t *testing.T) {
	bin := browserBinary(t)

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte(elementPrimitivesPage))
	}))
	defer srv.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()
	b, err := camoufox.Launch(ctx, camoufox.WithExecutablePath(bin), camoufox.WithHeadless(true),
		camoufox.WithMainWorldEval(true))
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

	t.Run("EvaluateElement returns a handle for a node", func(t *testing.T) {
		el, err := p.EvaluateElement(ctx, `document.getElementById("outer")`)
		if err != nil || el == nil {
			t.Fatalf("EvaluateElement(node) = %v, %v; want a handle", el, err)
		}
		if got, err := el.GetAttribute(ctx, "id"); err != nil || got != "outer" {
			t.Errorf("handle id = %q, %v; want outer", got, err)
		}
	})

	for _, expr := range []string{`null`, `undefined`, `document.getElementById("nope")`} {
		t.Run("EvaluateElement "+expr+" returns nil", func(t *testing.T) {
			el, err := p.EvaluateElement(ctx, expr)
			if err != nil || el != nil {
				t.Errorf("EvaluateElement(%s) = %v, %v; want nil, nil", expr, el, err)
			}
		})
	}

	t.Run("EvaluateElement rejects a number", func(t *testing.T) {
		el, err := p.EvaluateElement(ctx, `42`)
		if err == nil || el != nil {
			t.Errorf("EvaluateElement(42) = %v, %v; want an error", el, err)
		}
	})

	t.Run("EvaluateElement rejects a non-node object", func(t *testing.T) {
		el, err := p.EvaluateElement(ctx, `({id: "outer"})`)
		if err == nil || el != nil {
			t.Errorf("EvaluateElement(object) = %v, %v; want an error", el, err)
		}
	})

	t.Run("EvaluateElement rejects a main-world expression", func(t *testing.T) {
		el, err := p.EvaluateElement(ctx, `mw:document.body`)
		if err == nil || el != nil || !strings.Contains(err.Error(), "main world") {
			t.Errorf("EvaluateElement(mw:) = %v, %v; want an error naming the main world", el, err)
		}
	})

	t.Run("EvaluateElement rejects a node of an iframe's document", func(t *testing.T) {
		if _, err := p.Evaluate(ctx, `new Promise(r => { const f = document.getElementById("frame"); f.contentDocument.readyState === "complete" ? r(1) : f.addEventListener("load", () => r(1)); })`); err != nil {
			t.Fatalf("wait for iframe: %v", err)
		}
		el, err := p.EvaluateElement(ctx, `document.getElementById("frame").contentDocument.getElementById("framed")`)
		if err == nil || el != nil || !strings.Contains(err.Error(), "document") {
			t.Errorf("EvaluateElement(iframe node) = %v, %v; want an error naming the document", el, err)
		}
	})

	t.Run("ElementHandle.Evaluate passes the element as the first argument", func(t *testing.T) {
		el, err := p.QuerySelector(ctx, "#outer")
		if err != nil || el == nil {
			t.Fatalf("query: %v, %v", el, err)
		}
		v, err := el.Evaluate(ctx, `el => el.id`)
		if err != nil || v != "outer" {
			t.Errorf("Evaluate(el => el.id) = %v, %v; want outer", v, err)
		}
		v, err = el.Evaluate(ctx, `function(el) { return el.children.length; }`)
		if err != nil || v != float64(1) {
			t.Errorf("Evaluate(children.length) = %v, %v; want 1", v, err)
		}
	})

	t.Run("ElementHandle.QuerySelector stays inside the element", func(t *testing.T) {
		outer, err := p.QuerySelector(ctx, "#outer")
		if err != nil || outer == nil {
			t.Fatalf("query: %v, %v", outer, err)
		}
		child, err := outer.QuerySelector(ctx, "#inner")
		if err != nil || child == nil {
			t.Fatalf("QuerySelector(#inner) = %v, %v; want a handle", child, err)
		}
		if got, err := child.TextContent(ctx); err != nil || got != "in" {
			t.Errorf("child text = %q, %v; want in", got, err)
		}
		sib, err := outer.QuerySelector(ctx, "#sibling")
		if err != nil || sib != nil {
			t.Errorf("QuerySelector(#sibling) = %v, %v; want nil, nil", sib, err)
		}
	})
}
