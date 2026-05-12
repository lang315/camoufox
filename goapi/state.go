package camoufox

import (
	"context"
	"encoding/json"
	"fmt"
	"time"
)

// PageState is a lightweight snapshot of observable page properties.
type PageState struct {
	URL            string    `json:"url"`
	Title          string    `json:"title"`
	ReadyState     string    `json:"readyState"`
	FrameCount     int       `json:"frameCount"`
	CookieCount    int       `json:"cookieCount"`
	ViewportWidth  int       `json:"viewportWidth"`
	ViewportHeight int       `json:"viewportHeight"`
	ScrollX        float64   `json:"scrollX"`
	ScrollY        float64   `json:"scrollY"`
	Timestamp      time.Time `json:"timestamp"`
}

// StateSnapshot captures a comprehensive snapshot of observable page state.
// DOM-side fields are gathered in a single evaluate; cookie count and frame
// count come from existing Go-side methods.
func (p *Page) StateSnapshot(ctx context.Context) (*PageState, error) {
	script := `(function() {
		return {
			url: location.href || '',
			title: document.title || '',
			readyState: document.readyState || '',
			viewportWidth: window.innerWidth || 0,
			viewportHeight: window.innerHeight || 0,
			scrollX: window.scrollX || 0,
			scrollY: window.scrollY || 0
		};
	})()`

	raw, err := p.Evaluate(ctx, script)
	if err != nil {
		return nil, fmt.Errorf("camoufox: StateSnapshot: %w", err)
	}

	b, err := json.Marshal(raw)
	if err != nil {
		return nil, err
	}
	var st PageState
	if err := json.Unmarshal(b, &st); err != nil {
		return nil, fmt.Errorf("camoufox: StateSnapshot decode: %w", err)
	}

	// Go-side fields.
	st.FrameCount = len(p.Frames())
	st.Timestamp = time.Now()

	// Cookie count via BrowserContext.
	cookies, err := p.bc.Cookies(ctx)
	if err == nil {
		st.CookieCount = len(cookies)
	}

	return &st, nil
}
