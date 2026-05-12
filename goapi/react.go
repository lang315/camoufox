package camoufox

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/lang315/camoufox/goapi/pkg/juggler"
)

// ReactProps reads the memoizedProps from the React Fiber node attached to
// the element. Works with React 16/17/18 — all attach the fiber under a key
// matching "__reactFiber$" or "__reactInternalInstance$".
//
// Returns nil without error when the element has no React fiber (e.g. plain
// HTML pages). Callers should treat a nil map as "no React props".
func (e *ElementHandle) ReactProps(ctx context.Context) (map[string]any, error) {
	return e.reactField(ctx, "memoizedProps")
}

// ReactState reads memoizedState from the React Fiber. For class components
// this is the component state object; for hooks it is the first hook's
// memoizedState value. Returns nil when no fiber is present.
func (e *ElementHandle) ReactState(ctx context.Context) (map[string]any, error) {
	return e.reactField(ctx, "memoizedState")
}

// reactField extracts a named field from the element's React Fiber.
func (e *ElementHandle) reactField(ctx context.Context, field string) (map[string]any, error) {
	res, err := e.page.callFunction(ctx, e.ctxID,
		`function(el, field) {
			// Scan element properties for the React fiber key.
			// React 16+ uses __reactFiber$<random>; older versions __reactInternalInstance$.
			for (var k in el) {
				if (k.indexOf('__reactFiber$') === 0 || k.indexOf('__reactInternalInstance$') === 0) {
					var fiber = el[k];
					if (fiber && fiber[field] !== undefined) {
						try {
							return JSON.stringify(fiber[field]);
						} catch(e) {
							return null;
						}
					}
				}
			}
			// Also check __reactProps$ which React 17+ attaches directly.
			if (field === 'memoizedProps') {
				for (var k in el) {
					if (k.indexOf('__reactProps$') === 0) {
						try {
							return JSON.stringify(el[k]);
						} catch(e) {
							return null;
						}
					}
				}
			}
			return null;
		}`,
		[]juggler.CallFunctionArgument{{ObjectID: e.objectID}, argString(field)}, true)
	if err != nil {
		return nil, fmt.Errorf("camoufox: ReactField %s: %w", field, err)
	}
	if res.Result == nil || len(res.Result.Value) == 0 || string(res.Result.Value) == "null" {
		return nil, nil
	}
	// result.Value is the JSON string returned by JSON.stringify inside JS.
	var raw string
	if err := json.Unmarshal(res.Result.Value, &raw); err != nil {
		return nil, fmt.Errorf("camoufox: ReactField %s unmarshal outer: %w", field, err)
	}
	var out map[string]any
	if err := json.Unmarshal([]byte(raw), &out); err != nil {
		// memoizedState for hooks is not always a plain object; return nil gracefully.
		return nil, nil
	}
	return out, nil
}
