// Example: launch Camoufox, navigate to a data URL with an input,
// type a shifted character, verify the value, and take a screenshot.
//
// Run: CAMOUFOX_BIN=/path/to/firefox go run ./example/keyboard
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

	dataURL := `data:text/html,<html><body><input id="i" type="text"></body></html>`
	if err := p.Goto(ctx, dataURL); err != nil {
		log.Fatalf("goto: %v", err)
	}

	if err := p.Focus(ctx, "#i"); err != nil {
		log.Fatalf("focus: %v", err)
	}

	kb := p.Keyboard()
	if err := kb.Down(ctx, "Shift"); err != nil {
		log.Fatalf("shift down: %v", err)
	}
	if err := kb.Press(ctx, "KeyH"); err != nil {
		log.Fatalf("press KeyH: %v", err)
	}
	if err := kb.Up(ctx, "Shift"); err != nil {
		log.Fatalf("shift up: %v", err)
	}
	if err := kb.Type(ctx, "ello"); err != nil {
		log.Fatalf("type: %v", err)
	}

	val, err := p.Evaluate(ctx, "document.getElementById('i').value")
	if err != nil {
		log.Fatalf("evaluate: %v", err)
	}
	fmt.Printf("input value: %v\n", val)

	png, err := p.Screenshot(ctx, camoufox.Clip{})
	if err != nil {
		log.Fatalf("screenshot: %v", err)
	}
	if err := os.WriteFile("keyboard.png", png, 0644); err != nil {
		log.Fatalf("write: %v", err)
	}
	fmt.Println("wrote keyboard.png")
}
