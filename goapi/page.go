package camoufox

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"sync"
	"time"

	"github.com/lang315/camoufox/goapi/pkg/juggler"
)

// Page is a single tab within a BrowserContext.
type Page struct {
	bc      *BrowserContext
	target  juggler.TargetInfo
	session *juggler.Session

	mu             sync.Mutex
	mainFrameID    string
	mainContextID  string
	contextReadyCh chan struct{}
	closed         chan struct{}

	framesMu sync.Mutex
	frames   map[string]*Frame

	subs []juggler.Subscription // owned by this page, deregistered on Close
}

// NewPage opens a fresh page in this context. It blocks until the
// browser attaches the page session and the main execution context
// is ready (so the first call to Evaluate has somewhere to land).
func (c *BrowserContext) NewPage(ctx context.Context) (*Page, error) {
	params := juggler.BrowserNewPageParams{BrowserContextID: c.id}
	var res juggler.BrowserNewPageResult
	if err := c.b.root.Call(ctx, "Browser.newPage", params, &res); err != nil {
		return nil, fmt.Errorf("camoufox: newPage: %w", err)
	}

	// Browser.attachedToTarget may have already landed (and been
	// buffered) before the response was decoded. awaitAttach handles
	// both ordering paths.
	attachCtx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	att, err := c.b.awaitAttach(attachCtx, res.TargetID)
	if err != nil {
		return nil, fmt.Errorf("camoufox: await attach: %w", err)
	}

	p := &Page{
		bc:             c,
		target:         att.TargetInfo,
		session:        c.b.conn.Session(att.SessionID),
		contextReadyCh: make(chan struct{}),
		closed:         make(chan struct{}),
		frames:         make(map[string]*Frame),
	}
	c.pagesMu.Lock()
	c.pages = append(c.pages, p)
	c.pagesMu.Unlock()
	c.b.mu.Lock()
	c.b.pages[p.target.TargetID] = p
	c.b.mu.Unlock()

	p.subscribe()
	p.registerFrameEvents()
	// Wait for the main-world execution context so the first
	// Evaluate doesn't fail. about:blank fires this within ms.
	select {
	case <-p.contextReadyCh:
	case <-time.After(5 * time.Second):
		// Continue anyway; some callers may only want navigate.
	case <-ctx.Done():
		return nil, ctx.Err()
	}
	return p, nil
}

func (p *Page) subscribe() {
	conn := p.bc.b.conn

	p.subs = append(p.subs, conn.On("Page.frameAttached", func(ev juggler.Event) {
		if ev.SessionID != p.session.ID() {
			return
		}
		var fa juggler.FrameAttachedEvent
		if err := json.Unmarshal(ev.Params, &fa); err != nil {
			return
		}
		if fa.ParentFrameID == "" {
			p.mu.Lock()
			if p.mainFrameID == "" {
				p.mainFrameID = fa.FrameID
			}
			p.mu.Unlock()
		}
	}))

	p.subs = append(p.subs, conn.On("Runtime.executionContextCreated", func(ev juggler.Event) {
		if ev.SessionID != p.session.ID() {
			return
		}
		var ec juggler.ExecutionContextCreatedEvent
		if err := json.Unmarshal(ev.Params, &ec); err != nil {
			return
		}
		p.mu.Lock()
		defer p.mu.Unlock()
		isMain := ec.AuxData.Name == ""
		// Only adopt main-world contexts as the page's primary ctx.
		// Isolated worlds (named) belong to per-script sandboxes and
		// won't accept the kind of expressions Evaluate runs.
		if !isMain {
			return
		}
		// Prefer the context belonging to the main frame.
		if p.mainFrameID != "" && ec.AuxData.FrameID != "" && ec.AuxData.FrameID != p.mainFrameID {
			return
		}
		p.mainContextID = ec.ExecutionContextID
		if p.mainFrameID == "" {
			p.mainFrameID = ec.AuxData.FrameID
		}
		select {
		case <-p.contextReadyCh:
		default:
			close(p.contextReadyCh)
		}
	}))

	p.subs = append(p.subs, conn.On("Runtime.executionContextDestroyed", func(ev juggler.Event) {
		if ev.SessionID != p.session.ID() {
			return
		}
		var d struct {
			ExecutionContextID string `json:"executionContextId"`
		}
		if err := json.Unmarshal(ev.Params, &d); err != nil {
			return
		}
		p.mu.Lock()
		defer p.mu.Unlock()
		if d.ExecutionContextID == p.mainContextID {
			p.mainContextID = ""
			p.contextReadyCh = make(chan struct{})
		}
	}))

	p.subs = append(p.subs, conn.On("Runtime.executionContextsCleared", func(ev juggler.Event) {
		if ev.SessionID != p.session.ID() {
			return
		}
		p.mu.Lock()
		defer p.mu.Unlock()
		p.mainContextID = ""
		p.contextReadyCh = make(chan struct{})
	}))
}

// TargetID returns the underlying juggler targetId.
func (p *Page) TargetID() string { return p.target.TargetID }

// MainFrameID returns the page's primary frame id once known.
func (p *Page) MainFrameID() string {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.mainFrameID
}

// WaitUntil controls how Goto decides navigation is "done".
type WaitUntil string

const (
	WaitUntilLoad             WaitUntil = "load"
	WaitUntilDOMContentLoaded WaitUntil = "DOMContentLoaded"
	WaitUntilCommit           WaitUntil = "commit" // returns as soon as Page.navigationCommitted fires
)

// GotoOptions tunes Goto behavior.
type GotoOptions struct {
	WaitUntil WaitUntil     // default: load
	Timeout   time.Duration // default: 30s
	Referer   string
}

// Goto navigates the main frame to url. Default waits for load.
func (p *Page) Goto(ctx context.Context, url string, opts ...GotoOptions) error {
	frame := p.MainFrameID()
	if frame == "" {
		// Force a value: targetId doubles as frameId only when the
		// frame is already attached; otherwise wait briefly for it.
		deadline := time.NewTimer(2 * time.Second)
		defer deadline.Stop()
	wait:
		for frame == "" {
			select {
			case <-time.After(20 * time.Millisecond):
				frame = p.MainFrameID()
			case <-deadline.C:
				break wait
			case <-ctx.Done():
				return ctx.Err()
			}
		}
		if frame == "" {
			return errors.New("camoufox: main frame not attached")
		}
	}

	opt := GotoOptions{WaitUntil: WaitUntilLoad, Timeout: 30 * time.Second}
	if len(opts) > 0 {
		if opts[0].WaitUntil != "" {
			opt.WaitUntil = opts[0].WaitUntil
		}
		if opts[0].Timeout > 0 {
			opt.Timeout = opts[0].Timeout
		}
		opt.Referer = opts[0].Referer
	}

	conn := p.bc.b.conn
	doneCh := make(chan struct{}, 1)
	var subs []juggler.Subscription
	switch opt.WaitUntil {
	case WaitUntilCommit:
		subs = append(subs, conn.On("Page.navigationCommitted", func(ev juggler.Event) {
			if ev.SessionID != p.session.ID() {
				return
			}
			var nc juggler.NavigationCommittedEvent
			if err := json.Unmarshal(ev.Params, &nc); err != nil {
				return
			}
			if nc.FrameID == frame {
				select {
				case doneCh <- struct{}{}:
				default:
				}
			}
		}))
	default:
		target := string(opt.WaitUntil)
		subs = append(subs, conn.On("Page.eventFired", func(ev juggler.Event) {
			if ev.SessionID != p.session.ID() {
				return
			}
			var fired juggler.EventFiredEvent
			if err := json.Unmarshal(ev.Params, &fired); err != nil {
				return
			}
			if fired.Name == target && fired.FrameID == frame {
				select {
				case doneCh <- struct{}{}:
				default:
				}
			}
		}))
	}
	defer func() {
		for _, s := range subs {
			conn.Off(s)
		}
	}()

	params := juggler.PageNavigateParams{FrameID: frame, URL: url, Referer: opt.Referer}
	var res juggler.PageNavigateResult
	if err := p.session.Call(ctx, "Page.navigate", params, &res); err != nil {
		return fmt.Errorf("camoufox: navigate: %w", err)
	}
	select {
	case <-doneCh:
		return nil
	case <-time.After(opt.Timeout):
		return fmt.Errorf("camoufox: goto: timed out waiting for %s", opt.WaitUntil)
	case <-ctx.Done():
		return ctx.Err()
	}
}

// Evaluate runs expression in the main world and returns the value.
// Booleans / numbers / strings / JSON-serializable objects decode
// straight into the returned any.
func (p *Page) Evaluate(ctx context.Context, expression string) (any, error) {
	ctxID, err := p.awaitMainContext(ctx, 5*time.Second)
	if err != nil {
		return nil, err
	}
	params := juggler.EvaluateParams{
		ExecutionContextID: ctxID,
		Expression:         expression,
		ReturnByValue:      true,
	}
	var res juggler.EvaluateResult
	if err := p.session.Call(ctx, "Runtime.evaluate", params, &res); err != nil {
		// Context may have been destroyed by an in-flight navigation;
		// wait for the next one and try once more.
		if isContextGone(err) {
			ctxID, err2 := p.awaitMainContext(ctx, 5*time.Second)
			if err2 != nil {
				return nil, err
			}
			params.ExecutionContextID = ctxID
			if err := p.session.Call(ctx, "Runtime.evaluate", params, &res); err != nil {
				return nil, err
			}
		} else {
			return nil, err
		}
	}
	if res.ExceptionDetails != nil {
		return nil, fmt.Errorf("camoufox: page exception: %s", res.ExceptionDetails.Text)
	}
	if res.Result == nil || len(res.Result.Value) == 0 {
		return nil, nil
	}
	var v any
	if err := json.Unmarshal(res.Result.Value, &v); err != nil {
		return nil, fmt.Errorf("camoufox: decode evaluate result: %w", err)
	}
	return v, nil
}

// Screenshot captures the visible viewport as PNG bytes. clip lets
// the caller select a region; pass a zero-value clip for the full
// 1280x720 default.
func (p *Page) Screenshot(ctx context.Context, clip juggler.PageScreenshotClip) ([]byte, error) {
	if clip == (juggler.PageScreenshotClip{}) {
		clip = juggler.PageScreenshotClip{Width: 1280, Height: 720}
	}
	params := juggler.PageScreenshotParams{
		MimeType: "image/png",
		Clip:     clip,
	}
	var res juggler.PageScreenshotResult
	if err := p.session.Call(ctx, "Page.screenshot", params, &res); err != nil {
		return nil, err
	}
	return base64.StdEncoding.DecodeString(res.Data)
}

// SetViewportSize sets the viewport.
func (p *Page) SetViewportSize(ctx context.Context, width, height int) error {
	sz := juggler.Size{Width: width, Height: height}
	params := juggler.SetViewportSizeParams{ViewportSize: &sz}
	return p.session.Call(ctx, "Page.setViewportSize", params, nil)
}

// AddInitScript adds a per-page init script.
func (p *Page) AddInitScript(ctx context.Context, script string) error {
	params := juggler.PageSetInitScriptsParams{
		Scripts: []juggler.InitScript{{Script: script}},
	}
	return p.session.Call(ctx, "Page.setInitScripts", params, nil)
}

// awaitMainContext returns the current main-world execution context
// id, waiting up to d for one to appear if the page is mid-navigation.
func (p *Page) awaitMainContext(ctx context.Context, d time.Duration) (string, error) {
	p.mu.Lock()
	if p.mainContextID != "" {
		id := p.mainContextID
		p.mu.Unlock()
		return id, nil
	}
	ch := p.contextReadyCh
	p.mu.Unlock()
	timer := time.NewTimer(d)
	defer timer.Stop()
	select {
	case <-ch:
	case <-timer.C:
		return "", errors.New("camoufox: timed out waiting for execution context")
	case <-ctx.Done():
		return "", ctx.Err()
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.mainContextID == "" {
		return "", errors.New("camoufox: execution context appeared and vanished")
	}
	return p.mainContextID, nil
}

// isContextGone matches "Failed to find execution context" errors
// from juggler/content/Runtime.js.
func isContextGone(err error) bool {
	if err == nil {
		return false
	}
	return strings.Contains(err.Error(), "Failed to find execution context")
}

// Close shuts the page down via Page.close.
func (p *Page) Close(ctx context.Context) error {
	defer func() {
		for _, s := range p.subs {
			p.bc.b.conn.Off(s)
		}
		p.subs = nil
		select {
		case <-p.closed:
		default:
			close(p.closed)
		}
	}()
	return p.session.Call(ctx, "Page.close", map[string]any{"runBeforeUnload": false}, nil)
}
