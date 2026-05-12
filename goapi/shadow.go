package camoufox

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/lang315/camoufox/goapi/pkg/juggler"
)

// QueryDeep pierces shadow DOM boundaries and returns all elements matching
// selector across the entire document tree, including inside shadow roots.
// It recursively walks shadowRoot.querySelectorAll for every element that
// has a shadow root attached.
func (p *Page) QueryDeep(ctx context.Context, selector string) ([]*ElementHandle, error) {
	ctxID, err := p.awaitMainContext(ctx, 5*time.Second)
	if err != nil {
		return nil, err
	}

	// Build the array of matching elements across all shadow roots.
	walkExpr := fmt.Sprintf(`(() => {
		const sel = %s;
		const out = [];
		const walk = (root) => {
			const matches = root.querySelectorAll(sel);
			for (let i = 0; i < matches.length; i++) out.push(matches[i]);
			const all = root.querySelectorAll('*');
			for (let i = 0; i < all.length; i++) {
				if (all[i].shadowRoot) walk(all[i].shadowRoot);
			}
		};
		walk(document);
		return out;
	})()`, jsString(selector))

	var evalRes juggler.EvaluateResult
	if err := p.session.Call(ctx, "Runtime.evaluate", juggler.EvaluateParams{
		ExecutionContextID: ctxID,
		Expression:         walkExpr,
	}, &evalRes); err != nil {
		return nil, fmt.Errorf("camoufox: QueryDeep evaluate: %w", err)
	}
	if evalRes.ExceptionDetails != nil {
		return nil, fmt.Errorf("camoufox: QueryDeep exception: %s", evalRes.ExceptionDetails.Text)
	}
	if evalRes.Result == nil || evalRes.Result.ObjectID == "" {
		return nil, nil
	}

	count, err := p.callFunction(ctx, ctxID,
		`function(a) { return a.length; }`,
		[]juggler.CallFunctionArgument{{ObjectID: evalRes.Result.ObjectID}}, true)
	if err != nil {
		return nil, fmt.Errorf("camoufox: QueryDeep length: %w", err)
	}
	var n int
	_ = json.Unmarshal(count.Result.Value, &n)

	frameID := p.MainFrameID()
	out := make([]*ElementHandle, 0, n)
	for i := 0; i < n; i++ {
		item, err := p.callFunction(ctx, ctxID,
			`function(a, i) { return a[i]; }`,
			[]juggler.CallFunctionArgument{
				{ObjectID: evalRes.Result.ObjectID},
				argNumber(float64(i)),
			}, false)
		if err != nil {
			return nil, fmt.Errorf("camoufox: QueryDeep index %d: %w", i, err)
		}
		if item.Result == nil || item.Result.ObjectID == "" {
			continue
		}
		out = append(out, p.wrapObject(frameID, ctxID, item.Result.ObjectID))
	}
	return out, nil
}
