// Example: exercise WaitFor + Click + Type against a real
// Camoufox binary. Loads a tiny inline data: URL with a button + input
// so we don't depend on network state.
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

const html = `<!doctype html><html><body>
<input id="name" placeholder="name">
<button id="go" onclick="document.title='clicked'">Go</button>
<div id="status"></div>
<script>
  document.getElementById('go').addEventListener('click', () => {
    document.getElementById('status').textContent = 'CLICKED:' + document.getElementById('name').value;
  });
</script>
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
		camoufox.WithOS("macos"),
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

	u := "data:text/html;charset=utf-8," + url.PathEscape(html)
	if err := p.Goto(ctx, u, camoufox.GotoOptions{WaitUntil: camoufox.WaitUntilDOMContentLoaded}); err != nil {
		log.Fatalf("goto: %v", err)
	}
	if _, err := p.WaitFor(ctx, "#name", camoufox.WaitForOptions{State: camoufox.WaitAttached}); err != nil {
		log.Fatalf("wait name: %v", err)
	}
	if err := p.Type(ctx, "#name", "camoufox-go"); err != nil {
		log.Fatalf("type: %v", err)
	}
	if err := p.Click(ctx, "#go"); err != nil {
		log.Fatalf("click: %v", err)
	}
	if _, err := p.WaitFor(ctx, "#status:not(:empty)", camoufox.WaitForOptions{State: camoufox.WaitAttached}); err != nil {
		log.Fatalf("wait status: %v", err)
	}
	got, err := p.Evaluate(ctx, "document.getElementById('status').textContent")
	if err != nil {
		log.Fatalf("eval: %v", err)
	}
	fmt.Printf("status text = %q\n", got)
	title, _ := p.Evaluate(ctx, "document.title")
	fmt.Printf("title = %q\n", title)
}
