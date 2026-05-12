package camoufox

import (
	"context"
	"encoding/json"
	"fmt"
	"sync"
	"sync/atomic"

	"github.com/lang315/camoufox/goapi/pkg/juggler"
)

// MutationOptions configures which mutation types are observed.
type MutationOptions struct {
	ChildList       bool
	Subtree         bool
	Attributes      bool
	AttributeFilter []string // observe only these attribute names; empty = all
}

// Mutation is a single MutationRecord serialized from the browser.
type Mutation struct {
	Type          string   `json:"type"`
	Target        string   `json:"target"`       // outerHTML of the target node
	AddedNodes    []string `json:"addedNodes"`   // outerHTML of each added node
	RemovedNodes  []string `json:"removedNodes"` // outerHTML of each removed node
	AttributeName string   `json:"attributeName,omitempty"`
	OldValue      string   `json:"oldValue,omitempty"`
}

// bindingCounter generates unique binding names across concurrent watchers.
var bindingCounter atomic.Uint64

// WatchMutations installs a MutationObserver on the page that delivers
// mutations matching selector to the returned channel. When selector is
// non-empty, only records whose target matches document.querySelector(selector)
// or any of its descendants are delivered (filter semantics — the observer
// itself watches the full document). The cancel func deregisters the handler.
//
// Channel is never closed by the implementation; it stays open after cancel so
// callers can drain buffered items without racing a close.
//
// Implementation: Page.addBinding (Protocol.js L791) registers a named
// Go→JS bridge. The script field sets up the MutationObserver which filters
// by selector and calls the binding on each batch. Page.bindingCalled (L714)
// delivers the JSON payload to Go.
func (p *Page) WatchMutations(ctx context.Context, selector string, opts MutationOptions) (<-chan Mutation, func(), error) {
	id := bindingCounter.Add(1)
	bindName := fmt.Sprintf("__goapi_mut_%d", id)

	childList := "false"
	if opts.ChildList {
		childList = "true"
	}
	subtree := "false"
	if opts.Subtree {
		subtree = "true"
	}
	attributes := "false"
	if opts.Attributes {
		attributes = "true"
	}
	attrFilter := "undefined"
	if len(opts.AttributeFilter) > 0 {
		b, _ := json.Marshal(opts.AttributeFilter)
		attrFilter = string(b)
	}

	// The MutationObserver always observes document.documentElement with
	// subtree:true so it catches all DOM changes. When selector is non-empty
	// each record is filtered: only records whose target matches the selector
	// (or is contained by a matching element) are forwarded.
	script := fmt.Sprintf(`(function() {
		var send = window[%s];
		if (!send) return;
		var filterSel = %s;
		var obs = new MutationObserver(function(records) {
			var out = [];
			for (var i = 0; i < records.length; i++) {
				var r = records[i];
				if (filterSel) {
					var t = r.target;
					var match = false;
					while (t) {
						if (t.matches && t.matches(filterSel)) { match = true; break; }
						t = t.parentElement;
					}
					if (!match) continue;
				}
				var added = [];
				for (var j = 0; j < r.addedNodes.length; j++) {
					var n = r.addedNodes[j];
					added.push(n.nodeType === 1 ? n.outerHTML : n.textContent || '');
				}
				var removed = [];
				for (var j = 0; j < r.removedNodes.length; j++) {
					var n = r.removedNodes[j];
					removed.push(n.nodeType === 1 ? n.outerHTML : n.textContent || '');
				}
				out.push({
					type: r.type,
					target: r.target && r.target.nodeType === 1 ? r.target.outerHTML : '',
					addedNodes: added,
					removedNodes: removed,
					attributeName: r.attributeName || '',
					oldValue: r.oldValue || ''
				});
			}
			if (out.length > 0) send(JSON.stringify(out));
		});
		obs.observe(document.documentElement, {
			childList: %s,
			subtree: true,
			attributes: %s,
			attributeFilter: %s
		});
	})()`,
		jsString(bindName),
		// JS string literal for selector, or empty string for "no filter"
		jsString(selector),
		childList,
		attributes,
		attrFilter,
	)
	_ = subtree // always true in observer; kept in MutationOptions for API compatibility

	params := juggler.PageAddBindingParams{
		Name:   bindName,
		Script: script,
	}
	if err := p.session.Call(ctx, "Page.addBinding", params, nil); err != nil {
		return nil, nil, fmt.Errorf("camoufox: WatchMutations addBinding: %w", err)
	}

	ch := make(chan Mutation, 64)
	conn := p.bc.b.conn

	// done guards against handler running after cancel returns.
	var once sync.Once
	done := make(chan struct{})

	sub := conn.On("Page.bindingCalled", func(ev juggler.Event) {
		if ev.SessionID != p.session.ID() {
			return
		}
		var bc juggler.PageBindingCalledEvent
		if err := json.Unmarshal(ev.Params, &bc); err != nil {
			return
		}
		if bc.Name != bindName {
			return
		}
		var records []Mutation
		if err := json.Unmarshal([]byte(bc.Payload), &records); err != nil {
			return
		}
		for _, m := range records {
			select {
			case <-done:
				return // cancelled — discard
			case ch <- m:
			default:
				// drop if channel full — caller too slow
			}
		}
	})

	cancel := func() {
		once.Do(func() {
			conn.Off(sub)
			close(done)
			// ch is intentionally NOT closed — callers drain buffered items safely.
		})
	}
	return ch, cancel, nil
}
