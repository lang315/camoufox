package camoufox

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"time"

	"github.com/lang315/camoufox/goapi/pkg/juggler"
)

// ElementHandle is a reference to a single DOM element living inside
// the browser. Methods on ElementHandle route through Juggler's
// Runtime.callFunction so the handle survives across reflow / reflow
// as long as the underlying JS object isn't garbage-collected.
//
// Each handle holds an objectId that is only meaningful within its
// originating executionContext. Call Dispose to release the browser-
// side reference when done.
type ElementHandle struct {
	page     *Page
	objectID string
	ctxID    string
	frameID  string
}

// Box is the bounding rectangle of a DOM element in viewport coordinates.
type Box struct {
	X      float64
	Y      float64
	Width  float64
	Height float64
}

// ScreenshotOption configures ElementHandle.Screenshot.
type ScreenshotOption func(*screenshotOpts)

type screenshotOpts struct {
	mimeType string
}

// WithMimeType sets the image format for ElementHandle.Screenshot (default: image/png).
func WithMimeType(mime string) ScreenshotOption {
	return func(o *screenshotOpts) { o.mimeType = mime }
}

// wrapObject builds an ElementHandle from a Runtime.RemoteObject objectId.
func (p *Page) wrapObject(frameID, ctxID, objectID string) *ElementHandle {
	return &ElementHandle{page: p, objectID: objectID, ctxID: ctxID, frameID: frameID}
}

// QuerySelector returns the first matching element, or nil if no
// element matches (no error). Errors are reserved for transport
// failures.
func (p *Page) QuerySelector(ctx context.Context, selector string) (*ElementHandle, error) {
	ctxID, err := p.awaitMainContext(ctx, 5*time.Second)
	if err != nil {
		return nil, err
	}
	res, err := p.callFunction(ctx, ctxID,
		`function(sel) { return document.querySelector(sel); }`,
		[]juggler.CallFunctionArgument{argString(selector)}, false)
	if err != nil {
		return nil, err
	}
	if res.Result == nil || res.Result.ObjectID == "" {
		return nil, nil
	}
	return p.wrapObject(p.MainFrameID(), ctxID, res.Result.ObjectID), nil
}

// QuerySelectorAll returns every matching element as a slice of handles.
func (p *Page) QuerySelectorAll(ctx context.Context, selector string) ([]*ElementHandle, error) {
	ctxID, err := p.awaitMainContext(ctx, 5*time.Second)
	if err != nil {
		return nil, err
	}
	res, err := p.callFunction(ctx, ctxID,
		`function(sel) { return Array.from(document.querySelectorAll(sel)); }`,
		[]juggler.CallFunctionArgument{argString(selector)}, false)
	if err != nil {
		return nil, err
	}
	if res.Result == nil || res.Result.ObjectID == "" {
		return nil, nil
	}
	// Pull the array length, then index each entry.
	count, err := p.callFunction(ctx, ctxID,
		`function(a) { return a.length; }`,
		[]juggler.CallFunctionArgument{{ObjectID: res.Result.ObjectID}}, true)
	if err != nil {
		return nil, err
	}
	var n int
	_ = json.Unmarshal(count.Result.Value, &n)
	frameID := p.MainFrameID()
	out := make([]*ElementHandle, 0, n)
	for i := 0; i < n; i++ {
		idx, err := p.callFunction(ctx, ctxID,
			`function(a, i) { return a[i]; }`,
			[]juggler.CallFunctionArgument{{ObjectID: res.Result.ObjectID}, argNumber(float64(i))}, false)
		if err != nil {
			return out, err
		}
		if idx.Result != nil && idx.Result.ObjectID != "" {
			out = append(out, p.wrapObject(frameID, ctxID, idx.Result.ObjectID))
		}
	}
	return out, nil
}

// Click scrolls the element into view and dispatches a real mouse
// click at its center.
func (e *ElementHandle) Click(ctx context.Context) error {
	res, err := e.page.callFunction(ctx, e.ctxID,
		`function(el) {
			el.scrollIntoView({block:'center', inline:'center'});
			const r = el.getBoundingClientRect();
			return {x: r.left + r.width/2, y: r.top + r.height/2};
		}`,
		[]juggler.CallFunctionArgument{{ObjectID: e.objectID}}, true)
	if err != nil {
		return err
	}
	if res.Result == nil || len(res.Result.Value) == 0 {
		return errors.New("camoufox: ElementHandle.Click: element disposed?")
	}
	var rect struct{ X, Y float64 }
	if err := json.Unmarshal(res.Result.Value, &rect); err != nil {
		return fmt.Errorf("camoufox: ElementHandle.Click decode: %w", err)
	}
	return e.page.MouseClick(ctx, rect.X, rect.Y)
}

// Focus calls element.focus() in the browser.
func (e *ElementHandle) Focus(ctx context.Context) error {
	_, err := e.page.callFunction(ctx, e.ctxID,
		`function(el) { el.focus(); }`,
		[]juggler.CallFunctionArgument{{ObjectID: e.objectID}}, true)
	return err
}

// Type focuses the element then inserts text via Page.insertText.
func (e *ElementHandle) Type(ctx context.Context, text string) error {
	if err := e.Focus(ctx); err != nil {
		return err
	}
	return e.page.session.Call(ctx, "Page.insertText", map[string]any{"text": text}, nil)
}

// TextContent returns element.textContent.
func (e *ElementHandle) TextContent(ctx context.Context) (string, error) {
	res, err := e.page.callFunction(ctx, e.ctxID,
		`function(el) { return el.textContent; }`,
		[]juggler.CallFunctionArgument{{ObjectID: e.objectID}}, true)
	if err != nil {
		return "", err
	}
	if res.Result == nil || len(res.Result.Value) == 0 {
		return "", nil
	}
	var s string
	if err := json.Unmarshal(res.Result.Value, &s); err != nil {
		return "", err
	}
	return s, nil
}

// InnerHTML returns element.innerHTML.
func (e *ElementHandle) InnerHTML(ctx context.Context) (string, error) {
	res, err := e.page.callFunction(ctx, e.ctxID,
		`function(el) { return el.innerHTML; }`,
		[]juggler.CallFunctionArgument{{ObjectID: e.objectID}}, true)
	if err != nil {
		return "", err
	}
	if res.Result == nil || len(res.Result.Value) == 0 {
		return "", nil
	}
	var s string
	_ = json.Unmarshal(res.Result.Value, &s)
	return s, nil
}

// GetAttribute returns the attribute value, or empty string if absent.
func (e *ElementHandle) GetAttribute(ctx context.Context, name string) (string, error) {
	res, err := e.page.callFunction(ctx, e.ctxID,
		`function(el, n) { return el.getAttribute(n); }`,
		[]juggler.CallFunctionArgument{{ObjectID: e.objectID}, argString(name)}, true)
	if err != nil {
		return "", err
	}
	if res.Result == nil || len(res.Result.Value) == 0 {
		return "", nil
	}
	var s *string
	_ = json.Unmarshal(res.Result.Value, &s)
	if s == nil {
		return "", nil
	}
	return *s, nil
}

// Dispose releases the browser-side reference.
func (e *ElementHandle) Dispose(ctx context.Context) error {
	if e.objectID == "" {
		return nil
	}
	err := e.page.session.Call(ctx, "Runtime.disposeObject",
		map[string]any{"executionContextId": e.ctxID, "objectId": e.objectID}, nil)
	e.objectID = ""
	return err
}

// BoundingBox returns the element's bounding rectangle in viewport coordinates.
// It calls Page.getContentQuads and folds all quad points into min/max extents.
func (e *ElementHandle) BoundingBox(ctx context.Context) (*Box, error) {
	frameID := e.frameID
	if frameID == "" {
		frameID = e.page.MainFrameID()
	}
	params := juggler.PageGetContentQuadsParams{
		FrameID:  frameID,
		ObjectID: e.objectID,
	}
	var res juggler.PageGetContentQuadsResult
	if err := e.page.session.Call(ctx, "Page.getContentQuads", params, &res); err != nil {
		return nil, fmt.Errorf("camoufox: getContentQuads: %w", err)
	}
	if len(res.Quads) == 0 {
		return nil, errors.New("camoufox: BoundingBox: no quads returned")
	}
	minX, minY := math.MaxFloat64, math.MaxFloat64
	maxX, maxY := -math.MaxFloat64, -math.MaxFloat64
	for _, q := range res.Quads {
		for _, pt := range [4]juggler.DOMPoint{q.P1, q.P2, q.P3, q.P4} {
			if pt.X < minX {
				minX = pt.X
			}
			if pt.X > maxX {
				maxX = pt.X
			}
			if pt.Y < minY {
				minY = pt.Y
			}
			if pt.Y > maxY {
				maxY = pt.Y
			}
		}
	}
	return &Box{X: minX, Y: minY, Width: maxX - minX, Height: maxY - minY}, nil
}

// ScrollIntoViewIfNeeded scrolls the element into the visible area if it is not already.
func (e *ElementHandle) ScrollIntoViewIfNeeded(ctx context.Context) error {
	frameID := e.frameID
	if frameID == "" {
		frameID = e.page.MainFrameID()
	}
	params := juggler.PageScrollIntoViewIfNeededParams{
		FrameID:  frameID,
		ObjectID: e.objectID,
	}
	return e.page.session.Call(ctx, "Page.scrollIntoViewIfNeeded", params, nil)
}

// Hover moves the mouse to the center of the element.
func (e *ElementHandle) Hover(ctx context.Context) error {
	box, err := e.BoundingBox(ctx)
	if err != nil {
		return fmt.Errorf("camoufox: Hover: %w", err)
	}
	cx := box.X + box.Width/2
	cy := box.Y + box.Height/2
	ev := juggler.PageDispatchMouseEventParams{
		Type: "mousemove", X: cx, Y: cy,
	}
	return e.page.session.Call(ctx, "Page.dispatchMouseEvent", ev, nil)
}

// Screenshot captures the element's bounding region as PNG bytes.
func (e *ElementHandle) Screenshot(ctx context.Context, opts ...ScreenshotOption) ([]byte, error) {
	o := screenshotOpts{mimeType: "image/png"}
	for _, fn := range opts {
		fn(&o)
	}
	box, err := e.BoundingBox(ctx)
	if err != nil {
		return nil, fmt.Errorf("camoufox: Screenshot: %w", err)
	}
	params := juggler.PageScreenshotParams{
		MimeType: o.mimeType,
		Clip: juggler.PageScreenshotClip{
			X:      box.X,
			Y:      box.Y,
			Width:  box.Width,
			Height: box.Height,
		},
	}
	var res juggler.PageScreenshotResult
	if err := e.page.session.Call(ctx, "Page.screenshot", params, &res); err != nil {
		return nil, fmt.Errorf("camoufox: element screenshot: %w", err)
	}
	return base64.StdEncoding.DecodeString(res.Data)
}

func (p *Page) callFunction(ctx context.Context, ctxID, fn string,
	args []juggler.CallFunctionArgument, returnByValue bool) (*juggler.EvaluateResult, error) {
	params := juggler.CallFunctionParams{
		ExecutionContextID:  ctxID,
		FunctionDeclaration: fn,
		ReturnByValue:       returnByValue,
		Args:                args,
	}
	var res juggler.EvaluateResult
	if err := p.session.Call(ctx, "Runtime.callFunction", params, &res); err != nil {
		return nil, err
	}
	if res.ExceptionDetails != nil {
		return nil, fmt.Errorf("camoufox: callFunction exception: %s", res.ExceptionDetails.Text)
	}
	return &res, nil
}

func argString(s string) juggler.CallFunctionArgument {
	b, _ := json.Marshal(s)
	return juggler.CallFunctionArgument{Value: b}
}

func argNumber(n float64) juggler.CallFunctionArgument {
	b, _ := json.Marshal(n)
	return juggler.CallFunctionArgument{Value: b}
}
