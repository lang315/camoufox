// Example: QueryXPath across a simple DOM.
// Run: CAMOUFOX_BIN=/path/to/camoufox go run ./example/xpath
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

const xhtmlPage = `<!doctype html><html><body>
<ul>
  <li class="fruit">apple</li>
  <li class="fruit">banana</li>
  <li class="veggie">carrot</li>
</ul>
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

	u := "data:text/html;charset=utf-8," + url.PathEscape(xhtmlPage)
	if err := p.Goto(ctx, u, camoufox.GotoOptions{WaitUntil: camoufox.WaitUntilDOMContentLoaded}); err != nil {
		log.Fatalf("goto: %v", err)
	}

	// Select all fruit list items by XPath attribute predicate.
	els, err := p.QueryXPath(ctx, `//li[@class='fruit']`)
	if err != nil {
		log.Fatalf("QueryXPath: %v", err)
	}
	fmt.Printf("found %d fruit items:\n", len(els))
	for _, el := range els {
		text, _ := el.TextContent(ctx)
		fmt.Printf("  - %s\n", text)
	}
}
