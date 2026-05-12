package camoufox

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/lang315/camoufox/goapi/pkg/juggler"
)

// Dialog represents an open browser dialog (alert, confirm, prompt, beforeunload).
type Dialog struct {
	Type         string
	Message      string
	DefaultValue string

	page     *Page
	dialogID string
}

// Accept accepts the dialog. For prompt dialogs, promptText is sent as the input.
func (d *Dialog) Accept(ctx context.Context, promptText string) error {
	params := juggler.HandleDialogParams{
		DialogID:   d.dialogID,
		Accept:     true,
		PromptText: promptText,
	}
	if err := d.page.session.Call(ctx, "Page.handleDialog", params, nil); err != nil {
		return fmt.Errorf("camoufox: dialog Accept: %w", err)
	}
	return nil
}

// Dismiss dismisses the dialog (equivalent to clicking Cancel).
func (d *Dialog) Dismiss(ctx context.Context) error {
	params := juggler.HandleDialogParams{
		DialogID: d.dialogID,
		Accept:   false,
	}
	if err := d.page.session.Call(ctx, "Page.handleDialog", params, nil); err != nil {
		return fmt.Errorf("camoufox: dialog Dismiss: %w", err)
	}
	return nil
}

// OnDialog registers a handler for Page.dialogOpened events on this page.
// The returned Subscription can be passed to p.Off to deregister.
// An internal subscription to Page.dialogClosed is added to p.subs for
// lifecycle cleanup; it fires automatically and cannot be disabled separately.
func (p *Page) OnDialog(handler func(*Dialog)) juggler.Subscription {
	p.subs = append(p.subs, p.bc.b.conn.On("Page.dialogClosed", func(ev juggler.Event) {
		if ev.SessionID != p.session.ID() {
			return
		}
	}))
	return p.bc.b.conn.On("Page.dialogOpened", func(ev juggler.Event) {
		if ev.SessionID != p.session.ID() {
			return
		}
		var de juggler.DialogOpenedEvent
		if err := json.Unmarshal(ev.Params, &de); err != nil {
			return
		}
		d := &Dialog{
				Type:         de.Type,
				Message:      de.Message,
				DefaultValue: de.DefaultValue,
				page:         p,
				dialogID:     de.DialogID,
			}
			go handler(d)
	})
}
