package camoufox

import (
	"context"

	"github.com/lang315/camoufox/goapi/pkg/juggler"
)

// Cookie / CookieOptions are re-exported so callers do not need to
// import pkg/juggler.
type (
	Cookie        = juggler.Cookie
	CookieOptions = juggler.CookieOptions
)

// Cookies returns all cookies stored in this BrowserContext.
func (c *BrowserContext) Cookies(ctx context.Context) ([]Cookie, error) {
	var res juggler.BrowserGetCookiesResult
	if err := c.b.root.Call(ctx, "Browser.getCookies",
		juggler.BrowserGetCookiesParams{BrowserContextID: c.id}, &res); err != nil {
		return nil, err
	}
	return res.Cookies, nil
}

// SetCookies bulk-adds cookies to this context. Each entry must
// include either url or domain+path.
func (c *BrowserContext) SetCookies(ctx context.Context, cookies ...CookieOptions) error {
	return c.b.root.Call(ctx, "Browser.setCookies",
		juggler.BrowserSetCookiesParams{BrowserContextID: c.id, Cookies: cookies}, nil)
}

// ClearCookies wipes every cookie in this context.
func (c *BrowserContext) ClearCookies(ctx context.Context) error {
	return c.b.root.Call(ctx, "Browser.clearCookies",
		juggler.BrowserClearCookiesParams{BrowserContextID: c.id}, nil)
}
