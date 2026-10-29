package camoufox

import "context"

func (p *Page) ExposeBinding(ctx context.Context, name, script string, fn func(payload string)) (func(), error) {
	return func() {}, nil
}

func (c *BrowserContext) SetBypassCSP(ctx context.Context, bypass bool) error { return nil }
