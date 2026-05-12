package camoufox

import (
	"context"
	"errors"
	"fmt"

	"github.com/lang315/camoufox/goapi/pkg/juggler"
)

// Reload reloads the current page.
func (p *Page) Reload(ctx context.Context) error {
	if err := p.session.Call(ctx, "Page.reload", map[string]any{}, nil); err != nil {
		return fmt.Errorf("camoufox: reload: %w", err)
	}
	return nil
}

// GoBack navigates the main frame back in history.
// Returns true if there was a history entry to go back to.
func (p *Page) GoBack(ctx context.Context) (bool, error) {
	frameID := p.MainFrameID()
	if frameID == "" {
		return false, errors.New("camoufox: GoBack: main frame not ready")
	}
	params := juggler.PageGoBackParams{FrameID: frameID}
	var res juggler.PageGoBackResult
	if err := p.session.Call(ctx, "Page.goBack", params, &res); err != nil {
		return false, fmt.Errorf("camoufox: goBack: %w", err)
	}
	return res.Success, nil
}

// GoForward navigates the main frame forward in history.
// Returns true if there was a history entry to go forward to.
func (p *Page) GoForward(ctx context.Context) (bool, error) {
	frameID := p.MainFrameID()
	if frameID == "" {
		return false, errors.New("camoufox: GoForward: main frame not ready")
	}
	params := juggler.PageGoForwardParams{FrameID: frameID}
	var res juggler.PageGoForwardResult
	if err := p.session.Call(ctx, "Page.goForward", params, &res); err != nil {
		return false, fmt.Errorf("camoufox: goForward: %w", err)
	}
	return res.Success, nil
}
