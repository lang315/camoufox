// Example: intercept a file-chooser dialog and supply a local file
// without showing the native OS file picker.
//
// Run: CAMOUFOX_BIN=/path/to/firefox go run ./example/upload
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

	// Create a temporary file to "upload".
	f, err := os.CreateTemp("", "camoufox-upload-*.txt")
	if err != nil {
		log.Fatalf("tmp file: %v", err)
	}
	_, _ = f.WriteString("Hello from camoufox upload example")
	f.Close()
	defer os.Remove(f.Name())

	var wg sync.WaitGroup
	wg.Add(1)
	sub := p.OnFileChooser(func(fc *camoufox.FileChooser) {
		fmt.Printf("file chooser opened (multiple=%v)\n", fc.IsMultiple)
		if err := fc.SetFiles(ctx, []string{f.Name()}); err != nil {
			log.Printf("SetFiles: %v", err)
		}
		wg.Done()
	})
	defer p.Off(sub)

	dataURL := `data:text/html,<html><body><input id="f" type="file"></body></html>`
	if err := p.Goto(ctx, dataURL, camoufox.GotoOptions{WaitUntil: camoufox.WaitUntilLoad}); err != nil {
		log.Fatalf("goto: %v", err)
	}

	el, err := p.QuerySelector(ctx, "#f")
	if err != nil || el == nil {
		log.Fatalf("QuerySelector: %v, el=%v", err, el)
	}
	if err := el.Click(ctx); err != nil {
		log.Fatalf("Click: %v", err)
	}

	done := make(chan struct{})
	go func() { wg.Wait(); close(done) }()
	select {
	case <-done:
	case <-time.After(10 * time.Second):
		log.Fatal("timed out waiting for file chooser")
	}

	name, err := p.Evaluate(ctx, `document.getElementById('f').files[0].name`)
	if err != nil {
		log.Fatalf("Evaluate: %v", err)
	}
	fmt.Printf("input.files[0].name = %v\n", name)
}
