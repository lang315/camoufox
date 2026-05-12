// Package juggler implements the Camoufox/Playwright Juggler remote
// debugging protocol over the browser's stdio pipe transport.
//
// Wire format (one direction): a stream of UTF-8 JSON messages each
// terminated by a single NUL byte (0x00). Reference:
// additions/juggler/pipe/nsRemoteDebuggingPipe.cpp (SendMessage and ReaderLoop).
package juggler

import (
	"bufio"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"sync"
)

// Pipe is the framed JSON+NUL transport over a pair of io streams.
// On Unix the browser opens FD 3 for reading and FD 4 for writing
// (from the browser's point of view) — so the client writes to FD 3
// and reads from FD 4.
type Pipe struct {
	r       *bufio.Reader
	w       io.Writer
	wMu     sync.Mutex
	closeFn func() error
}

// NewPipe wraps a reader and writer. The caller is responsible for
// closing the underlying files; closeFn is invoked from Close().
func NewPipe(r io.Reader, w io.Writer, closeFn func() error) *Pipe {
	return &Pipe{
		r:       bufio.NewReaderSize(r, 256*1024),
		w:       w,
		closeFn: closeFn,
	}
}

// Send writes a JSON message followed by a NUL terminator.
// Safe for concurrent use.
func (p *Pipe) Send(payload []byte) error {
	p.wMu.Lock()
	defer p.wMu.Unlock()
	if _, err := p.w.Write(payload); err != nil {
		return fmt.Errorf("juggler: write payload: %w", err)
	}
	if _, err := p.w.Write([]byte{0}); err != nil {
		return fmt.Errorf("juggler: write terminator: %w", err)
	}
	return nil
}

// Recv reads the next NUL-terminated JSON message and returns it
// without the trailing NUL. Returns io.EOF on clean pipe close.
func (p *Pipe) Recv() ([]byte, error) {
	msg, err := p.r.ReadBytes(0)
	if err != nil {
		if errors.Is(err, io.EOF) && len(msg) == 0 {
			return nil, io.EOF
		}
		if len(msg) > 0 && !errors.Is(err, io.EOF) {
			return nil, fmt.Errorf("juggler: read: %w", err)
		}
		return nil, err
	}
	// Strip trailing NUL.
	return msg[:len(msg)-1], nil
}

// SendJSON marshals v and frames it.
func (p *Pipe) SendJSON(v any) error {
	buf, err := json.Marshal(v)
	if err != nil {
		return fmt.Errorf("juggler: marshal: %w", err)
	}
	return p.Send(buf)
}

// Close releases the transport.
func (p *Pipe) Close() error {
	if p.closeFn == nil {
		return nil
	}
	return p.closeFn()
}
