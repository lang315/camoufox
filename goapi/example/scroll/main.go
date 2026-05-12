// Example: demonstrate ScrollToBottom on an infinite-scroll-like page.
//
// Run: CAMOUFOX_BIN=/path/to/camoufox go run ./example/scroll
package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"net/http/httptest"
	"os"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
)

func main() {
	exe := os.Getenv("CAMOUFOX_BIN")
	if exe == "" {
		log.Fatal("set CAMOUFOX_BIN to your camoufox firefox binary")
	}

	// Serve a tall page that simulates new content appended on scroll.
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		_, _ = fmt.Fprint(w, `<html><body style="margin:0">
<div style="height:8000px;background:linear-gradient(blue,red)">
  <p style="padding:20px">Scroll to the bottom of this tall page.</p>
</div>
</body></html>`)
	}))
	defer srv.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	b, err := camoufox.Launch(ctx,
		camoufox.WithExecutablePath(exe),
		camoufox.WithHeadless(true),
	)
	if err != nil {
		log.Fatalf("launch: %v", err)
	}
	defer b.Close()

	bc, err := b.NewContext(ctx)
	if err != nil {
		log.Fatalf("context: %v", err)
	}
	p, err := bc.NewPage(ctx)
	if err != nil {
		log.Fatalf("page: %v", err)
	}

	if err := p.Goto(ctx, srv.URL, camoufox.GotoOptions{WaitUntil: camoufox.WaitUntilLoad}); err != nil {
		log.Fatalf("goto: %v", err)
	}

	fmt.Println("Scrolling to bottom...")
	if err := p.ScrollToBottom(ctx, camoufox.ScrollToBottomOptions{
		MaxSteps:  30,
		IdleMs:    150 * time.Millisecond,
		StepDelta: 600,
	}); err != nil {
		log.Fatalf("ScrollToBottom: %v", err)
	}

	raw, _ := p.Evaluate(ctx, `window.scrollY`)
	fmt.Printf("Final scrollY: %v\n", raw)
}
