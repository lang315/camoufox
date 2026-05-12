// Example: QueryResilient with cascading selector fallbacks.
// Tries a non-existent CSS ID first, then falls back to text-content match.
// Run: CAMOUFOX_BIN=/path/to/camoufox go run ./example/resilient
package main

import (
	"context"
	"fmt"
	"log"
	"net/url"
	"os"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
)

const htmlPage = `<!doctype html><html><body>
<button id="submit-btn">Submit</button>
<span data-testid="status">ready</span>
</body></html>`

func main() {
	exe := os.Getenv("CAMOUFOX_BIN")
	if exe == "" {
		log.Fatal("set CAMOUFOX_BIN")
	}
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

	bc, _ := b.NewContext(ctx)
	p, err := bc.NewPage(ctx)
	if err != nil {
		log.Fatalf("page: %v", err)
	}

	u := "data:text/html;charset=utf-8," + url.PathEscape(htmlPage)
	if err := p.Goto(ctx, u, camoufox.GotoOptions{WaitUntil: camoufox.WaitUntilDOMContentLoaded}); err != nil {
		log.Fatalf("goto: %v", err)
	}

	// Primary selector (#missing) does not exist; fallback by text finds it.
	el, err := p.QueryResilient(ctx, []camoufox.Selector{
		{Kind: camoufox.KindCSS, Value: "#missing"},
		{Kind: camoufox.KindText, Value: "Submit"},
	})
	if err != nil {
		log.Fatalf("QueryResilient: %v", err)
	}
	text, _ := el.TextContent(ctx)
	fmt.Printf("found via KindText: %q\n", text)

	// TestID selector for the status span.
	status, err := p.QueryResilient(ctx, []camoufox.Selector{
		{Kind: camoufox.KindTestID, Value: "status"},
	})
	if err != nil {
		log.Fatalf("QueryResilient testid: %v", err)
	}
	statusText, _ := status.TextContent(ctx)
	fmt.Printf("status via KindTestID: %q\n", statusText)
}
