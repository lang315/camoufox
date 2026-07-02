package camoufox

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"time"

	"github.com/lang315/camoufox/goapi/pkg/juggler"
)

// FileChooser represents a file-chooser dialog intercepted via
// Page.setInterceptFileChooserDialog. Call SetFiles to complete it.
type FileChooser struct {
	Element    *ElementHandle
	IsMultiple bool
}

// SetFiles satisfies the chooser by forwarding the given file paths to
// the underlying input element.
func (fc *FileChooser) SetFiles(ctx context.Context, paths []string) error {
	return fc.Element.SetInputFiles(ctx, paths)
}

// SetInputFiles assigns local file paths to the <input type="file">
// represented by this handle. Wraps Page.setFileInputFiles.
func (e *ElementHandle) SetInputFiles(ctx context.Context, paths []string) error {
	frameID := e.frameID
	if frameID == "" {
		frameID = e.page.MainFrameID()
	}
	params := juggler.PageSetFileInputFilesParams{
		FrameID:  frameID,
		ObjectID: e.objectID,
		Files:    paths,
	}
	if err := e.page.session.Call(ctx, "Page.setFileInputFiles", params, nil); err != nil {
		return fmt.Errorf("camoufox: SetInputFiles: %w", err)
	}
	return nil
}

// OnFileChooser registers handler to receive intercepted file-chooser
// dialogs on this page. Enables interception automatically on first
// call. Disable interception by removing all OnFileChooser
// subscriptions and calling Page.setInterceptFileChooserDialog false
// explicitly if needed.
//
// The returned Subscription can be passed to p.bc.b.conn.Off to
// deregister.
func (p *Page) OnFileChooser(handler func(*FileChooser)) juggler.Subscription {
	// Enable interception; log on failure so the caller can diagnose missing events.
	if err := p.session.Call(context.Background(), "Page.setInterceptFileChooserDialog",
		juggler.PageSetInterceptFileChooserParams{Enabled: true}, nil); err != nil {
		log.Printf("camoufox: OnFileChooser: setInterceptFileChooserDialog: %v", err)
	}

	return p.bc.b.conn.On("Page.fileChooserOpened", func(ev juggler.Event) {
		if ev.SessionID != p.session.ID() {
			return
		}
		var fce juggler.FileChooserOpenedEvent
		if err := json.Unmarshal(ev.Params, &fce); err != nil {
			return
		}

		// Resolve the frameID by matching executionContextId against
		// the frames map (the event does not carry a frameId directly).
		var frameID string
		p.framesMu.Lock()
		for _, fr := range p.frames {
			fr.mu.Lock()
			if fr.mainContextID == fce.ExecutionContextID {
				frameID = fr.id
			}
			fr.mu.Unlock()
			if frameID != "" {
				break
			}
		}
		p.framesMu.Unlock()
		if frameID == "" {
			frameID = p.MainFrameID()
		}

		el := p.wrapObject(frameID, fce.ExecutionContextID, fce.Element.ObjectID)

		// The multiple-flag probe and the user handler both make blocking RPCs.
		// This callback runs on the juggler readLoop goroutine, which must stay
		// free to deliver responses (see EventHandler contract in dispatcher.go);
		// blocking it here means the probe's own response can never arrive — a
		// self-deadlock. Run the probe and handler off readLoop.
		go func() {
			pctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
			defer cancel()
			var isMultiple bool
			res, err := p.callFunction(pctx, fce.ExecutionContextID,
				`function(el) { return el.multiple; }`,
				[]juggler.CallFunctionArgument{{ObjectID: fce.Element.ObjectID}}, true)
			if err == nil && res.Result != nil {
				_ = json.Unmarshal(res.Result.Value, &isMultiple)
			}
			handler(&FileChooser{Element: el, IsMultiple: isMultiple})
		}()
	})
}
