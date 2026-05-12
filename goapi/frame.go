package camoufox

import (
	"context"
	"encoding/json"
	"errors"
	"sync"
	"time"

	"github.com/lang315/camoufox/goapi/pkg/juggler"
)

// Frame is a single browsing context (the main frame plus any
// <iframe>s). Each frame owns its own main-world execution context
// in the browser.
type Frame struct {
	page          *Page
	id            string
	parentID      string
	mu            sync.Mutex
	mainContextID string
	readyCh       chan struct{}
	url           string
	name          string
}

// ID returns the juggler frameId.
func (f *Frame) ID() string { return f.id }

// URL returns the frame's last committed URL.
func (f *Frame) URL() string {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.url
}

// Name returns the frame's name attribute (empty for unnamed frames).
func (f *Frame) Name() string {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.name
}

// Parent returns the parent Frame, or nil for the main frame.
func (f *Frame) Parent() *Frame {
	if f.parentID == "" {
		return nil
	}
	return f.page.findFrame(f.parentID)
}

// IsMain reports whether this is the page's top-level frame.
func (f *Frame) IsMain() bool { return f.parentID == "" }

// Evaluate runs expression inside this frame's main-world context.
func (f *Frame) Evaluate(ctx context.Context, expression string) (any, error) {
	ctxID, err := f.awaitContext(ctx, 5*time.Second)
	if err != nil {
		return nil, err
	}
	params := juggler.EvaluateParams{
		ExecutionContextID: ctxID,
		Expression:         expression,
		ReturnByValue:      true,
	}
	var res juggler.EvaluateResult
	if err := f.page.session.Call(ctx, "Runtime.evaluate", params, &res); err != nil {
		return nil, err
	}
	if res.ExceptionDetails != nil {
		return nil, errors.New("camoufox: " + res.ExceptionDetails.Text)
	}
	if res.Result == nil || len(res.Result.Value) == 0 {
		return nil, nil
	}
	var v any
	_ = json.Unmarshal(res.Result.Value, &v)
	return v, nil
}

func (f *Frame) awaitContext(ctx context.Context, d time.Duration) (string, error) {
	f.mu.Lock()
	if f.mainContextID != "" {
		id := f.mainContextID
		f.mu.Unlock()
		return id, nil
	}
	ch := f.readyCh
	f.mu.Unlock()
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ch:
		f.mu.Lock()
		defer f.mu.Unlock()
		if f.mainContextID == "" {
			return "", errors.New("camoufox: frame context disappeared")
		}
		return f.mainContextID, nil
	case <-t.C:
		return "", errors.New("camoufox: timed out waiting for frame context")
	case <-ctx.Done():
		return "", ctx.Err()
	}
}

// Frames returns the page's known frames (snapshot). The main frame
// is always first.
func (p *Page) Frames() []*Frame {
	p.framesMu.Lock()
	defer p.framesMu.Unlock()
	out := make([]*Frame, 0, len(p.frames))
	// Main frame first.
	for _, f := range p.frames {
		if f.IsMain() {
			out = append(out, f)
			break
		}
	}
	for _, f := range p.frames {
		if !f.IsMain() {
			out = append(out, f)
		}
	}
	return out
}

// MainFrame returns the top-level frame.
func (p *Page) MainFrame() *Frame {
	for _, f := range p.Frames() {
		if f.IsMain() {
			return f
		}
	}
	return nil
}

func (p *Page) findFrame(id string) *Frame {
	p.framesMu.Lock()
	defer p.framesMu.Unlock()
	return p.frames[id]
}

// registerFrameEvents wires Page.frameAttached / frameDetached and
// Runtime.executionContextCreated to keep p.frames in sync. Returns
// the subscription handles so Close can remove them.
func (p *Page) registerFrameEvents() {
	conn := p.bc.b.conn
	p.subs = append(p.subs, conn.On("Page.frameAttached", func(ev juggler.Event) {
		if ev.SessionID != p.session.ID() {
			return
		}
		var fa juggler.FrameAttachedEvent
		if err := json.Unmarshal(ev.Params, &fa); err != nil {
			return
		}
		p.framesMu.Lock()
		if _, ok := p.frames[fa.FrameID]; !ok {
			p.frames[fa.FrameID] = &Frame{
				page:     p,
				id:       fa.FrameID,
				parentID: fa.ParentFrameID,
				readyCh:  make(chan struct{}),
			}
		}
		p.framesMu.Unlock()
	}))

	p.subs = append(p.subs, conn.On("Page.frameDetached", func(ev juggler.Event) {
		if ev.SessionID != p.session.ID() {
			return
		}
		var fd struct {
			FrameID string `json:"frameId"`
		}
		if err := json.Unmarshal(ev.Params, &fd); err != nil {
			return
		}
		p.framesMu.Lock()
		delete(p.frames, fd.FrameID)
		p.framesMu.Unlock()
	}))

	p.subs = append(p.subs, conn.On("Runtime.executionContextCreated", func(ev juggler.Event) {
		if ev.SessionID != p.session.ID() {
			return
		}
		var ec juggler.ExecutionContextCreatedEvent
		if err := json.Unmarshal(ev.Params, &ec); err != nil {
			return
		}
		if ec.AuxData.Name != "" || ec.AuxData.FrameID == "" {
			return // isolated world or no frame info
		}
		p.framesMu.Lock()
		fr := p.frames[ec.AuxData.FrameID]
		if fr == nil {
			fr = &Frame{
				page:    p,
				id:      ec.AuxData.FrameID,
				readyCh: make(chan struct{}),
			}
			p.frames[ec.AuxData.FrameID] = fr
		}
		p.framesMu.Unlock()
		fr.mu.Lock()
		fr.mainContextID = ec.ExecutionContextID
		select {
		case <-fr.readyCh:
		default:
			close(fr.readyCh)
		}
		fr.mu.Unlock()
	}))

	p.subs = append(p.subs, conn.On("Page.navigationCommitted", func(ev juggler.Event) {
		if ev.SessionID != p.session.ID() {
			return
		}
		var nc juggler.NavigationCommittedEvent
		if err := json.Unmarshal(ev.Params, &nc); err != nil {
			return
		}
		p.framesMu.Lock()
		fr := p.frames[nc.FrameID]
		if fr == nil {
			fr = &Frame{
				page:    p,
				id:      nc.FrameID,
				readyCh: make(chan struct{}),
			}
			p.frames[nc.FrameID] = fr
		}
		p.framesMu.Unlock()
		fr.mu.Lock()
		fr.url = nc.URL
		fr.name = nc.Name
		fr.mu.Unlock()
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
		p.framesMu.Lock()
		defer p.framesMu.Unlock()
		for _, fr := range p.frames {
			fr.mu.Lock()
			if fr.mainContextID == d.ExecutionContextID {
				fr.mainContextID = ""
				fr.readyCh = make(chan struct{})
			}
			fr.mu.Unlock()
		}
	}))
}
