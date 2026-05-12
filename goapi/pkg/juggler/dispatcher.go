package juggler

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"sync"
	"sync/atomic"
)

// rawEnvelope captures the union of request, response and event shapes
// produced by additions/juggler/protocol/Dispatcher.js.
//
// Request  (client → browser): {id, method, params, sessionId?}
// Response (browser → client): {id, sessionId, result | error}
// Event    (browser → client): {method, params, sessionId}
type rawEnvelope struct {
	ID        uint64           `json:"id,omitempty"`
	SessionID string           `json:"sessionId,omitempty"`
	Method    string           `json:"method,omitempty"`
	Params    json.RawMessage  `json:"params,omitempty"`
	Result    json.RawMessage  `json:"result,omitempty"`
	Error     *ProtocolError   `json:"error,omitempty"`
}

// ProtocolError mirrors the {message, data} payload from Dispatcher.js.
type ProtocolError struct {
	Message string `json:"message"`
	Data    string `json:"data,omitempty"`
}

func (e *ProtocolError) Error() string {
	if e.Data != "" {
		return fmt.Sprintf("juggler: %s (%s)", e.Message, e.Data)
	}
	return "juggler: " + e.Message
}

// Event is a server-pushed notification dispatched to subscribers.
type Event struct {
	SessionID string
	Method    string
	Params    json.RawMessage
}

// EventHandler receives push events. Handlers must not block; offload
// expensive work to their own goroutine.
type EventHandler func(Event)

// Subscription identifies a registered handler. Pass to Connection.Off
// to deregister.
type Subscription struct {
	method string
	id     uint64
}

// Connection is a request/response/event multiplexer over a Pipe.
// All exported methods are safe for concurrent use.
type Connection struct {
	pipe *Pipe

	nextID atomic.Uint64

	pendingMu sync.Mutex
	pending   map[uint64]chan *rawEnvelope

	subsMu    sync.RWMutex
	nextSubID atomic.Uint64
	subs      map[string]map[uint64]EventHandler // method → id→handler, "" key is wildcard

	closeOnce sync.Once
	closed    chan struct{}
	closeErr  error
}

// NewConnection starts a reader goroutine and returns a ready connection.
func NewConnection(p *Pipe) *Connection {
	c := &Connection{
		pipe:    p,
		pending: make(map[uint64]chan *rawEnvelope),
		subs:    make(map[string]map[uint64]EventHandler),
		closed:  make(chan struct{}),
	}
	go c.readLoop()
	return c
}

// Done returns a channel that is closed when the connection is torn down.
func (c *Connection) Done() <-chan struct{} { return c.closed }

// Err returns the terminal read error, if any.
func (c *Connection) Err() error { return c.closeErr }

// Call sends a request and blocks until a matching response arrives
// or the context is canceled. sessionID may be empty for root-session
// calls (e.g. Browser.* methods).
func (c *Connection) Call(ctx context.Context, sessionID, method string, params any) (json.RawMessage, error) {
	id := c.nextID.Add(1)

	var rawParams json.RawMessage
	if params != nil {
		buf, err := json.Marshal(params)
		if err != nil {
			return nil, fmt.Errorf("juggler: marshal params for %s: %w", method, err)
		}
		rawParams = buf
	}

	ch := make(chan *rawEnvelope, 1)
	c.pendingMu.Lock()
	c.pending[id] = ch
	c.pendingMu.Unlock()
	defer func() {
		c.pendingMu.Lock()
		delete(c.pending, id)
		c.pendingMu.Unlock()
	}()

	envelope := rawEnvelope{
		ID:        id,
		SessionID: sessionID,
		Method:    method,
		Params:    rawParams,
	}
	if err := c.pipe.SendJSON(envelope); err != nil {
		return nil, err
	}

	select {
	case env := <-ch:
		if env.Error != nil {
			return nil, env.Error
		}
		return env.Result, nil
	case <-ctx.Done():
		return nil, ctx.Err()
	case <-c.closed:
		if c.closeErr != nil {
			return nil, c.closeErr
		}
		return nil, errors.New("juggler: connection closed")
	}
}

// On registers an event handler for the given method (e.g.
// "Browser.attachedToTarget"). Pass "" to receive every event.
// The returned Subscription can be passed to Off to deregister.
func (c *Connection) On(method string, h EventHandler) Subscription {
	id := c.nextSubID.Add(1)
	c.subsMu.Lock()
	defer c.subsMu.Unlock()
	bucket := c.subs[method]
	if bucket == nil {
		bucket = make(map[uint64]EventHandler)
		c.subs[method] = bucket
	}
	bucket[id] = h
	return Subscription{method: method, id: id}
}

// Off deregisters a handler returned from On. No-op for the zero Subscription.
func (c *Connection) Off(sub Subscription) {
	if sub.id == 0 {
		return
	}
	c.subsMu.Lock()
	defer c.subsMu.Unlock()
	if bucket := c.subs[sub.method]; bucket != nil {
		delete(bucket, sub.id)
	}
}

// Close terminates the read loop and the underlying pipe.
func (c *Connection) Close() error {
	c.closeOnce.Do(func() {
		close(c.closed)
		if c.pipe != nil {
			_ = c.pipe.Close()
		}
	})
	return nil
}

func (c *Connection) readLoop() {
	defer func() {
		c.closeOnce.Do(func() { close(c.closed) })
	}()
	for {
		msg, err := c.pipe.Recv()
		if err != nil {
			if !errors.Is(err, io.EOF) {
				c.closeErr = err
			}
			c.failPending(err)
			return
		}
		var env rawEnvelope
		if err := json.Unmarshal(msg, &env); err != nil {
			c.closeErr = fmt.Errorf("juggler: decode envelope: %w (payload=%q)", err, msg)
			c.failPending(c.closeErr)
			return
		}
		if env.ID != 0 {
			c.deliverResponse(env)
			continue
		}
		c.deliverEvent(env)
	}
}

func (c *Connection) deliverResponse(env rawEnvelope) {
	c.pendingMu.Lock()
	ch := c.pending[env.ID]
	c.pendingMu.Unlock()
	if ch == nil {
		return
	}
	select {
	case ch <- &env:
	default:
	}
}

func (c *Connection) deliverEvent(env rawEnvelope) {
	ev := Event{SessionID: env.SessionID, Method: env.Method, Params: env.Params}
	c.subsMu.RLock()
	var handlers []EventHandler
	for _, h := range c.subs[env.Method] {
		handlers = append(handlers, h)
	}
	for _, h := range c.subs[""] {
		handlers = append(handlers, h)
	}
	c.subsMu.RUnlock()
	for _, h := range handlers {
		h(ev)
	}
}

func (c *Connection) failPending(err error) {
	c.pendingMu.Lock()
	defer c.pendingMu.Unlock()
	for id, ch := range c.pending {
		select {
		case ch <- &rawEnvelope{ID: id, Error: &ProtocolError{Message: fmtErr(err)}}:
		default:
		}
	}
}

func fmtErr(err error) string {
	if err == nil {
		return "connection closed"
	}
	return err.Error()
}
