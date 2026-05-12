package camoufox

import (
	"context"
	"fmt"

	"github.com/lang315/camoufox/goapi/pkg/juggler"
)

// Touchscreen provides low-level touch-event dispatch for this page.
type Touchscreen struct {
	page *Page
}

// Touchscreen returns the Touchscreen helper for this page.
func (p *Page) Touchscreen() *Touchscreen {
	return &Touchscreen{page: p}
}

// Tap dispatches a synthetic tap (touchstart + touchend) at (x, y).
func (t *Touchscreen) Tap(ctx context.Context, x, y float64) error {
	params := juggler.PageDispatchTapEventParams{X: x, Y: y}
	if err := t.page.session.Call(ctx, "Page.dispatchTapEvent", params, nil); err != nil {
		return fmt.Errorf("camoufox: Touchscreen.Tap: %w", err)
	}
	return nil
}

// TouchStart dispatches a touchstart event with the given touch points.
func (t *Touchscreen) TouchStart(ctx context.Context, points []juggler.TouchPoint) error {
	return t.dispatch(ctx, "touchStart", points)
}

// TouchMove dispatches a touchmove event with the given touch points.
func (t *Touchscreen) TouchMove(ctx context.Context, points []juggler.TouchPoint) error {
	return t.dispatch(ctx, "touchMove", points)
}

// TouchEnd dispatches a touchend event with the given touch points.
func (t *Touchscreen) TouchEnd(ctx context.Context, points []juggler.TouchPoint) error {
	return t.dispatch(ctx, "touchEnd", points)
}

// TouchCancel dispatches a touchcancel event with the given touch points.
func (t *Touchscreen) TouchCancel(ctx context.Context, points []juggler.TouchPoint) error {
	return t.dispatch(ctx, "touchCancel", points)
}

func (t *Touchscreen) dispatch(ctx context.Context, typ string, points []juggler.TouchPoint) error {
	params := juggler.PageDispatchTouchEventParams{
		Type:        typ,
		TouchPoints: points,
	}
	if err := t.page.session.Call(ctx, "Page.dispatchTouchEvent", params, nil); err != nil {
		return fmt.Errorf("camoufox: Touchscreen.%s: %w", typ, err)
	}
	return nil
}

// SetTouchOverride overrides the touch capability for all pages in this
// context. Pass nil to remove the override and restore the default
// device emulation setting.
func (c *BrowserContext) SetTouchOverride(ctx context.Context, hasTouch *bool) error {
	params := juggler.BrowserSetTouchOverrideParams{
		BrowserContextID: c.id,
		HasTouch:         hasTouch,
	}
	if err := c.b.root.Call(ctx, "Browser.setTouchOverride", params, nil); err != nil {
		return fmt.Errorf("camoufox: SetTouchOverride: %w", err)
	}
	return nil
}
