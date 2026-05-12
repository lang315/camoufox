package camoufox

import (
	"encoding/json"

	"github.com/lang315/camoufox/goapi/pkg/juggler"
)

// ConsoleMessage represents a Runtime.console event.
// Level maps from the protocol's `type` field (log, warn, error, etc.).
// Text is best-effort derived from the first string arg if present.
// Args holds the raw decoded values of each RemoteObject argument.
type ConsoleMessage struct {
	Level string
	Text  string
	Args  []any
}

// PageError represents an uncaught JavaScript error on a page.
type PageError struct {
	FrameID string
	Message string
	Stack   string
}

// OnConsole registers a handler for Runtime.console events on this page.
// Returns a Subscription that can be passed to p.Off to deregister.
func (p *Page) OnConsole(handler func(*ConsoleMessage)) juggler.Subscription {
	return p.bc.b.conn.On("Runtime.console", func(ev juggler.Event) {
		if ev.SessionID != p.session.ID() {
			return
		}
		var ce juggler.RuntimeConsoleEvent
		if err := json.Unmarshal(ev.Params, &ce); err != nil {
			return
		}
		msg := &ConsoleMessage{Level: ce.Type}
		for _, arg := range ce.Args {
			if len(arg.Value) > 0 {
				var v any
				if err := json.Unmarshal(arg.Value, &v); err == nil {
					msg.Args = append(msg.Args, v)
					if msg.Text == "" {
						if s, ok := v.(string); ok {
							msg.Text = s
						}
					}
				}
			}
		}
		go handler(msg)
	})
}

// OnPageError registers a handler for Page.uncaughtError events.
// Returns a Subscription that can be passed to p.Off to deregister.
func (p *Page) OnPageError(handler func(*PageError)) juggler.Subscription {
	return p.bc.b.conn.On("Page.uncaughtError", func(ev juggler.Event) {
		if ev.SessionID != p.session.ID() {
			return
		}
		var ue juggler.PageUncaughtErrorEvent
		if err := json.Unmarshal(ev.Params, &ue); err != nil {
			return
		}
		go handler(&PageError{
			FrameID: ue.FrameID,
			Message: ue.Message,
			Stack:   ue.Stack,
		})
	})
}

// OnCrash registers a handler for Page.crashed events.
// Returns a Subscription that can be passed to p.Off to deregister.
func (p *Page) OnCrash(handler func()) juggler.Subscription {
	return p.bc.b.conn.On("Page.crashed", func(ev juggler.Event) {
		if ev.SessionID != p.session.ID() {
			return
		}
		go handler()
	})
}
