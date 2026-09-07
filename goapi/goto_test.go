package camoufox

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/lang315/camoufox/goapi/pkg/juggler"
)

// scriptedReader feeds the connection's read loop from a channel and
// blocks (rather than reporting EOF) while the channel is open, so a
// test can pause between injections without killing the connection.
type scriptedReader struct {
	buf bytes.Buffer
	in  chan []byte
}

func (r *scriptedReader) Read(p []byte) (int, error) {
	for r.buf.Len() == 0 {
		b, ok := <-r.in
		if !ok {
			return 0, io.EOF
		}
		r.buf.Write(b)
	}
	return r.buf.Read(p)
}

// capturingWriter reassembles the NUL-framed requests the client sends
// (Pipe.Send writes the payload and the terminator separately) so a
// test can learn the id of the Page.navigate call it must answer.
type capturingWriter struct {
	mu  sync.Mutex
	buf []byte
	out chan map[string]any
}

func (w *capturingWriter) Write(p []byte) (int, error) {
	w.mu.Lock()
	defer w.mu.Unlock()
	w.buf = append(w.buf, p...)
	for {
		i := bytes.IndexByte(w.buf, 0)
		if i < 0 {
			break
		}
		msg := w.buf[:i]
		w.buf = w.buf[i+1:]
		var m map[string]any
		if json.Unmarshal(msg, &m) == nil {
			select {
			case w.out <- m:
			default:
			}
		}
	}
	return len(p), nil
}

type gotoHarness struct {
	in   chan []byte
	sent chan map[string]any
	page *Page
}

// newGotoHarness builds a Page wired to a scripted connection. No
// Browser.attachedToTarget is injected: that would open the per-session
// hold from the NewPage fix and swallow every event below, since
// nothing here calls ReplaySession.
func newGotoHarness(t *testing.T) *gotoHarness {
	t.Helper()
	in := make(chan []byte, 16)
	sent := make(chan map[string]any, 16)
	conn := juggler.NewConnection(juggler.NewPipe(&scriptedReader{in: in}, &capturingWriter{out: sent}, nil))
	b := &Browser{conn: conn, root: conn.RootSession(), pages: map[string]*Page{}}
	p := &Page{
		bc:             &BrowserContext{b: b},
		session:        conn.Session("s1"),
		mainFrameID:    "f1",
		contextReadyCh: make(chan struct{}),
		closed:         make(chan struct{}),
		frames:         make(map[string]*Frame),
	}
	t.Cleanup(func() {
		close(in)
		conn.Close()
	})
	return &gotoHarness{in: in, sent: sent, page: p}
}

func (h *gotoHarness) send(payload string) { h.in <- []byte(payload + "\x00") }

func (h *gotoHarness) reply(id float64, result string) {
	h.send(fmt.Sprintf(`{"id":%d,"sessionId":"s1","result":%s}`, int64(id), result))
}

// awaitNavigate blocks until the client issues Page.navigate and
// returns its request id.
func (h *gotoHarness) awaitNavigate(t *testing.T) float64 {
	t.Helper()
	select {
	case m := <-h.sent:
		if m["method"] != "Page.navigate" {
			t.Fatalf("first request was %v, want Page.navigate", m["method"])
		}
		id, ok := m["id"].(float64)
		if !ok {
			t.Fatalf("Page.navigate request carried no id: %v", m)
		}
		return id
	case <-time.After(2 * time.Second):
		t.Fatal("client never sent Page.navigate")
		return 0
	}
}

func (h *gotoHarness) start(ctx context.Context, opts GotoOptions) chan error {
	done := make(chan error, 1)
	go func() { done <- h.page.Goto(ctx, "https://example.test/", opts) }()
	return done
}

const (
	loadFired   = `{"method":"Page.eventFired","sessionId":"s1","params":{"frameId":"f1","name":"load"}}`
	committedN1 = `{"method":"Page.navigationCommitted","sessionId":"s1","params":{"frameId":"f1","navigationId":"n1","url":"https://example.test/","name":""}}`
)

// TestGotoIgnoresLoadBeforeItsNavigationCommits pins the beta.31
// symptom: the load of the document Goto is replacing (the initial
// about:blank) reaches the waiter before Page.navigate has even been
// answered. Matching it by frame id alone returns from Goto with the
// page still on the old document.
func TestGotoIgnoresLoadBeforeItsNavigationCommits(t *testing.T) {
	h := newGotoHarness(t)
	done := h.start(context.Background(), GotoOptions{Timeout: 5 * time.Second})

	id := h.awaitNavigate(t)
	h.send(loadFired) // about:blank finishing, not ours
	time.Sleep(50 * time.Millisecond)
	h.reply(id, `{"navigationId":"n1"}`)

	select {
	case err := <-done:
		t.Fatalf("Goto returned (err=%v) on the load of the document it was replacing; it must wait for navigation n1", err)
	case <-time.After(300 * time.Millisecond):
	}

	h.send(committedN1)
	h.send(loadFired)
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("Goto after n1 committed and loaded: %v", err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("Goto did not return after navigation n1 committed and fired load")
	}
}

// TestGotoReportsAbortedNavigation: the browser gave up on the exact
// navigation Goto started, so Goto must surface the reason instead of
// sitting out the full timeout.
func TestGotoReportsAbortedNavigation(t *testing.T) {
	h := newGotoHarness(t)
	done := h.start(context.Background(), GotoOptions{Timeout: 2 * time.Second})

	id := h.awaitNavigate(t)
	h.reply(id, `{"navigationId":"n1"}`)
	h.send(`{"method":"Page.navigationAborted","sessionId":"s1","params":{"frameId":"f1","navigationId":"n1","errorText":"NS_ERROR_UNKNOWN_HOST"}}`)

	select {
	case err := <-done:
		if err == nil || !strings.Contains(err.Error(), "NS_ERROR_UNKNOWN_HOST") {
			t.Fatalf("Goto err = %v, want an error naming NS_ERROR_UNKNOWN_HOST", err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("Goto did not return after its navigation was aborted")
	}
}

// TestGotoCommitWaitsForItsOwnNavigation: WaitUntilCommit was matched by
// frame id too, so another frame-f1 navigation's commit satisfied it.
func TestGotoCommitWaitsForItsOwnNavigation(t *testing.T) {
	h := newGotoHarness(t)
	done := h.start(context.Background(), GotoOptions{WaitUntil: WaitUntilCommit, Timeout: 5 * time.Second})

	id := h.awaitNavigate(t)
	h.reply(id, `{"navigationId":"n1"}`)
	h.send(`{"method":"Page.navigationCommitted","sessionId":"s1","params":{"frameId":"f1","navigationId":"n0","url":"about:blank","name":""}}`)

	select {
	case err := <-done:
		t.Fatalf("Goto(commit) returned (err=%v) on navigation n0's commit, not its own n1", err)
	case <-time.After(300 * time.Millisecond):
	}

	h.send(committedN1)
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("Goto(commit) after n1 committed: %v", err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("Goto(commit) did not return after navigation n1 committed")
	}
}

// TestGotoReturnsWhenNoNavigationStarted: Page.navigate reports a null
// navigationId for a same-document (hash) navigation. There is no
// commit and no load coming, so waiting would burn the whole timeout.
func TestGotoReturnsWhenNoNavigationStarted(t *testing.T) {
	h := newGotoHarness(t)
	done := h.start(context.Background(), GotoOptions{Timeout: 5 * time.Second})

	id := h.awaitNavigate(t)
	h.reply(id, `{"navigationId":null}`)

	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("Goto with a null navigationId: %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("Goto blocked on a navigation the browser never started")
	}
}
