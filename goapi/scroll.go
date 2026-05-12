package camoufox

import (
	"context"
	"encoding/json"
	"fmt"
	"math/rand"
	"time"
)

// ScrollToOptions configures Page.ScrollTo.
type ScrollToOptions struct {
	X      float64
	Y      float64
	Smooth bool
}

// ScrollToBottomOptions configures Page.ScrollToBottom.
type ScrollToBottomOptions struct {
	// MaxSteps is the maximum number of scroll steps before giving up (default 50).
	MaxSteps int
	// IdleMs is the wait between steps to let lazy-load content settle (default 400ms).
	IdleMs time.Duration
	// StepDelta is the nominal pixel delta per step (default 600).
	StepDelta float64
}

// ScrollTo scrolls the window to absolute (X, Y). Smooth controls CSS scroll-behavior.
func (p *Page) ScrollTo(ctx context.Context, opts ScrollToOptions) error {
	behavior := "instant"
	if opts.Smooth {
		behavior = "smooth"
	}
	script := fmt.Sprintf(`window.scrollTo({left: %g, top: %g, behavior: %s})`,
		opts.X, opts.Y, jsString(behavior))
	_, err := p.Evaluate(ctx, script)
	return err
}

// ScrollBy scrolls the window by (dx, dy) relative to current position.
func (p *Page) ScrollBy(ctx context.Context, dx, dy float64) error {
	script := fmt.Sprintf(`window.scrollBy(%g, %g)`, dx, dy)
	_, err := p.Evaluate(ctx, script)
	return err
}

// ScrollToBottom scrolls the page to the bottom using repeated wheel events with
// human-like jitter. It exits when scroll position is unchanged for two consecutive
// steps or MaxSteps is reached.
func (p *Page) ScrollToBottom(ctx context.Context, opts ScrollToBottomOptions) error {
	if opts.MaxSteps <= 0 {
		opts.MaxSteps = 50
	}
	if opts.IdleMs <= 0 {
		opts.IdleMs = 400 * time.Millisecond
	}
	if opts.StepDelta <= 0 {
		opts.StepDelta = 600
	}

	// seed-once rng for jitter; each call gets a fresh source so tests remain deterministic.
	rng := rand.New(rand.NewSource(time.Now().UnixNano()))

	var prevScrollTop float64
	unchanged := 0

	for step := 0; step < opts.MaxSteps; step++ {
		top, err := p.scrollTop(ctx)
		if err != nil {
			return err
		}
		if step > 0 {
			if top == prevScrollTop {
				unchanged++
				if unchanged >= 2 {
					break
				}
			} else {
				unchanged = 0
			}
		}
		prevScrollTop = top

		// Apply ±10% jitter to look human.
		jitter := (rng.Float64()*0.2 - 0.1) * opts.StepDelta
		delta := opts.StepDelta + jitter

		// Use wheel events so the browser's scroll event pipeline fires normally.
		if err := p.Mouse().Wheel(ctx, 1, 1, 0, delta); err != nil {
			return fmt.Errorf("camoufox: ScrollToBottom wheel: %w", err)
		}

		select {
		case <-time.After(opts.IdleMs):
		case <-ctx.Done():
			return ctx.Err()
		}
	}
	return nil
}

// scrollTop returns document.scrollingElement.scrollTop via a single Evaluate call.
func (p *Page) scrollTop(ctx context.Context) (float64, error) {
	v, err := p.Evaluate(ctx, `(document.scrollingElement||document.documentElement).scrollTop`)
	if err != nil {
		return 0, err
	}
	switch n := v.(type) {
	case float64:
		return n, nil
	case json.Number:
		f, _ := n.Float64()
		return f, nil
	}
	return 0, nil
}
