package camoufox

import (
	"context"
	"encoding/json"
	"fmt"
)

// FillForm fills form fields described by fields, where each key is matched against
// name/label text/placeholder/aria-label of inputs. Returns the count of fields
// successfully filled. The entire lookup+fill is done in a single JS evaluate per
// field to minimize round-trips.
func (p *Page) FillForm(ctx context.Context, fields map[string]string) (int, error) {
	if len(fields) == 0 {
		return 0, nil
	}

	// Encode the map as ordered pairs so JS receives it without depending on map iteration.
	type kv struct {
		K string `json:"k"`
		V string `json:"v"`
	}
	pairs := make([]kv, 0, len(fields))
	for k, v := range fields {
		pairs = append(pairs, kv{K: k, V: v})
	}
	pairsJSON, err := json.Marshal(pairs)
	if err != nil {
		return 0, err
	}

	// Single JS evaluate: for each pair resolve the element then set its value.
	fillJS := fmt.Sprintf(`(function(pairs) {
		var filled = 0;
		function findEl(key) {
			// a) [name="key"]
			var el = document.querySelector('[name=' + JSON.stringify(key) + ']');
			if (el) return el;
			// b) label whose text contains key → associated input
			var labels = Array.from(document.querySelectorAll('label'));
			for (var i = 0; i < labels.length; i++) {
				if (labels[i].textContent.trim().toLowerCase().indexOf(key.toLowerCase()) !== -1) {
					var forId = labels[i].htmlFor;
					if (forId) {
						var target = document.getElementById(forId);
						if (target) return target;
					}
					// label wrapping input
					var inner = labels[i].querySelector('input, textarea, select');
					if (inner) return inner;
				}
			}
			// c) [placeholder="key"]
			el = document.querySelector('[placeholder=' + JSON.stringify(key) + ']');
			if (el) return el;
			// d) [aria-label="key"]
			el = document.querySelector('[aria-label=' + JSON.stringify(key) + ']');
			if (el) return el;
			return null;
		}
		for (var i = 0; i < pairs.length; i++) {
			var key = pairs[i].k;
			var val = pairs[i].v;
			var el = findEl(key);
			if (!el) continue;
			var tag = el.tagName.toLowerCase();
			var type_ = (el.getAttribute('type') || '').toLowerCase();
			if (tag === 'select') {
				el.value = val;
				el.dispatchEvent(new Event('change', {bubbles: true}));
				filled++;
			} else if (type_ === 'checkbox' || type_ === 'radio') {
				var checked = (val === 'true' || val === el.value);
				if (el.checked !== checked) {
					el.click();
				}
				filled++;
			} else {
				// input / textarea / contenteditable
				el.focus();
				if (el.value !== undefined) {
					el.value = val;
				} else {
					el.textContent = val;
				}
				el.dispatchEvent(new Event('input', {bubbles: true}));
				el.dispatchEvent(new Event('change', {bubbles: true}));
				filled++;
			}
		}
		return filled;
	})(%s)`, string(pairsJSON))

	raw, err := p.Evaluate(ctx, fillJS)
	if err != nil {
		return 0, fmt.Errorf("camoufox: FillForm: %w", err)
	}
	switch n := raw.(type) {
	case float64:
		return int(n), nil
	case json.Number:
		f, _ := n.Float64()
		return int(f), nil
	}
	return 0, nil
}
