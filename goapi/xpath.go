package camoufox

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/lang315/camoufox/goapi/pkg/juggler"
)

// QueryXPath evaluates an XPath expression against the document and returns
// all matching nodes as ElementHandle slices. Uses the per-index callFunction
// pattern established by QuerySelectorAll — Juggler evaluate does not support
// serializeAsObject, so we extract each node individually.
func (p *Page) QueryXPath(ctx context.Context, expr string) ([]*ElementHandle, error) {
	ctxID, err := p.awaitMainContext(ctx, 5*time.Second)
	if err != nil {
		return nil, err
	}

	// Evaluate the XPath and return the snapshot as an array handle.
	xpathExpr := fmt.Sprintf(`(() => {
		const r = document.evaluate(%s, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
		const out = [];
		for (let i = 0; i < r.snapshotLength; i++) out.push(r.snapshotItem(i));
		return out;
	})()`, jsString(expr))

	var evalRes juggler.EvaluateResult
	if err := p.session.Call(ctx, "Runtime.evaluate", juggler.EvaluateParams{
		ExecutionContextID: ctxID,
		Expression:         xpathExpr,
	}, &evalRes); err != nil {
		return nil, fmt.Errorf("camoufox: QueryXPath evaluate: %w", err)
	}
	if evalRes.ExceptionDetails != nil {
		return nil, fmt.Errorf("camoufox: QueryXPath exception: %s", evalRes.ExceptionDetails.Text)
	}
	if evalRes.Result == nil || evalRes.Result.ObjectID == "" {
		return nil, nil
	}

	// Read array length.
	count, err := p.callFunction(ctx, ctxID,
		`function(a) { return a.length; }`,
		[]juggler.CallFunctionArgument{{ObjectID: evalRes.Result.ObjectID}}, true)
	if err != nil {
		return nil, fmt.Errorf("camoufox: QueryXPath length: %w", err)
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
			return nil, fmt.Errorf("camoufox: QueryXPath index %d: %w", i, err)
		}
		if item.Result == nil || item.Result.ObjectID == "" {
			continue
		}
		out = append(out, p.wrapObject(frameID, ctxID, item.Result.ObjectID))
	}
	return out, nil
}
