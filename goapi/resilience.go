package camoufox

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/lang315/camoufox/goapi/pkg/juggler"
)

// SelectorKind identifies the matching strategy for a Selector.
type SelectorKind int

const (
	KindCSS    SelectorKind = iota // standard CSS selector
	KindXPath                      // XPath expression
	KindText                       // element whose trimmed textContent equals Value
	KindTestID                     // shorthand for [data-testid="Value"]
)

// Selector pairs a matching strategy with its value.
type Selector struct {
	Kind  SelectorKind
	Value string
}

// QueryResilient tries each selector in order and returns the first match.
// Returns an error only when all selectors are exhausted without a match.
func (p *Page) QueryResilient(ctx context.Context, selectors []Selector) (*ElementHandle, error) {
	for _, sel := range selectors {
		el, err := p.queryOne(ctx, sel)
		if err != nil {
			continue
		}
		if el != nil {
			return el, nil
		}
	}
	return nil, fmt.Errorf("camoufox: QueryResilient: no selector matched out of %d tried", len(selectors))
}

// queryOne executes a single selector strategy and returns the element or nil.
func (p *Page) queryOne(ctx context.Context, sel Selector) (*ElementHandle, error) {
	switch sel.Kind {
	case KindCSS:
		return p.QuerySelector(ctx, sel.Value)
	case KindXPath:
		results, err := p.QueryXPath(ctx, sel.Value)
		if err != nil {
			return nil, err
		}
		if len(results) == 0 {
			return nil, nil
		}
		return results[0], nil
	case KindText:
		return p.queryByTextHandle(ctx, sel.Value)
	case KindTestID:
		return p.QuerySelector(ctx, fmt.Sprintf(`[data-testid="%s"]`, escapeAttr(sel.Value)))
	}
	return nil, fmt.Errorf("camoufox: queryOne: unknown SelectorKind %d", sel.Kind)
}

// queryByTextHandle uses callFunction to get a live objectId for the first
// element whose trimmed textContent equals text. Array.from is used for
// portability across older JS runtimes.
func (p *Page) queryByTextHandle(ctx context.Context, text string) (*ElementHandle, error) {
	ctxID, err := p.awaitMainContext(ctx, 5*time.Second)
	if err != nil {
		return nil, err
	}
	res, err := p.callFunction(ctx, ctxID,
		`function(text) {
			var els = Array.from(document.querySelectorAll('*'));
			for (var i = 0; i < els.length; i++) {
				if (els[i].textContent.trim() === text) return els[i];
			}
			return null;
		}`,
		[]juggler.CallFunctionArgument{argString(text)}, false)
	if err != nil {
		return nil, err
	}
	if res.Result == nil || res.Result.ObjectID == "" {
		return nil, nil
	}
	return p.wrapObject(p.MainFrameID(), ctxID, res.Result.ObjectID), nil
}

// escapeAttr escapes double-quotes in an attribute value for embedding in CSS.
func escapeAttr(s string) string {
	return strings.ReplaceAll(s, `"`, `\"`)
}
