package juggler

import (
	"context"
	"encoding/json"
)

// Session pins a sessionId to RPC calls. The root session has an empty
// sessionId and only handles the Browser domain. Per-target sessions
// (one per page/worker) are created by the browser and announced via
// Browser.attachedToTarget events; the client typically holds a
// Session for each.
type Session struct {
	conn *Connection
	id   string
}

// RootSession returns the empty-sessionId binding used for Browser.* calls.
func (c *Connection) RootSession() *Session {
	return &Session{conn: c, id: ""}
}

// Session binds an existing sessionId (received from
// Browser.attachedToTarget).
func (c *Connection) Session(sessionID string) *Session {
	return &Session{conn: c, id: sessionID}
}

// ID returns the sessionId; empty for the root session.
func (s *Session) ID() string { return s.id }

// Conn exposes the underlying connection (event subscription, close).
func (s *Session) Conn() *Connection { return s.conn }

// Call issues a method against this session and decodes the result
// into out (if non-nil). Pass params=nil for parameterless methods.
func (s *Session) Call(ctx context.Context, method string, params any, out any) error {
	raw, err := s.conn.Call(ctx, s.id, method, params)
	if err != nil {
		return err
	}
	if out == nil || len(raw) == 0 {
		return nil
	}
	return json.Unmarshal(raw, out)
}
