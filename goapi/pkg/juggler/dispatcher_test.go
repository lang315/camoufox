package juggler

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"sync"
	"testing"
	"time"
)

// pipeReadEnd lets tests inject scripted messages into a Pipe.
type pipeReadEnd struct {
	mu  sync.Mutex
	buf bytes.Buffer
	in  chan []byte
}

func (r *pipeReadEnd) Read(p []byte) (int, error) {
	for r.buf.Len() == 0 {
		select {
		case b, ok := <-r.in:
			if !ok {
				return 0, io.EOF
			}
			r.mu.Lock()
			r.buf.Write(b)
			r.mu.Unlock()
		case <-time.After(2 * time.Second):
			return 0, io.EOF
		}
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.buf.Read(p)
}

func TestSubscriptionOnOff(t *testing.T) {
	in := make(chan []byte, 16)
	rd := &pipeReadEnd{in: in}
	pipe := NewPipe(rd, &bytes.Buffer{}, nil)
	c := NewConnection(pipe)
	defer c.Close()

	var calls int32
	var mu sync.Mutex
	sub := c.On("Test.event", func(ev Event) {
		mu.Lock()
		calls++
		mu.Unlock()
	})

	// Inject one event.
	payload := []byte(`{"method":"Test.event","params":{}}` + "\x00")
	in <- payload
	time.Sleep(50 * time.Millisecond)

	mu.Lock()
	if calls != 1 {
		t.Fatalf("expected 1 call, got %d", calls)
	}
	mu.Unlock()

	// Deregister.
	c.Off(sub)
	in <- payload
	time.Sleep(50 * time.Millisecond)
	mu.Lock()
	if calls != 1 {
		t.Fatalf("handler fired after Off: %d", calls)
	}
	mu.Unlock()
	close(in)
}

func TestCallSendsRequest(t *testing.T) {
	in := make(chan []byte, 4)
	rd := &pipeReadEnd{in: in}
	var written bytes.Buffer
	pipe := NewPipe(rd, &written, nil)
	c := NewConnection(pipe)
	defer c.Close()

	// Schedule a response for id=1 from the "server" side.
	go func() {
		time.Sleep(20 * time.Millisecond)
		in <- []byte(`{"id":1,"result":{"ok":true}}` + "\x00")
	}()

	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	raw, err := c.RootSession().Conn().Call(ctx, "", "Browser.enable", map[string]any{"attachToDefaultContext": true})
	if err != nil {
		t.Fatal(err)
	}
	var got map[string]bool
	if err := json.Unmarshal(raw, &got); err != nil {
		t.Fatal(err)
	}
	if !got["ok"] {
		t.Fatalf("bad result: %v", got)
	}

	// Verify the request bytes contain the expected envelope.
	if !bytes.Contains(written.Bytes(), []byte(`"method":"Browser.enable"`)) {
		t.Fatalf("missing method in payload: %q", written.String())
	}
	if !bytes.HasSuffix(written.Bytes(), []byte{0}) {
		t.Fatalf("payload not NUL-terminated: %q", written.String())
	}
}
