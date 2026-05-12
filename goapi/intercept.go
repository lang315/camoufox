package camoufox

import (
	"context"
	"encoding/base64"

	"github.com/lang315/camoufox/goapi/pkg/juggler"
)

// Route is the action a RouteHandler decides for an intercepted
// request: continue (optionally rewritten), fulfill with a synthetic
// response, or abort with a network error.
type Route struct {
	page    *Page
	request *Request
}

// URL returns the request URL.
func (r *Route) URL() string { return r.request.URL }

// Request returns the underlying Request.
func (r *Route) Request() *Request { return r.request }

// Continue resumes the request with optional overrides. Pass empty
// strings / nil to keep the originals.
func (r *Route) Continue(ctx context.Context, opts ...ContinueOptions) error {
	params := map[string]any{"requestId": r.request.RequestID}
	if len(opts) > 0 {
		o := opts[0]
		if o.URL != "" {
			params["url"] = o.URL
		}
		if o.Method != "" {
			params["method"] = o.Method
		}
		if len(o.Headers) > 0 {
			var hs []juggler.HTTPHeader
			for k, v := range o.Headers {
				hs = append(hs, juggler.HTTPHeader{Name: k, Value: v})
			}
			params["headers"] = hs
		}
		if o.PostData != "" {
			params["postData"] = o.PostData
		}
	}
	return r.page.session.Call(ctx, "Network.resumeInterceptedRequest", params, nil)
}

// Fulfill returns a synthetic response (HTTP status + headers + body)
// without sending the request upstream.
func (r *Route) Fulfill(ctx context.Context, status int, headers map[string]string, body []byte) error {
	var hs []juggler.HTTPHeader
	for k, v := range headers {
		hs = append(hs, juggler.HTTPHeader{Name: k, Value: v})
	}
	params := map[string]any{
		"requestId":  r.request.RequestID,
		"status":     status,
		"statusText": "",
		"headers":    hs,
	}
	if len(body) > 0 {
		params["base64body"] = base64.StdEncoding.EncodeToString(body)
	}
	return r.page.session.Call(ctx, "Network.fulfillInterceptedRequest", params, nil)
}

// Abort cancels the request with the given errorCode (e.g.
// "BLOCKEDBYCLIENT", "FAILED").
func (r *Route) Abort(ctx context.Context, errorCode string) error {
	if errorCode == "" {
		errorCode = "FAILED"
	}
	return r.page.session.Call(ctx, "Network.abortInterceptedRequest",
		map[string]any{"requestId": r.request.RequestID, "errorCode": errorCode}, nil)
}

// ContinueOptions overrides applied by Route.Continue.
type ContinueOptions struct {
	URL      string
	Method   string
	Headers  map[string]string
	PostData string
}

// RouteHandler receives every request once SetRequestInterception is
// enabled. The handler must always call one of Continue/Fulfill/Abort
// or the page will hang.
type RouteHandler func(*Route)

// EnableRequestInterception switches on Network.setRequestInterception
// for this page and routes every intercepted request through h. The
// returned Subscription lets the caller stop listening; the browser
// remains in interception mode until DisableRequestInterception is
// called.
func (p *Page) EnableRequestInterception(ctx context.Context, h RouteHandler) (juggler.Subscription, error) {
	if err := p.session.Call(ctx, "Network.setRequestInterception",
		map[string]any{"enabled": true}, nil); err != nil {
		return juggler.Subscription{}, err
	}
	sub := p.bc.b.conn.On("Network.requestWillBeSent", func(ev juggler.Event) {
		if ev.SessionID != p.session.ID() {
			return
		}
		req := &Request{}
		// Decode the same way OnRequest does, but we need
		// IsIntercepted to filter — non-intercepted requests should
		// not be handed to h.
		var ne juggler.NetworkRequestWillBeSentEvent
		if err := jsonUnmarshal(ev.Params, &ne); err != nil {
			return
		}
		if !ne.IsIntercepted {
			return
		}
		req.page = p
		req.RequestID = ne.RequestID
		req.FrameID = ne.FrameID
		req.URL = ne.URL
		req.Method = ne.Method
		req.PostData = ne.PostData
		req.Headers = headerSliceToMap(ne.Headers)
		req.IsIntercepted = true
		req.NavigationID = ne.NavigationID
		req.Cause = ne.Cause
		h(&Route{page: p, request: req})
	})
	return sub, nil
}

// DisableRequestInterception turns interception back off.
func (p *Page) DisableRequestInterception(ctx context.Context) error {
	return p.session.Call(ctx, "Network.setRequestInterception",
		map[string]any{"enabled": false}, nil)
}
