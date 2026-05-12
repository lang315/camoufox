// Example: launch Camoufox, navigate to a page that calls confirm(),
// register an OnDialog handler that dismisses the dialog, then exit.
//
// Run: CAMOUFOX_BIN=/path/to/firefox go run ./example/dialog
package main

import (
	"context"
	"fmt"
	"log"
	"os"
	"sync"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
)

func main() {
	exe := os.Getenv("CAMOUFOX_BIN")
	if exe == "" {
		log.Fatal("set CAMOUFOX_BIN to your camoufox firefox binary")
	}

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	b, err := camoufox.Launch(ctx,
		camoufox.WithExecutablePath(exe),
		camoufox.WithHeadless(true),
		camoufox.WithDebug(os.Getenv("DEBUG") != ""),
	)
	if err != nil {
		log.Fatalf("launch: %v", err)
	}
	defer b.Close()

	bc, err := b.NewContext(ctx)
	if err != nil {
		log.Fatalf("new context: %v", err)
	}
	p, err := bc.NewPage(ctx)
	if err != nil {
		log.Fatalf("new page: %v", err)
	}
	defer p.Close(ctx)

	var wg sync.WaitGroup
	wg.Add(1)
	sub := p.OnDialog(func(d *camoufox.Dialog) {
		fmt.Printf("dialog: type=%s message=%q\n", d.Type, d.Message)
		if err := d.Dismiss(ctx); err != nil {
			log.Printf("dismiss: %v", err)
		}
		wg.Done()
	})
	defer p.Off(sub)

	dataURL := `data:text/html,<html><body><script>confirm('proceed?');</script></body></html>`
	if err := p.Goto(ctx, dataURL, camoufox.GotoOptions{WaitUntil: camoufox.WaitUntilLoad}); err != nil {
		log.Printf("goto (may be interrupted by dialog): %v", err)
	}

	done := make(chan struct{})
	go func() { wg.Wait(); close(done) }()
	select {
	case <-done:
		fmt.Println("dialog dismissed, page continues")
	case <-time.After(10 * time.Second):
		log.Fatal("timed out waiting for dialog")
	}
}
