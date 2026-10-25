package camoufox

import (
	"math"

	"github.com/lang315/camoufox/goapi/pkg/juggler"
)

// mainWorldPrefix routes an Evaluate expression to the page's own global
// instead of the isolated world (see WithMainWorldEval).
const mainWorldPrefix = "mw:"

// Juggler recognises a main-world request only in Playwright's own call
// shape (browser/additions/juggler/content/Runtime.js isMainWorldRequest):
// a function declaration naming utilityScript.evaluate, called with
// [utilityScript, isFunction, returnByValue, expression, argCount]. The
// function itself never runs on that path, so the first argument is unused.
const mainWorldFunction = "(utilityScript, ...args) => utilityScript.evaluate(...args)"

func mainWorldArgs(expression string) []juggler.CallFunctionArgument {
	return []juggler.CallFunctionArgument{
		{},
		argBool(false),
		argBool(true),
		argString(expression),
		argNumber(0),
	}
}

// decodeSerialized turns a value in Playwright's serialized form, which
// main-world evaluation returns, into the plain JSON shape Evaluate returns
// otherwise. A back-reference to an enclosing object decodes to nil, and a
// tag with no plain equivalent (regexp, error, typed array) stays as decoded.
func decodeSerialized(v any) any {
	switch t := v.(type) {
	case []any:
		out := make([]any, len(t))
		for i, item := range t {
			out[i] = decodeSerialized(item)
		}
		return out
	case map[string]any:
		if s, ok := t["v"].(string); ok {
			switch s {
			case "NaN":
				return math.NaN()
			case "Infinity":
				return math.Inf(1)
			case "-Infinity":
				return math.Inf(-1)
			case "-0":
				return math.Copysign(0, -1)
			}
			return nil
		}
		if _, ok := t["ref"]; ok {
			return nil
		}
		if a, ok := t["a"].([]any); ok {
			return decodeSerialized(a)
		}
		if o, ok := t["o"].([]any); ok {
			out := make(map[string]any, len(o))
			for _, entry := range o {
				if kv, ok := entry.(map[string]any); ok {
					if k, ok := kv["k"].(string); ok {
						out[k] = decodeSerialized(kv["v"])
					}
				}
			}
			return out
		}
		for _, tag := range []string{"d", "u", "bi"} {
			if s, ok := t[tag].(string); ok {
				return s
			}
		}
	}
	return v
}
