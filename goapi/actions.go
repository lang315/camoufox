package camoufox

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"

	"github.com/lang315/camoufox/goapi/pkg/juggler"
)

// Click locates the first element matching the CSS selector and
// synthesizes a real mouse click at its center. Falls back to
// element.click() (DOM-level) if mouse coordinates can't be resolved.
func (p *Page) Click(ctx context.Context, selector string) error {
	frameID := p.MainFrameID()
	if frameID == "" {
		return errors.New("camoufox: Click: main frame not ready")
	}
	ctxID := p.executionContextID()
	if ctxID == "" {
		return errors.New("camoufox: Click: no execution context")
	}

	// Resolve the element and grab its center.
	expr := fmt.Sprintf(`(() => {
		const el = document.querySelector(%s);
		if (!el) return null;
		el.scrollIntoView({block: "center", inline: "center"});
		const r = el.getBoundingClientRect();
		return {x: r.left + r.width/2, y: r.top + r.height/2, found: true};
	})()`, jsString(selector))

	var res juggler.EvaluateResult
	err := p.session.Call(ctx, "Runtime.evaluate", juggler.EvaluateParams{
		ExecutionContextID: ctxID,
		Expression:         expr,
		ReturnByValue:      true,
	}, &res)
	if err != nil {
		return fmt.Errorf("camoufox: Click resolve %q: %w", selector, err)
	}
	if res.Result == nil || len(res.Result.Value) == 0 || string(res.Result.Value) == "null" {
		return fmt.Errorf("camoufox: Click: selector %q not found", selector)
	}
	var rect struct {
		X     float64 `json:"x"`
		Y     float64 `json:"y"`
		Found bool    `json:"found"`
	}
	if err := json.Unmarshal(res.Result.Value, &rect); err != nil {
		return fmt.Errorf("camoufox: Click decode: %w", err)
	}
	if !rect.Found {
		return fmt.Errorf("camoufox: Click: selector %q not found", selector)
	}
	return p.MouseClick(ctx, rect.X, rect.Y)
}

// MouseClick dispatches mousemove → mousedown → mouseup at the given
// viewport coordinates.
func (p *Page) MouseClick(ctx context.Context, x, y float64) error {
	one := 1
	move := juggler.PageDispatchMouseEventParams{
		Type: "mousemove", Button: 0, Buttons: 0, X: x, Y: y, Modifiers: 0,
	}
	down := juggler.PageDispatchMouseEventParams{
		Type: "mousedown", Button: 0, Buttons: 1, X: x, Y: y, Modifiers: 0,
		ClickCount: &one,
	}
	up := juggler.PageDispatchMouseEventParams{
		Type: "mouseup", Button: 0, Buttons: 0, X: x, Y: y, Modifiers: 0,
		ClickCount: &one,
	}
	for _, ev := range []juggler.PageDispatchMouseEventParams{move, down, up} {
		if err := p.session.Call(ctx, "Page.dispatchMouseEvent", ev, nil); err != nil {
			return fmt.Errorf("camoufox: dispatchMouseEvent %s: %w", ev.Type, err)
		}
	}
	return nil
}

// Focus runs element.focus() on the first matching element.
func (p *Page) Focus(ctx context.Context, selector string) error {
	expr := fmt.Sprintf(`(() => {
		const el = document.querySelector(%s);
		if (!el) return false;
		el.focus();
		return true;
	})()`, jsString(selector))
	v, err := p.Evaluate(ctx, expr)
	if err != nil {
		return err
	}
	if ok, _ := v.(bool); !ok {
		return fmt.Errorf("camoufox: Focus: selector %q not found", selector)
	}
	return nil
}

// Type focuses the element matching selector then inserts text via
// Page.insertText (one frame round-trip — fast but not keystroke-by-
// keystroke).
func (p *Page) Type(ctx context.Context, selector, text string) error {
	if err := p.Focus(ctx, selector); err != nil {
		return err
	}
	return p.session.Call(ctx, "Page.insertText", map[string]any{"text": text}, nil)
}

// executionContextID returns the cached main-world context id.
func (p *Page) executionContextID() string {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.mainContextID
}

// jsString safely embeds s as a JS string literal — backslash, single
// quote, newline, carriage return, line/paragraph separator.
func jsString(s string) string {
	var b strings.Builder
	b.WriteByte('\'')
	for _, r := range s {
		switch r {
		case '\\':
			b.WriteString(`\\`)
		case '\'':
			b.WriteString(`\'`)
		case '\n':
			b.WriteString(`\n`)
		case '\r':
			b.WriteString(`\r`)
		case ' ':
			b.WriteString(` `)
		case ' ':
			b.WriteString(` `)
		default:
			b.WriteRune(r)
		}
	}
	b.WriteByte('\'')
	return b.String()
}
