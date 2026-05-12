// Example: launch Camoufox, navigate to a URL, evaluate JS,
// capture a screenshot.
//
// Run: CAMOUFOX_BIN=/path/to/camoufox/firefox go run ./example/basic
package main

import (
	"context"
	"fmt"
	"log"
	"os"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
)

func main() {
	exe := os.Getenv("CAMOUFOX_BIN")
	if exe == "" {
		log.Fatal("set CAMOUFOX_BIN to your camoufox firefox binary")
	}

	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	b, err := camoufox.Launch(ctx,
		camoufox.WithExecutablePath(exe),
		camoufox.WithOS("windows"),
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

	if err := p.Goto(ctx, "https://example.com"); err != nil {
		log.Fatalf("goto: %v", err)
	}

	ua, err := p.Evaluate(ctx, "navigator.userAgent")
	if err != nil {
		log.Fatalf("evaluate: %v", err)
	}
	fmt.Printf("navigator.userAgent = %v\n", ua)

	png, err := p.Screenshot(ctx, camoufox.Clip{})
	if err != nil {
		log.Fatalf("screenshot: %v", err)
	}
	if err := os.WriteFile("example.png", png, 0644); err != nil {
		log.Fatalf("write: %v", err)
	}
	fmt.Println("wrote example.png")
}
