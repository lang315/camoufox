package camoufox

import (
	"context"
	"fmt"
	"reflect"
	"testing"
	"time"

	"github.com/lang315/camoufox/goapi/pkg/juggler"
)

// grantRequest runs GrantPermissions against a scripted connection and returns the permissions
// it sent to Juggler, or the error it returned instead of sending anything.
func grantRequest(t *testing.T, perms []string) ([]any, error) {
	t.Helper()
	in := make(chan []byte, 4)
	sent := make(chan map[string]any, 4)
	conn := juggler.NewConnection(juggler.NewPipe(&scriptedReader{in: in}, &capturingWriter{out: sent}, nil))
	t.Cleanup(func() {
		close(in)
		conn.Close()
	})
	bc := &BrowserContext{b: &Browser{conn: conn, root: conn.RootSession()}, id: "c1"}
	done := make(chan error, 1)
	go func() { done <- bc.GrantPermissions(context.Background(), "http://127.0.0.1:1", perms) }()
	select {
	case m := <-sent:
		if m["method"] != "Browser.grantPermissions" {
			t.Fatalf("sent %v, want Browser.grantPermissions", m["method"])
		}
		in <- []byte(fmt.Sprintf(`{"id":%d,"result":{}}`+"\x00", int64(m["id"].(float64))))
		if err := <-done; err != nil {
			t.Fatalf("GrantPermissions: %v", err)
		}
		return m["params"].(map[string]any)["permissions"].([]any), nil
	case err := <-done:
		return nil, err
	case <-time.After(2 * time.Second):
		t.Fatal("GrantPermissions neither sent a request nor returned")
		return nil, nil
	}
}

// Juggler records every name it does not know as a denial and answers without an error
// (TargetRegistry.js grantPermissionsToOrigin), so a Playwright name sent through unchanged
// leaves the permission denied (#397).
func TestGrantPermissionsSendsJugglersNamesForPlaywrightsNames(t *testing.T) {
	for _, tc := range []struct {
		in   []string
		want []any
	}{
		{[]string{"geolocation"}, []any{"geo"}},
		{[]string{"notifications"}, []any{"desktop-notification"}},
		{[]string{"local-network-access"}, []any{"local-network", "loopback-network"}},
		{[]string{"geolocation", "notifications"}, []any{"geo", "desktop-notification"}},
	} {
		got, err := grantRequest(t, tc.in)
		if err != nil {
			t.Fatalf("%v: %v", tc.in, err)
		}
		if !reflect.DeepEqual(got, tc.want) {
			t.Errorf("GrantPermissions(%v) sent %v, want %v", tc.in, got, tc.want)
		}
	}
}

func TestGrantPermissionsRefusesANameJugglerCannotHonour(t *testing.T) {
	for _, name := range []string{"geo", "camera", "push"} {
		if got, err := grantRequest(t, []string{name}); err == nil {
			t.Errorf("GrantPermissions(%q) sent %v and returned no error; Juggler would deny it silently", name, got)
		}
	}
}
