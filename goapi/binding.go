package camoufox

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"sync/atomic"

	"github.com/lang315/camoufox/goapi/pkg/juggler"
)

// ExposeBinding installs window[name] in the isolated world that Page.Evaluate
// and WatchMutations use, then runs script there, on the current document and
// on every later one. script calls window[name](payload) to deliver a string
// to fn; the caller JSON-encodes anything structured.
//
// The binding is not visible to the page. Page script, and a "mw:" init script,
// read typeof window[name] as "undefined" and cannot call it, so it is not a
// fingerprint. A main-world script that must reach Go bridges through the DOM:
// it dispatches a CustomEvent on document, which script listens for. That
// bridge is visible to the page, and the caller accepts it. On a new document
// the binding and script run before any init script of the same world, so a
// listener script adds is in place before a "mw:" init script dispatches.
// On the document that is current when ExposeBinding is called, the binding
// exists only from that call on: earlier events on it are not delivered.
//
// fn runs on the connection's read loop, so it must return promptly and must not
// call the browser (Evaluate, Call): the reply it would wait for can only be read
// by the loop it is blocking. Hand the work to a goroutine; calls arrive in page order.
//
// An empty name, or a name already bound on this page, returns an error.
// Juggler has no removeBinding, so cancel only stops delivery to fn: window[name]
// stays in the isolated world, and its name stays taken on this page.
func (p *Page) ExposeBinding(ctx context.Context, name, script string, fn func(payload string)) (cancel func(), err error) {
	return p.addBinding(ctx, name, script, fn)
}

// addBinding is the one path every binding takes: WatchMutations and
// ExposeBinding both register a Page.addBinding and route its Page.bindingCalled
// events to a handler.
func (p *Page) addBinding(ctx context.Context, name, script string, fn func(payload string)) (func(), error) {
	if name == "" {
		return nil, errors.New("camoufox: binding name is empty")
	}
	p.bindMu.Lock()
	if _, taken := p.bound[name]; taken {
		p.bindMu.Unlock()
		return nil, fmt.Errorf("camoufox: binding %q is already bound on this page", name)
	}
	if p.bound == nil {
		p.bound = map[string]struct{}{}
	}
	p.bound[name] = struct{}{}
	p.bindMu.Unlock()

	// The handler is in place before addBinding, because script runs during it.
	var cancelled atomic.Bool
	conn := p.bc.b.conn
	sub := p.own(conn.On("Page.bindingCalled", func(ev juggler.Event) {
		if ev.SessionID != p.session.ID() || cancelled.Load() {
			return
		}
		var bc juggler.PageBindingCalledEvent
		if err := json.Unmarshal(ev.Params, &bc); err != nil || bc.Name != name {
			return
		}
		fn(bc.Payload)
	}))
	params := juggler.PageAddBindingParams{Name: name, Script: script}
	if err := p.session.Call(ctx, "Page.addBinding", params, nil); err != nil {
		conn.Off(sub)
		p.bindMu.Lock()
		delete(p.bound, name)
		p.bindMu.Unlock()
		return nil, fmt.Errorf("camoufox: addBinding %q: %w", name, err)
	}
	return func() {
		cancelled.Store(true)
		conn.Off(sub)
	}, nil
}

// SetBypassCSP turns Content-Security-Policy enforcement off (true) or back on
// for pages of this context, from the next navigation. A page served with
// connect-src 'none' can then reach a local server, such as a devtools backend.
func (c *BrowserContext) SetBypassCSP(ctx context.Context, bypass bool) error {
	params := juggler.BrowserSetBypassCSPParams{BrowserContextID: c.id, BypassCSP: bypass}
	return c.b.root.Call(ctx, "Browser.setBypassCSP", params, nil)
}
