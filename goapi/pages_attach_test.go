package camoufox

import (
	"context"
	"fmt"
	"sync"
	"testing"
	"time"

	"github.com/lang315/camoufox/goapi/pkg/juggler"
)

// attachHarness drives a Browser over a scripted connection, so the order in
// which attach events and responses arrive is the test's, not the browser's.
type attachHarness struct {
	b    *Browser
	bc   *BrowserContext
	in   chan []byte
	sent chan map[string]any

	mu   sync.Mutex
	seen []*Page
}

func newAttachHarness(t *testing.T) *attachHarness {
	t.Helper()
	in := make(chan []byte, 64)
	sent := make(chan map[string]any, 16)
	conn := juggler.NewConnection(juggler.NewPipe(&scriptedReader{in: in}, &capturingWriter{out: sent}, nil))
	b := &Browser{
		conn:         conn,
		root:         conn.RootSession(),
		contexts:     map[string]*BrowserContext{},
		pages:        map[string]*Page{},
		pageAwaiters: map[string]chan *Page{},
	}
	b.subscribeAttach()
	bc := &BrowserContext{b: b, id: "c1"}
	b.contexts["c1"] = bc
	h := &attachHarness{b: b, bc: bc, in: in, sent: sent}
	bc.OnPage(func(p *Page) {
		h.mu.Lock()
		h.seen = append(h.seen, p)
		h.mu.Unlock()
	})
	t.Cleanup(func() {
		close(in)
		conn.Close()
	})
	return h
}

func (h *attachHarness) send(payload string) { h.in <- []byte(payload + "\x00") }

// attach announces a page target with no opener, as a tab the browser opens
// without one does, and gives its session a main execution context.
func (h *attachHarness) attach(target, session string) {
	h.send(fmt.Sprintf(`{"method":"Browser.attachedToTarget","params":{"sessionId":%q,"targetInfo":{"type":"page","targetId":%q,"browserContextId":"c1"}}}`, session, target))
	h.send(fmt.Sprintf(`{"method":"Runtime.executionContextCreated","sessionId":%q,"params":{"executionContextId":"x-%s","auxData":{"frameId":"f-%s","name":""}}}`, session, session, session))
}

func (h *attachHarness) awaitRequest(t *testing.T, method string) float64 {
	t.Helper()
	select {
	case m := <-h.sent:
		if m["method"] != method {
			t.Fatalf("request was %v, want %s", m["method"], method)
		}
		return m["id"].(float64)
	case <-time.After(2 * time.Second):
		t.Fatalf("client never sent %s", method)
		return 0
	}
}

func (h *attachHarness) reported() []*Page {
	h.mu.Lock()
	defer h.mu.Unlock()
	return append([]*Page(nil), h.seen...)
}

func (h *attachHarness) waitReported(t *testing.T, n int) {
	t.Helper()
	for end := time.Now().Add(2 * time.Second); time.Now().Before(end); time.Sleep(10 * time.Millisecond) {
		if len(h.reported()) >= n {
			return
		}
	}
	t.Fatalf("OnPage was called %d times, want %d", len(h.reported()), n)
}

// A page that attaches while a NewPage is waiting for a different target is
// nobody's to await. It is a page of the context all the same, and must reach
// Pages and OnPage whichever order NewPage's own attach and reply arrive in.
func TestUnawaitedPageDuringNewPageIsKept(t *testing.T) {
	for _, early := range []bool{false, true} {
		t.Run(fmt.Sprintf("own attach before reply=%v", early), func(t *testing.T) {
			h := newAttachHarness(t)
			ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			type result struct {
				p   *Page
				err error
			}
			done := make(chan result, 1)
			go func() {
				p, err := h.bc.NewPage(ctx)
				done <- result{p, err}
			}()
			id := h.awaitRequest(t, "Browser.newPage")

			h.attach("T9", "s9") // no opener, not NewPage's target
			h.waitReported(t, 1)

			if early {
				h.attach("T1", "s1")
			}
			h.send(fmt.Sprintf(`{"id":%d,"result":{"targetId":"T1"}}`, int64(id)))
			if !early {
				h.attach("T1", "s1")
			}
			r := <-done
			if r.err != nil {
				t.Fatalf("NewPage: %v", r.err)
			}
			if r.p.target.TargetID != "T1" {
				t.Errorf("NewPage returned target %s, want T1", r.p.target.TargetID)
			}
			h.waitReported(t, 2)
			pages := h.bc.Pages()
			if len(pages) != 2 {
				t.Fatalf("Pages() holds %d pages, want 2", len(pages))
			}
			got := map[string]int{}
			for _, p := range h.reported() {
				got[p.target.TargetID]++
			}
			if got["T1"] != 1 || got["T9"] != 1 || len(got) != 2 {
				t.Errorf("OnPage reported %v, want T1 and T9 once each", got)
			}
		})
	}
}
