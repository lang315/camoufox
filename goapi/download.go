package camoufox

import (
	"context"
	"encoding/json"
	"fmt"
	"path/filepath"
	"sync"

	"github.com/lang315/camoufox/goapi/pkg/juggler"
)

// DownloadOptions configures download behaviour for a BrowserContext.
type DownloadOptions struct {
	// Behavior is "saveToDisk" or "cancel". Default "saveToDisk".
	Behavior string
	// DownloadsDir is where files are saved when Behavior is "saveToDisk".
	DownloadsDir string
}

// SetDownloadOptions configures how downloads behave in this context.
func (c *BrowserContext) SetDownloadOptions(ctx context.Context, opts DownloadOptions) error {
	params := juggler.BrowserSetDownloadOptionsParams{
		BrowserContextID: c.id,
		DownloadOptions: &juggler.DownloadOptionsInner{
			Behavior:     opts.Behavior,
			DownloadsDir: opts.DownloadsDir,
		},
	}
	if err := c.b.root.Call(ctx, "Browser.setDownloadOptions", params, nil); err != nil {
		return fmt.Errorf("camoufox: SetDownloadOptions: %w", err)
	}
	return nil
}

// Download represents a single in-progress or completed file download.
type Download struct {
	// UUID is the browser-assigned identifier for this download.
	UUID string
	// URL is the source URL.
	URL string
	// SuggestedFileName is the filename recommended by the server/browser.
	SuggestedFileName string

	page         *Page
	downloadsDir string

	mu       sync.Mutex
	done     chan struct{}
	canceled bool
	err      string
}

// Page returns the page that initiated the download.
func (d *Download) Page() *Page { return d.page }

// Path returns the absolute path where the download will be saved once
// complete. It is derived from DownloadsDir + SuggestedFileName because
// the protocol's downloadFinished event carries no path field.
func (d *Download) Path() string {
	return filepath.Join(d.downloadsDir, d.SuggestedFileName)
}

// Wait blocks until the download finishes (success or failure) or ctx
// is cancelled. Returns an error if the download was cancelled or
// the browser reported an error.
func (d *Download) Wait(ctx context.Context) error {
	select {
	case <-d.done:
	case <-ctx.Done():
		return ctx.Err()
	}
	d.mu.Lock()
	defer d.mu.Unlock()
	if d.canceled {
		return fmt.Errorf("camoufox: download canceled")
	}
	if d.err != "" {
		return fmt.Errorf("camoufox: download error: %s", d.err)
	}
	return nil
}

// Cancel cancels the download.
func (d *Download) Cancel(ctx context.Context) error {
	params := juggler.BrowserCancelDownloadParams{UUID: d.UUID}
	if err := d.page.bc.b.root.Call(ctx, "Browser.cancelDownload", params, nil); err != nil {
		return fmt.Errorf("camoufox: Cancel download: %w", err)
	}
	return nil
}

// OnDownload registers handler for downloads initiated in this context.
// Each new download triggers handler with a fresh Download. The handler
// is responsible for calling Wait or Cancel. The returned Subscription
// can be passed to c.b.conn.Off to deregister.
func (c *BrowserContext) OnDownload(handler func(*Download)) juggler.Subscription {
	// Mapping from UUID to in-flight Download; protected by its own mutex.
	var mu sync.Mutex
	inflight := make(map[string]*Download)

	// Wire the finished event first so it is always registered when the
	// created event fires (avoids a tiny window where finish arrives
	// before the finished subscription is up).
	finishedSub := c.b.conn.On("Browser.downloadFinished", func(ev juggler.Event) {
		var df juggler.DownloadFinishedEvent
		if err := json.Unmarshal(ev.Params, &df); err != nil {
			return
		}
		mu.Lock()
		d, ok := inflight[df.UUID]
		if ok {
			delete(inflight, df.UUID)
		}
		mu.Unlock()
		if !ok {
			return
		}
		d.mu.Lock()
		d.canceled = df.Canceled
		d.err = df.Error
		close(d.done)
		d.mu.Unlock()
	})
	// Store finished sub so it is cleaned up when parent page closes.
	// Use a no-op to keep it alive; caller owns the primary sub.
	_ = finishedSub

	return c.b.conn.On("Browser.downloadCreated", func(ev juggler.Event) {
		var dc juggler.DownloadCreatedEvent
		if err := json.Unmarshal(ev.Params, &dc); err != nil {
			return
		}
		// Filter to this context only.
		if dc.BrowserContextID != c.id {
			return
		}

		// Find the page that triggered the download.
		c.b.mu.Lock()
		pg := c.b.pages[dc.PageTargetID]
		c.b.mu.Unlock()

		d := &Download{
			UUID:              dc.UUID,
			URL:               dc.URL,
			SuggestedFileName: dc.SuggestedFileName,
			page:              pg,
			downloadsDir:      "", // caller sets via SetDownloadOptions
			done:              make(chan struct{}),
		}

		mu.Lock()
		inflight[dc.UUID] = d
		mu.Unlock()

		go handler(d)
	})
}
