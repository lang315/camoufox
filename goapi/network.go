package camoufox

import (
	"context"
	"encoding/json"

	"github.com/lang315/camoufox/goapi/pkg/juggler"
)

// Request is the Go-facing view of a single in-flight network
// request. It is a snapshot — mutations to the underlying browser
// state are not reflected.
type Request struct {
	page          *Page
	RequestID     string
	FrameID       string
	URL           string
	Method        string
	PostData      string
	Headers       map[string]string
	IsIntercepted bool
	NavigationID  string
	Cause         string
}

// Response pairs a Request with the HTTP status / headers returned.
type Response struct {
	RequestID  string
	Status     int
	StatusText string
	Headers    map[string]string
	FromCache  bool
	RemoteIP   string
	RemotePort int
}

// RequestHandler is invoked for every Network.requestWillBeSent.
type RequestHandler func(*Request)

// ResponseHandler is invoked for every Network.responseReceived.
type ResponseHandler func(*Response)

// OnRequest subscribes to outbound requests for this page session.
// Returns a Subscription that can be passed to Off to deregister.
func (p *Page) OnRequest(h RequestHandler) juggler.Subscription {
	return p.bc.b.conn.On("Network.requestWillBeSent", func(ev juggler.Event) {
		if ev.SessionID != p.session.ID() {
			return
		}
		var ne juggler.NetworkRequestWillBeSentEvent
		if err := json.Unmarshal(ev.Params, &ne); err != nil {
			return
		}
		h(&Request{
			page:          p,
			RequestID:     ne.RequestID,
			FrameID:       ne.FrameID,
			URL:           ne.URL,
			Method:        ne.Method,
			PostData:      ne.PostData,
			Headers:       headerSliceToMap(ne.Headers),
			IsIntercepted: ne.IsIntercepted,
			NavigationID:  ne.NavigationID,
			Cause:         ne.Cause,
		})
	})
}

// OnResponse subscribes to inbound responses for this page session.
func (p *Page) OnResponse(h ResponseHandler) juggler.Subscription {
	return p.bc.b.conn.On("Network.responseReceived", func(ev juggler.Event) {
		if ev.SessionID != p.session.ID() {
			return
		}
		var ne juggler.NetworkResponseReceivedEvent
		if err := json.Unmarshal(ev.Params, &ne); err != nil {
			return
		}
		h(&Response{
			RequestID:  ne.RequestID,
			Status:     ne.Status,
			StatusText: ne.StatusText,
			Headers:    headerSliceToMap(ne.Headers),
			FromCache:  ne.FromCache,
			RemoteIP:   ne.RemoteIPAddress,
			RemotePort: ne.RemotePort,
		})
	})
}

// Off deregisters a Subscription previously returned by OnRequest /
// OnResponse.
func (p *Page) Off(sub juggler.Subscription) {
	p.bc.b.conn.Off(sub)
}

// SetExtraHTTPHeaders applies headers to every subsequent request
// from this page's network session.
func (p *Page) SetExtraHTTPHeaders(ctx context.Context, headers map[string]string) error {
	var hs []juggler.HTTPHeader
	for k, v := range headers {
		hs = append(hs, juggler.HTTPHeader{Name: k, Value: v})
	}
	return p.session.Call(ctx, "Network.setExtraHTTPHeaders",
		map[string]any{"headers": hs}, nil)
}

// GetResponseBody fetches the body bytes captured for a request.
// Returns the raw body even when base64Encoded was set by the
// browser; callers do their own base64 decode if needed.
func (p *Page) GetResponseBody(ctx context.Context, requestID string) ([]byte, error) {
	var res struct {
		Base64Body string `json:"base64body"`
		Evicted    bool   `json:"evicted"`
	}
	if err := p.session.Call(ctx, "Network.getResponseBody",
		map[string]any{"requestId": requestID}, &res); err != nil {
		return nil, err
	}
	return []byte(res.Base64Body), nil
}

func headerSliceToMap(hs []juggler.HTTPHeader) map[string]string {
	out := make(map[string]string, len(hs))
	for _, h := range hs {
		out[h.Name] = h.Value
	}
	return out
}
