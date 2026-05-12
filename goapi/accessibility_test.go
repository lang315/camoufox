package camoufox_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
	"github.com/lang315/camoufox/goapi/pkg/juggler"
)

func TestAccessibilitySnapshot(t *testing.T) {
	if os.Getenv("CAMOUFOX_BIN") == "" {
		t.Skip("set CAMOUFOX_BIN to run")
	}

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte(`<html><body>
<button aria-label="Submit form">Submit</button>
</body></html>`))
	}))
	defer srv.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	b, err := camoufox.Launch(ctx,
		camoufox.WithExecutablePath(os.Getenv("CAMOUFOX_BIN")),
		camoufox.WithHeadless(true))
	if err != nil {
		t.Fatalf("launch: %v", err)
	}
	defer b.Close()

	bc, err := b.NewContext(ctx)
	if err != nil {
		t.Fatalf("context: %v", err)
	}
	p, err := bc.NewPage(ctx)
	if err != nil {
		t.Fatalf("page: %v", err)
	}
	defer p.Close(ctx)

	if err := p.Goto(ctx, srv.URL, camoufox.GotoOptions{WaitUntil: camoufox.WaitUntilLoad, Timeout: 10 * time.Second}); err != nil {
		t.Fatalf("goto: %v", err)
	}
	// Firefox a11y service is lazy-init; brief wait ensures tree is populated.
	time.Sleep(300 * time.Millisecond)

	tree, err := p.Accessibility().Snapshot(ctx, nil)
	if err != nil {
		t.Fatalf("Snapshot: %v", err)
	}
	if tree == nil {
		t.Fatal("Snapshot returned nil tree")
	}

	// Firefox reports button role as "pushbutton".
	if !findAXNode(tree, "pushbutton", "Submit form") {
		t.Errorf("expected pushbutton with name 'Submit form' in AX tree; got root=%q", tree.Role)
	}
}

func findAXNode(node *juggler.AXNode, role, name string) bool {
	if node == nil {
		return false
	}
	if node.Role == role && node.Name == name {
		return true
	}
	for _, child := range node.Children {
		if findAXNode(child, role, name) {
			return true
		}
	}
	return false
}
