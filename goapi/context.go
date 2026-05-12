package camoufox

import (
	"context"
	"fmt"
	"sync"

	"github.com/lang315/camoufox/goapi/pkg/juggler"
)

// BrowserContext is a partitioned environment (cookies, storage)
// inside a Browser. Mirrors browserContext in Playwright/Juggler.
type BrowserContext struct {
	b  *Browser
	id string // browserContextId, empty for default context

	pagesMu sync.Mutex
	pages   []*Page
}

// NewContext creates a fresh browser context. The context is removed
// when the parent Browser is closed (removeOnDetach=true).
func (b *Browser) NewContext(ctx context.Context) (*BrowserContext, error) {
	var res juggler.CreateBrowserContextResult
	params := juggler.CreateBrowserContextParams{RemoveOnDetach: true}
	if err := b.root.Call(ctx, "Browser.createBrowserContext", params, &res); err != nil {
		return nil, fmt.Errorf("camoufox: createBrowserContext: %w", err)
	}
	bc := &BrowserContext{b: b, id: res.BrowserContextID}
	b.mu.Lock()
	b.contexts[res.BrowserContextID] = bc
	b.mu.Unlock()
	return bc, nil
}

// DefaultContext returns the implicit context attached at startup
// (no browserContextId — applies to default profile).
func (b *Browser) DefaultContext() *BrowserContext {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.defaultCtx == nil {
		b.defaultCtx = &BrowserContext{b: b, id: ""}
		b.contexts[""] = b.defaultCtx
	}
	return b.defaultCtx
}

// ID returns the underlying browserContextId. Empty for the default
// context.
func (c *BrowserContext) ID() string { return c.id }

// Close removes the context and discards its pages.
func (c *BrowserContext) Close(ctx context.Context) error {
	if c.id == "" {
		return nil // default context cannot be removed
	}
	params := juggler.RemoveBrowserContextParams{BrowserContextID: c.id}
	if err := c.b.root.Call(ctx, "Browser.removeBrowserContext", params, nil); err != nil {
		return fmt.Errorf("camoufox: removeBrowserContext: %w", err)
	}
	c.b.mu.Lock()
	delete(c.b.contexts, c.id)
	c.b.mu.Unlock()
	return nil
}

// AddInitScript registers a script to run on every new document.
// Applies to all pages of this context.
func (c *BrowserContext) AddInitScript(ctx context.Context, script string) error {
	params := juggler.BrowserSetInitScriptsParams{
		BrowserContextID: c.id,
		Scripts:          []juggler.InitScript{{Script: script}},
	}
	return c.b.root.Call(ctx, "Browser.setInitScripts", params, nil)
}

// SetExtraHTTPHeaders applies headers to all subsequent requests in
// this context.
func (c *BrowserContext) SetExtraHTTPHeaders(ctx context.Context, headers map[string]string) error {
	params := juggler.BrowserSetExtraHTTPHeadersParams{BrowserContextID: c.id}
	for k, v := range headers {
		params.Headers = append(params.Headers, juggler.HTTPHeader{Name: k, Value: v})
	}
	return c.b.root.Call(ctx, "Browser.setExtraHTTPHeaders", params, nil)
}

// SetGeolocation sets the geolocation override (use nil to clear).
func (c *BrowserContext) SetGeolocation(ctx context.Context, geo *juggler.Geolocation) error {
	params := juggler.BrowserSetGeolocationOverrideParams{
		BrowserContextID: c.id,
		Geolocation:      geo,
	}
	return c.b.root.Call(ctx, "Browser.setGeolocationOverride", params, nil)
}
