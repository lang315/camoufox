package camoufox

import (
	"errors"
	"fmt"
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

// errMainWorldCycle is returned when a main-world result refers to an object
// that is still being decoded: a self-referencing Go map would recurse without
// bound in fmt and log calls, and Evaluate's isolated path never returns one.
var errMainWorldCycle = errors.New("camoufox: main-world result contains a cycle")

// decodeSerialized turns a value in Playwright's serialized form, which
// main-world evaluation returns, into the plain JSON shape Evaluate returns
// otherwise. Playwright's serializer records every object and array it visits
// and writes any later reach of one as {"ref": id}, shared sibling or cycle
// alike (utilityScriptSerializers, serializeAsCallArgument); a ref to a value
// already decoded resolves to it, as parseEvaluationResultValue does, and a ref
// to one still being decoded is errMainWorldCycle. A tag with no plain
// equivalent (regexp, error, typed array) stays as decoded.
func decodeSerialized(v any) (any, error) {
	d := serialDecoder{done: map[float64]any{}, open: map[float64]bool{}}
	return d.decode(v)
}

type serialDecoder struct {
	done map[float64]any
	open map[float64]bool
}

func (d *serialDecoder) decode(v any) (any, error) {
	switch t := v.(type) {
	case []any:
		out := make([]any, len(t))
		for i, item := range t {
			var err error
			if out[i], err = d.decode(item); err != nil {
				return nil, err
			}
		}
		return out, nil
	case map[string]any:
		if s, ok := t["v"].(string); ok {
			switch s {
			case "NaN":
				return math.NaN(), nil
			case "Infinity":
				return math.Inf(1), nil
			case "-Infinity":
				return math.Inf(-1), nil
			case "-0":
				return math.Copysign(0, -1), nil
			}
			return nil, nil
		}
		if ref, ok := t["ref"]; ok {
			id, _ := ref.(float64)
			if d.open[id] {
				return nil, errMainWorldCycle
			}
			out, ok := d.done[id]
			if !ok {
				return nil, fmt.Errorf("camoufox: main-world result refers to unknown object %v", ref)
			}
			return out, nil
		}
		id, _ := t["id"].(float64)
		d.open[id] = true
		defer delete(d.open, id)
		if a, ok := t["a"].([]any); ok {
			out, err := d.decode(a)
			if err == nil {
				d.done[id] = out
			}
			return out, err
		}
		if o, ok := t["o"].([]any); ok {
			out := make(map[string]any, len(o))
			for _, entry := range o {
				if kv, ok := entry.(map[string]any); ok {
					if k, ok := kv["k"].(string); ok {
						var err error
						if out[k], err = d.decode(kv["v"]); err != nil {
							return nil, err
						}
					}
				}
			}
			d.done[id] = out
			return out, nil
		}
		for _, tag := range []string{"d", "u", "bi"} {
			if s, ok := t[tag].(string); ok {
				return s, nil
			}
		}
	}
	return v, nil
}
