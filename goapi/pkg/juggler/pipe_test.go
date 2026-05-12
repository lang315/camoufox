package juggler

import (
	"bytes"
	"io"
	"testing"
)

// TestPipeFraming round-trips two messages through Pipe.Send and
// asserts the NUL framing matches additions/juggler/pipe/
// nsRemoteDebuggingPipe.cpp:SendMessage.
func TestPipeFraming(t *testing.T) {
	var sent bytes.Buffer
	p := NewPipe(nopReader{}, &sent, nil)
	if err := p.Send([]byte(`{"id":1,"method":"Browser.enable"}`)); err != nil {
		t.Fatal(err)
	}
	if err := p.Send([]byte(`{"id":2}`)); err != nil {
		t.Fatal(err)
	}
	got := sent.Bytes()
	want := append([]byte(`{"id":1,"method":"Browser.enable"}`), 0)
	want = append(want, []byte(`{"id":2}`)...)
	want = append(want, 0)
	if !bytes.Equal(got, want) {
		t.Fatalf("framing mismatch:\n got: %q\nwant: %q", got, want)
	}
}

func TestPipeRecvSplits(t *testing.T) {
	stream := []byte("{\"id\":1,\"result\":{}}\x00{\"method\":\"Browser.attachedToTarget\",\"params\":{}}\x00")
	p := NewPipe(bytes.NewReader(stream), io.Discard, nil)

	first, err := p.Recv()
	if err != nil {
		t.Fatal(err)
	}
	if string(first) != `{"id":1,"result":{}}` {
		t.Fatalf("first: %q", first)
	}
	second, err := p.Recv()
	if err != nil {
		t.Fatal(err)
	}
	if string(second) != `{"method":"Browser.attachedToTarget","params":{}}` {
		t.Fatalf("second: %q", second)
	}
	if _, err := p.Recv(); err != io.EOF {
		t.Fatalf("expected EOF, got %v", err)
	}
}

type nopReader struct{}

func (nopReader) Read(p []byte) (int, error) { return 0, io.EOF }
