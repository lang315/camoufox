package camoufox

import (
	"context"
	"encoding/json"
	"fmt"
	"time"
)

// DismissOverlayOptions configures Page.DismissOverlays.
type DismissOverlayOptions struct {
	// MinZIndex is the minimum computed z-index to consider an overlay (default 1000).
	MinZIndex int
	// CloseSelectors is the ordered list of CSS selectors to try for a close button.
	// Defaults to common close-button patterns when nil.
	CloseSelectors []string
	// MaxDismiss caps the number of overlays dismissed in one call (default 5).
	MaxDismiss int
}

// defaultCloseSelectors are tried in order inside each detected overlay.
var defaultCloseSelectors = []string{
	`[aria-label*="close" i]`,
	`button[aria-label*="dismiss" i]`,
	`[class*="close"]`,
	`[role="button"]`,
}

// DismissOverlays walks fixed/absolute/sticky elements with high z-index, finds the
// first matching close control inside each, clicks it, and returns the count dismissed.
// Heuristic — no platform-specific strings.
//
// Tests for DismissOverlays are omitted: the heuristic depends on real overlay markup
// that is hard to assert deterministically in a unit test.
func (p *Page) DismissOverlays(ctx context.Context, opts DismissOverlayOptions) (int, error) {
	if opts.MinZIndex <= 0 {
		opts.MinZIndex = 1000
	}
	if opts.MaxDismiss <= 0 {
		opts.MaxDismiss = 5
	}
	closeSelectors := opts.CloseSelectors
	if len(closeSelectors) == 0 {
		closeSelectors = defaultCloseSelectors
	}

	type overlayInfo struct {
		Index    int    `json:"index"`
		Selector string `json:"selector"` // unique nth-child selector
		HasClose bool   `json:"hasClose"`
		CloseSel string `json:"closeSel"`
	}

	selectorsJSON, _ := json.Marshal(closeSelectors)

	// JS: walk all elements, collect overlays with a matching close button.
	detectJS := fmt.Sprintf(`(function(minZ, closeSelectors) {
		var results = [];
		var els = Array.from(document.querySelectorAll('*'));
		for (var i = 0; i < els.length && results.length < 20; i++) {
			var el = els[i];
			var st = window.getComputedStyle(el);
			var pos = st.position;
			if (pos !== 'fixed' && pos !== 'absolute' && pos !== 'sticky') continue;
			var z = parseInt(st.zIndex, 10);
			if (isNaN(z) || z < minZ) continue;
			// must be visible
			if (st.display === 'none' || st.visibility === 'hidden' || st.opacity === '0') continue;
			var rect = el.getBoundingClientRect();
			if (rect.width === 0 || rect.height === 0) continue;

			var closeSel = '';
			for (var j = 0; j < closeSelectors.length; j++) {
				var btn = el.querySelector(closeSelectors[j]);
				if (btn) {
					// produce a unique data marker so we can click it by index
					btn.setAttribute('data-camoufox-dismiss', String(results.length));
					closeSel = '[data-camoufox-dismiss="' + results.length + '"]';
					break;
				}
			}
			// also match ×/X/Close text in any child button/role=button
			if (!closeSel) {
				var btns = Array.from(el.querySelectorAll('button, [role="button"]'));
				for (var k = 0; k < btns.length; k++) {
					var t = (btns[k].textContent || '').trim();
					if (t === '×' || t === 'X' || t === 'x' || t.toLowerCase() === 'close') {
						btns[k].setAttribute('data-camoufox-dismiss', String(results.length));
						closeSel = '[data-camoufox-dismiss="' + results.length + '"]';
						break;
					}
				}
			}
			results.push({index: results.length, hasClose: !!closeSel, closeSel: closeSel});
		}
		return results;
	})(%d, %s)`, opts.MinZIndex, string(selectorsJSON))

	raw, err := p.Evaluate(ctx, detectJS)
	if err != nil {
		return 0, fmt.Errorf("camoufox: DismissOverlays detect: %w", err)
	}
	if raw == nil {
		return 0, nil
	}

	b, err := json.Marshal(raw)
	if err != nil {
		return 0, err
	}
	var overlays []overlayInfo
	if err := json.Unmarshal(b, &overlays); err != nil {
		return 0, err
	}

	dismissed := 0
	for _, ov := range overlays {
		if dismissed >= opts.MaxDismiss {
			break
		}
		if !ov.HasClose || ov.CloseSel == "" {
			continue
		}
		clickJS := fmt.Sprintf(`(function(sel) {
			var btn = document.querySelector(sel);
			if (!btn) return false;
			btn.removeAttribute('data-camoufox-dismiss');
			btn.click();
			return true;
		})(%s)`, jsString(ov.CloseSel))

		result, err := p.Evaluate(ctx, clickJS)
		if err != nil {
			continue
		}
		if ok, _ := result.(bool); ok {
			dismissed++
			// brief pause for any dismiss animation.
			select {
			case <-time.After(200 * time.Millisecond):
			case <-ctx.Done():
				return dismissed, ctx.Err()
			}
		}
	}
	return dismissed, nil
}
