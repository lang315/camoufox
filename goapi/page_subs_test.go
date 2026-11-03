package camoufox

import (
	"sync/atomic"
	"testing"
	"time"
)

// attachedPage attaches one page and waits until OnPage has reported it.
func attachedPage(t *testing.T, h *attachHarness) *Page {
	t.Helper()
	h.attach("T1", "s1")
	h.waitReported(t, 1)
	return h.reported()[0]
}

func (h *attachHarness) detach() {
	h.send(`{"method":"Browser.detachedFromTarget","params":{"sessionId":"s1","targetId":"T1"}}`)
}

// A handler that registers per-page handlers while the browser detaches the
// page races finish(): under -race the unlocked append and range are reported,
// and a handler registered after finish is never deregistered.
func TestOnPageHandlerRegisteringHandlersRacesDetach(t *testing.T) {
	h := newAttachHarness(t)
	gate := make(chan struct{})
	done := make(chan *Page, 1)
	var calls atomic.Int64
	h.bc.OnPage(func(p *Page) {
		<-gate // the page is published; the browser detaches it while this handler runs
		for i := 0; i < 500; i++ {
			p.OnDialog(func(*Dialog) { calls.Add(1) })
		}
		done <- p
	})
	h.attach("T1", "s1")
	time.Sleep(100 * time.Millisecond) // let publish reach the blocked handler
	h.detach()
	close(gate)
	p := <-done
	select {
	case <-p.closed:
	case <-time.After(2 * time.Second):
		t.Fatal("the detach never finished the page")
	}

	h.send(`{"method":"Page.dialogOpened","sessionId":"s1","params":{"dialogId":"d1","type":"alert","message":"m"}}`)
	time.Sleep(300 * time.Millisecond)
	if n := calls.Load(); n != 0 {
		t.Fatalf("%d dialog handlers registered during the detach still run after the page closed", n)
	}
}

// The public per-page handlers belong to the page: once it closes, an event
// for its session reaches none of them. The delivery before the close is the
// control, so a silent handler cannot pass for a deregistered one.
func TestPageClosingDeregistersItsPublicHandlers(t *testing.T) {
	h := newAttachHarness(t)
	p := attachedPage(t, h)

	var dialog, console, pageErr, crash, request, response atomic.Int64
	p.OnDialog(func(*Dialog) { dialog.Add(1) })
	p.OnConsole(func(*ConsoleMessage) { console.Add(1) })
	p.OnPageError(func(*PageError) { pageErr.Add(1) })
	p.OnCrash(func() { crash.Add(1) })
	p.OnRequest(func(*Request) { request.Add(1) })
	p.OnResponse(func(*Response) { response.Add(1) })

	events := []string{
		`{"method":"Page.dialogOpened","sessionId":"s1","params":{"dialogId":"d1","type":"alert","message":"m"}}`,
		`{"method":"Runtime.console","sessionId":"s1","params":{"type":"log","args":[]}}`,
		`{"method":"Page.uncaughtError","sessionId":"s1","params":{"message":"boom"}}`,
		`{"method":"Page.crashed","sessionId":"s1","params":{}}`,
		`{"method":"Network.requestWillBeSent","sessionId":"s1","params":{"requestId":"r1","url":"http://x/"}}`,
		`{"method":"Network.responseReceived","sessionId":"s1","params":{"requestId":"r1","status":200}}`,
	}
	counts := func() []int64 {
		return []int64{dialog.Load(), console.Load(), pageErr.Load(), crash.Load(), request.Load(), response.Load()}
	}
	names := []string{"OnDialog", "OnConsole", "OnPageError", "OnCrash", "OnRequest", "OnResponse"}
	for _, e := range events {
		h.send(e)
	}
	waitFor(t, func() bool {
		for _, n := range counts() {
			if n != 1 {
				return false
			}
		}
		return true
	}, "each handler called once while the page is open (control)")

	h.detach()
	select {
	case <-p.closed:
	case <-time.After(2 * time.Second):
		t.Fatal("the detach never finished the page")
	}
	for _, e := range events {
		h.send(e)
	}
	time.Sleep(300 * time.Millisecond)
	for i, n := range counts() {
		if n != 1 {
			t.Errorf("%s ran %d times; it ran again after the page closed", names[i], n)
		}
	}

	// Off after the page closed is harmless.
	sub := p.OnDialog(func(*Dialog) {})
	p.Off(sub)
	p.Off(sub)
}

func waitFor(t *testing.T, ok func() bool, what string) {
	t.Helper()
	for end := time.Now().Add(2 * time.Second); time.Now().Before(end); time.Sleep(10 * time.Millisecond) {
		if ok() {
			return
		}
	}
	t.Fatalf("timed out waiting: %s", what)
}
