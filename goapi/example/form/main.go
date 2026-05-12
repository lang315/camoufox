// Example: demonstrate FillForm on a simple HTML form.
//
// Run: CAMOUFOX_BIN=/path/to/camoufox go run ./example/form
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

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		_, _ = fmt.Fprint(w, `<html><body>
<form>
  <label for="username">Username</label>
  <input id="username" name="username" type="text"><br>
  <input placeholder="Password" type="password" id="password"><br>
  <button type="submit">Login</button>
</form>
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

	if err := p.Goto(ctx, srv.URL, camoufox.GotoOptions{WaitUntil: camoufox.WaitUntilDOMContentLoaded}); err != nil {
		log.Fatalf("goto: %v", err)
	}

	n, err := p.FillForm(ctx, map[string]string{
		"Username": "alice",
		"Password": "s3cr3t",
	})
	if err != nil {
		log.Fatalf("FillForm: %v", err)
	}
	fmt.Printf("Filled %d fields\n", n)

	// Screenshot the result.
	png, err := p.Screenshot(ctx, camoufox.Clip{Width: 800, Height: 200})
	if err != nil {
		log.Fatalf("screenshot: %v", err)
	}
	if err := os.WriteFile("form_result.png", png, 0644); err != nil {
		log.Fatalf("write: %v", err)
	}
	fmt.Println("wrote form_result.png")
}
