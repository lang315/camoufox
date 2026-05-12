package camoufox

import (
	"context"
	"encoding/json"
	"fmt"
)

// ExtractOptions configures Page.ExtractText.
type ExtractOptions struct {
	// IncludeHidden includes text from elements hidden via CSS when true.
	IncludeHidden bool
	// Selector restricts extraction to a subtree (default: body).
	Selector string
}

// Heading is a single heading entry returned by Page.Summary.
type Heading struct {
	Level int    `json:"level"`
	Text  string `json:"text"`
}

// PageSummary is the structured summary returned by Page.Summary.
type PageSummary struct {
	Title    string    `json:"title"`
	URL      string    `json:"url"`
	Headings []Heading `json:"headings"`
	MainText string    `json:"mainText"`
}

// ExtractText returns the visible text content of the page (or a subtree if
// opts.Selector is set). Script/style nodes are skipped; whitespace is normalised.
func (p *Page) ExtractText(ctx context.Context, opts ExtractOptions) (string, error) {
	root := "document.body"
	if opts.Selector != "" {
		root = fmt.Sprintf("document.querySelector(%s)", jsString(opts.Selector))
	}

	includeHidden := "false"
	if opts.IncludeHidden {
		includeHidden = "true"
	}

	script := fmt.Sprintf(`(function(root, includeHidden) {
		if (!root) return '';
		var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
			acceptNode: function(node) {
				var parent = node.parentElement;
				if (!parent) return NodeFilter.FILTER_REJECT;
				var tag = parent.tagName.toLowerCase();
				if (tag === 'script' || tag === 'style' || tag === 'noscript') return NodeFilter.FILTER_REJECT;
				if (!includeHidden) {
					var st = window.getComputedStyle(parent);
					if (st.display === 'none' || st.visibility === 'hidden') return NodeFilter.FILTER_REJECT;
				}
				return NodeFilter.FILTER_ACCEPT;
			}
		});
		var parts = [];
		while (walker.nextNode()) {
			var t = walker.currentNode.textContent.replace(/\s+/g, ' ').trim();
			if (t) parts.push(t);
		}
		return parts.join(' ');
	})(%s, %s)`, root, includeHidden)

	raw, err := p.Evaluate(ctx, script)
	if err != nil {
		return "", fmt.Errorf("camoufox: ExtractText: %w", err)
	}
	if raw == nil {
		return "", nil
	}
	s, _ := raw.(string)
	return s, nil
}

// Summary returns a structured summary of the current page: title, URL, all
// headings in DOM order, and the main text content (prefers <article>, then
// <main>, then body minus nav/header/footer/aside).
func (p *Page) Summary(ctx context.Context) (*PageSummary, error) {
	script := `(function() {
		var headings = [];
		var hs = document.querySelectorAll('h1,h2,h3,h4,h5,h6');
		for (var i = 0; i < hs.length; i++) {
			headings.push({level: parseInt(hs[i].tagName.substring(1), 10), text: hs[i].textContent.trim()});
		}

		function visibleText(root) {
			if (!root) return '';
			var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
				acceptNode: function(node) {
					var p = node.parentElement;
					if (!p) return NodeFilter.FILTER_REJECT;
					var tag = p.tagName.toLowerCase();
					if (tag === 'script' || tag === 'style' || tag === 'noscript') return NodeFilter.FILTER_REJECT;
					var st = window.getComputedStyle(p);
					if (st.display === 'none' || st.visibility === 'hidden') return NodeFilter.FILTER_REJECT;
					return NodeFilter.FILTER_ACCEPT;
				}
			});
			var parts = [];
			while (walker.nextNode()) {
				var t = walker.currentNode.textContent.replace(/\s+/g, ' ').trim();
				if (t) parts.push(t);
			}
			return parts.join(' ');
		}

		var mainEl = document.querySelector('article') ||
		             document.querySelector('main') ||
		             (function() {
		               var b = document.body;
		               if (!b) return null;
		               // clone body, strip nav/header/footer/aside
		               var clone = b.cloneNode(true);
		               ['nav','header','footer','aside'].forEach(function(tag) {
		                 var rem = clone.querySelectorAll(tag);
		                 for (var i = 0; i < rem.length; i++) rem[i].remove();
		               });
		               return clone;
		             })();

		return {
			title: document.title || '',
			url: location.href || '',
			headings: headings,
			mainText: visibleText(mainEl)
		};
	})()`

	raw, err := p.Evaluate(ctx, script)
	if err != nil {
		return nil, fmt.Errorf("camoufox: Summary: %w", err)
	}
	if raw == nil {
		return &PageSummary{}, nil
	}

	b, err := json.Marshal(raw)
	if err != nil {
		return nil, err
	}
	var ps PageSummary
	if err := json.Unmarshal(b, &ps); err != nil {
		return nil, fmt.Errorf("camoufox: Summary decode: %w", err)
	}
	return &ps, nil
}
