package camoufox

import (
	"context"
	"fmt"

	"github.com/lang315/camoufox/goapi/pkg/juggler"
)

// GrantPermissions grants the listed permissions for the given origin within this context.
func (c *BrowserContext) GrantPermissions(ctx context.Context, origin string, perms []string) error {
	params := juggler.BrowserGrantPermissionsParams{
		BrowserContextID: c.id,
		Origin:           origin,
		Permissions:      perms,
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
