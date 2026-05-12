package camoufox

import (
	"context"
	"encoding/json"
	"fmt"
)

// OriginStorage holds the storage state for one origin.
type OriginStorage struct {
	Origin       string            `json:"origin"`
	LocalStorage map[string]string `json:"localStorage"`
	SessionStorage map[string]string `json:"sessionStorage"`
}

// StorageState is a Playwright-compatible snapshot of cookies and per-origin storage.
type StorageState struct {
	Cookies []Cookie        `json:"cookies"`
	Origins []OriginStorage `json:"origins"`
}

// LocalStorage returns a snapshot of window.localStorage for the page's current origin.
func (p *Page) LocalStorage(ctx context.Context) (map[string]string, error) {
	raw, err := p.Evaluate(ctx, `Object.fromEntries(Object.entries(localStorage))`)
	if err != nil {
		return nil, fmt.Errorf("camoufox: LocalStorage: %w", err)
	}
	return decodeStringMap(raw)
}

// SessionStorage returns a snapshot of window.sessionStorage for the page's current origin.
func (p *Page) SessionStorage(ctx context.Context) (map[string]string, error) {
	raw, err := p.Evaluate(ctx, `Object.fromEntries(Object.entries(sessionStorage))`)
	if err != nil {
		return nil, fmt.Errorf("camoufox: SessionStorage: %w", err)
	}
	return decodeStringMap(raw)
}

// SetLocalStorage sets key/value pairs in window.localStorage on the page's current origin.
func (p *Page) SetLocalStorage(ctx context.Context, items map[string]string) error {
	if len(items) == 0 {
		return nil
	}
	b, err := json.Marshal(items)
	if err != nil {
		return err
	}
	script := fmt.Sprintf(`(function(items){for(var k in items){localStorage.setItem(k,items[k]);}})(%s)`,
		string(b))
	_, err = p.Evaluate(ctx, script)
	return err
}

// ClearLocalStorage clears window.localStorage on the page's current origin.
func (p *Page) ClearLocalStorage(ctx context.Context) error {
	_, err := p.Evaluate(ctx, `localStorage.clear()`)
	return err
}

// StorageState collects a Playwright-style snapshot of cookies plus localStorage/sessionStorage
// per origin by iterating over the context's current pages.
func (c *BrowserContext) StorageState(ctx context.Context) (*StorageState, error) {
	cookies, err := c.Cookies(ctx)
	if err != nil {
		return nil, fmt.Errorf("camoufox: StorageState cookies: %w", err)
	}

	c.pagesMu.Lock()
	pages := make([]*Page, len(c.pages))
	copy(pages, c.pages)
	c.pagesMu.Unlock()

	seen := map[string]bool{}
	var origins []OriginStorage
	for _, pg := range pages {
		origin, err := originOfPage(ctx, pg)
		if err != nil || origin == "" || origin == "null" {
			continue
		}
		if seen[origin] {
			continue
		}
		seen[origin] = true

		ls, err := pg.LocalStorage(ctx)
		if err != nil {
			ls = map[string]string{}
		}
		ss, err := pg.SessionStorage(ctx)
		if err != nil {
			ss = map[string]string{}
		}
		origins = append(origins, OriginStorage{
			Origin:         origin,
			LocalStorage:   ls,
			SessionStorage: ss,
		})
	}

	return &StorageState{Cookies: cookies, Origins: origins}, nil
}

// originOfPage returns the scheme+host+port of the page's current document.
func originOfPage(ctx context.Context, p *Page) (string, error) {
	raw, err := p.Evaluate(ctx, `location.origin`)
	if err != nil {
		return "", err
	}
	s, _ := raw.(string)
	return s, nil
}

// decodeStringMap re-encodes a map[string]any returned by Evaluate as map[string]string.
func decodeStringMap(raw any) (map[string]string, error) {
	if raw == nil {
		return map[string]string{}, nil
	}
	m, ok := raw.(map[string]any)
	if !ok {
		return map[string]string{}, nil
	}
	out := make(map[string]string, len(m))
	for k, v := range m {
		switch sv := v.(type) {
		case string:
			out[k] = sv
		default:
			b, _ := json.Marshal(v)
			out[k] = string(b)
		}
	}
	return out, nil
}
