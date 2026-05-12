package camoufox

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/lang315/camoufox/goapi/pkg/juggler"
)

// WaitState describes the DOM/visibility condition to wait for.
type WaitState int

const (
	WaitAttached WaitState = iota
	WaitDetached
	WaitVisible
	WaitHidden
)

// WaitForOptions controls WaitFor behaviour.
type WaitForOptions struct {
	State        WaitState
	Timeout      time.Duration
	PollInterval time.Duration
}

// WaitFor polls until the selector satisfies opts.State or the deadline
// passes. Returns the matching ElementHandle for Attached/Visible states,
// nil for Detached/Hidden states, and an error on timeout or eval failure.
func (p *Page) WaitFor(ctx context.Context, selector string, opts WaitForOptions) (*ElementHandle, error) {
	if opts.Timeout <= 0 {
		opts.Timeout = 30 * time.Second
	}
	if opts.PollInterval <= 0 {
		opts.PollInterval = 50 * time.Millisecond
	}
	return p.waitState(ctx, selector, opts)
}

// waitState is the internal polling loop.
func (p *Page) waitState(ctx context.Context, selector string, opts WaitForOptions) (*ElementHandle, error) {
	deadline := time.Now().Add(opts.Timeout)
	tick := time.NewTicker(opts.PollInterval)
	defer tick.Stop()

	for {
		el, matched, err := p.checkState(ctx, selector, opts.State)
		if err != nil {
			return nil, err
		}
		if matched {
			return el, nil
		}
		if time.Now().After(deadline) {
			return nil, fmt.Errorf("camoufox: WaitFor: timed out after %s", opts.Timeout)
		}
		select {
		case <-tick.C:
		case <-ctx.Done():
			return nil, ctx.Err()
		}
	}
}

// checkState runs a single poll iteration. Returns (handle, matched, err).
func (p *Page) checkState(ctx context.Context, selector string, state WaitState) (*ElementHandle, bool, error) {
	switch state {
	case WaitAttached:
		el, err := p.QuerySelector(ctx, selector)
		if err != nil {
			return nil, false, err
		}
		return el, el != nil, nil

	case WaitDetached:
		el, err := p.QuerySelector(ctx, selector)
		if err != nil {
			return nil, false, err
		}
		return nil, el == nil, nil

	case WaitVisible:
		el, err := p.QuerySelector(ctx, selector)
		if err != nil || el == nil {
			return nil, false, err
		}
		vis, err := p.isVisible(ctx, el)
		if err != nil {
			return nil, false, err
		}
		return el, vis, nil

	case WaitHidden:
		el, err := p.QuerySelector(ctx, selector)
		if err != nil {
			return nil, false, err
		}
		if el == nil {
			return nil, true, nil
		}
		vis, err := p.isVisible(ctx, el)
		if err != nil {
			return nil, false, err
		}
		return nil, !vis, nil
	}
	return nil, false, fmt.Errorf("camoufox: waitState: unknown state %d", state)
}

// isVisible checks that an element has non-zero size and offsetParent is not null.
func (p *Page) isVisible(ctx context.Context, e *ElementHandle) (bool, error) {
	res, err := p.callFunction(ctx, e.ctxID,
		`function(el) {
			if (!el) return false;
			var r = el.getBoundingClientRect();
			return r.width > 0 && r.height > 0 && el.offsetParent !== null;
		}`,
		[]juggler.CallFunctionArgument{{ObjectID: e.objectID}}, true)
	if err != nil {
		return false, err
	}
	if res.Result == nil || len(res.Result.Value) == 0 {
		return false, nil
	}
	var ok bool
	_ = json.Unmarshal(res.Result.Value, &ok)
	return ok, nil
}
