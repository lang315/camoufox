package camoufox

import (
	"context"
	"fmt"

	"github.com/lang315/camoufox/goapi/pkg/juggler"
)

// Accessibility provides access to the page's live accessibility tree.
type Accessibility struct {
	page *Page
}

// Accessibility returns the Accessibility helper for this page.
func (p *Page) Accessibility() *Accessibility {
	return &Accessibility{page: p}
}

// Snapshot returns the full accessibility tree for the page. The root
// AXNode contains all descendants. Pass a non-nil root ElementHandle
// to scope the tree to a subtree (pass nil for the full page tree).
func (a *Accessibility) Snapshot(ctx context.Context, root *ElementHandle) (*juggler.AXNode, error) {
	params := juggler.AccessibilityGetFullAXTreeParams{}
	if root != nil {
		params.ObjectID = root.objectID
	}
	var res juggler.AccessibilityGetFullAXTreeResult
	if err := a.page.session.Call(ctx, "Accessibility.getFullAXTree", params, &res); err != nil {
		return nil, fmt.Errorf("camoufox: Accessibility.Snapshot: %w", err)
	}
	return res.Tree, nil
}
