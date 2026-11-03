package camoufox

import (
	"context"
	"fmt"

	"github.com/lang315/camoufox/goapi/pkg/juggler"
)

// jugglerPermissions maps the permission names of Playwright's API to Juggler's
// (ALL_PERMISSIONS in browser/additions/juggler/TargetRegistry.js). Playwright's client does
// the same translation (playwright-core firefox/ffBrowser.ts, doGrantPermissions); Juggler
// itself denies a name it does not know, without an error. Playwright's persistent-storage,
// push and screen-wake-lock are left out: Juggler has no such permission to grant.
var jugglerPermissions = map[string][]string{
	"geolocation":          {"geo"},
	"notifications":        {"desktop-notification"},
	"local-network-access": {"local-network", "loopback-network"},
}

// GrantPermissions grants the listed permissions (Playwright's names: "geolocation",
// "notifications", "local-network-access") for the given origin within this context.
// A name Juggler cannot grant is an error, not a grant that does nothing.
func (c *BrowserContext) GrantPermissions(ctx context.Context, origin string, perms []string) error {
	var names []string
	for _, p := range perms {
		mapped, ok := jugglerPermissions[p]
		if !ok {
			return fmt.Errorf("camoufox: grantPermissions: unsupported permission %q", p)
		}
		names = append(names, mapped...)
	}
	params := juggler.BrowserGrantPermissionsParams{
		BrowserContextID: c.id,
		Origin:           origin,
		Permissions:      names,
	}
	if err := c.b.root.Call(ctx, "Browser.grantPermissions", params, nil); err != nil {
		return fmt.Errorf("camoufox: grantPermissions: %w", err)
	}
	return nil
}

// ResetPermissions clears all permission overrides for this context.
func (c *BrowserContext) ResetPermissions(ctx context.Context) error {
	params := juggler.BrowserResetPermissionsParams{BrowserContextID: c.id}
	if err := c.b.root.Call(ctx, "Browser.resetPermissions", params, nil); err != nil {
		return fmt.Errorf("camoufox: resetPermissions: %w", err)
	}
	return nil
}
