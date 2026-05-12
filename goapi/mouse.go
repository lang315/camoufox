package camoufox

import (
	"context"
	"fmt"

	"github.com/lang315/camoufox/goapi/pkg/juggler"
)

// Mouse provides high-level mouse event dispatch. Obtain via Page.Mouse().
type Mouse struct {
	page *Page
}

// MouseClickOption configures Mouse.Click and Mouse.Down/Up.
type MouseClickOption func(*mouseClickOpts)

type mouseClickOpts struct {
	button    int
	modifiers int
}

// WithMouseButton sets which mouse button (0=left, 1=middle, 2=right).
func WithMouseButton(b int) MouseClickOption {
	return func(o *mouseClickOpts) { o.button = b }
}

// WithMouseModifiers sets the modifier bitmask for a mouse event.
func WithMouseModifiers(m int) MouseClickOption {
	return func(o *mouseClickOpts) { o.modifiers = m }
}

// Mouse returns the Mouse helper for this page.
func (p *Page) Mouse() *Mouse { return &Mouse{page: p} }

// Move dispatches a mousemove event at (x, y).
func (m *Mouse) Move(ctx context.Context, x, y float64) error {
	ev := juggler.PageDispatchMouseEventParams{
		Type: "mousemove", X: x, Y: y,
	}
	if err := m.page.session.Call(ctx, "Page.dispatchMouseEvent", ev, nil); err != nil {
		return fmt.Errorf("camoufox: mouse Move: %w", err)
	}
	return nil
}

// Down dispatches a mousedown event at the current mouse position (x, y must be re-supplied).
func (m *Mouse) Down(ctx context.Context, x, y float64, opts ...MouseClickOption) error {
	o := mouseClickOpts{}
	for _, fn := range opts {
		fn(&o)
	}
	one := 1
	ev := juggler.PageDispatchMouseEventParams{
		Type:       "mousedown",
		X:          x,
		Y:          y,
		Button:     o.button,
		Buttons:    1,
		Modifiers:  o.modifiers,
		ClickCount: &one,
	}
	if err := m.page.session.Call(ctx, "Page.dispatchMouseEvent", ev, nil); err != nil {
		return fmt.Errorf("camoufox: mouse Down: %w", err)
	}
	return nil
}

// Up dispatches a mouseup event.
func (m *Mouse) Up(ctx context.Context, x, y float64, opts ...MouseClickOption) error {
	o := mouseClickOpts{}
	for _, fn := range opts {
		fn(&o)
	}
	one := 1
	ev := juggler.PageDispatchMouseEventParams{
		Type:       "mouseup",
		X:          x,
		Y:          y,
		Button:     o.button,
		Buttons:    0,
		Modifiers:  o.modifiers,
		ClickCount: &one,
	}
	if err := m.page.session.Call(ctx, "Page.dispatchMouseEvent", ev, nil); err != nil {
		return fmt.Errorf("camoufox: mouse Up: %w", err)
	}
	return nil
}

// Click dispatches move → down → up at (x, y).
func (m *Mouse) Click(ctx context.Context, x, y float64, opts ...MouseClickOption) error {
	if err := m.Move(ctx, x, y); err != nil {
		return err
	}
	if err := m.Down(ctx, x, y, opts...); err != nil {
		return err
	}
	return m.Up(ctx, x, y, opts...)
}

// DblClick dispatches two sequential clicks at (x, y).
func (m *Mouse) DblClick(ctx context.Context, x, y float64, opts ...MouseClickOption) error {
	if err := m.Click(ctx, x, y, opts...); err != nil {
		return err
	}
	return m.Click(ctx, x, y, opts...)
}

// Wheel dispatches a wheel event with the given scroll deltas.
func (m *Mouse) Wheel(ctx context.Context, x, y, deltaX, deltaY float64) error {
	params := juggler.PageDispatchWheelEventParams{
		X:      x,
		Y:      y,
		DeltaX: deltaX,
		DeltaY: deltaY,
		DeltaZ: 0,
	}
	if err := m.page.session.Call(ctx, "Page.dispatchWheelEvent", params, nil); err != nil {
		return fmt.Errorf("camoufox: mouse Wheel: %w", err)
	}
	return nil
}
