package juggler

import (
	"bytes"
	"reflect"
	"sync"
	"testing"
	"time"
)

// TestSessionEventsSurviveTheAttachSubscribeGap reproduces the NewPage
// race: Browser.attachedToTarget announces a session, the browser
// immediately emits that session's Page.frameAttached and
// Runtime.executionContextCreated, and only afterwards does the client
// get around to registering handlers for it. Before the fix those two
// events had no matching handler at delivery time and were dropped,
// leaving mainFrameID empty and contextReadyCh open.
func TestSessionEventsSurviveTheAttachSubscribeGap(t *testing.T) {
	in := make(chan []byte, 16)
	rd := &pipeReadEnd{in: in}
	c := NewConnection(NewPipe(rd, &bytes.Buffer{}, nil))
	defer c.Close()
	defer close(in)

	var mu sync.Mutex
	attachSeen := 0
	var order []string
	record := func(name string) EventHandler {
		return func(ev Event) {
			if ev.SessionID != "s1" {
				return
			}
			mu.Lock()
			order = append(order, name)
			mu.Unlock()
		}
	}
	snapshot := func() []string {
		mu.Lock()
		defer mu.Unlock()
		return append([]string(nil), order...)
	}

	// Registered up front, mirroring Browser.subscribeAttach.
	c.On("Browser.attachedToTarget", func(ev Event) {
		mu.Lock()
		attachSeen++
		mu.Unlock()
	})

	in <- []byte(`{"method":"Browser.attachedToTarget","params":{"sessionId":"s1","targetInfo":{"targetId":"t1","type":"page"}}}` + "\x00")
	in <- []byte(`{"method":"Page.frameAttached","sessionId":"s1","params":{"frameId":"f1"}}` + "\x00")
	in <- []byte(`{"method":"Runtime.executionContextCreated","sessionId":"s1","params":{"executionContextId":"e1"}}` + "\x00")
	time.Sleep(50 * time.Millisecond)

	mu.Lock()
	seen := attachSeen
	mu.Unlock()
	if seen != 1 {
		t.Fatalf("attach handler fired %d times, want 1 (the hold must not eat the attach event)", seen)
	}

	// Page.subscribe() + registerFrameEvents() equivalent, run only
	// after the session's first events have already arrived.
	c.On("Page.frameAttached", record("frameAttached"))
	c.On("Runtime.executionContextCreated", record("executionContextCreated"))
	c.ReplaySession("s1")

	want := []string{"frameAttached", "executionContextCreated"}
	if got := snapshot(); !reflect.DeepEqual(got, want) {
		t.Fatalf("after ReplaySession got %v, want %v", got, want)
	}

	// Live delivery resumes once the session has been claimed.
	in <- []byte(`{"method":"Page.frameAttached","sessionId":"s1","params":{"frameId":"f2"}}` + "\x00")
	time.Sleep(50 * time.Millisecond)
	want = append(want, "frameAttached")
	if got := snapshot(); !reflect.DeepEqual(got, want) {
		t.Fatalf("after live event got %v, want %v", got, want)
	}

	// Replaying a claimed session again must not re-deliver anything.
	c.ReplaySession("s1")
	if got := snapshot(); !reflect.DeepEqual(got, want) {
		t.Fatalf("second ReplaySession re-delivered: got %v, want %v", got, want)
	}
}

// TestReplaySessionUnknownSessionIsSafe covers the paths where no hold
// exists: an unknown session id and the empty root session id.
func TestReplaySessionUnknownSessionIsSafe(t *testing.T) {
	in := make(chan []byte, 4)
	rd := &pipeReadEnd{in: in}
	c := NewConnection(NewPipe(rd, &bytes.Buffer{}, nil))
	defer c.Close()
	defer close(in)

	c.ReplaySession("")
	c.ReplaySession("never-attached")
}
