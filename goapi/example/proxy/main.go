// Example: launch Camoufox behind a proxy with automatic timezone
// and geolocation resolution from the proxy's egress IP.
package main

import (
	"context"
	"fmt"
	"log"
	"os"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
	"github.com/lang315/camoufox/goapi/pkg/proxy"
)

func main() {
	exe := os.Getenv("CAMOUFOX_BIN")
	server := os.Getenv("HTTP_PROXY_URL") // e.g. http://user:pass@proxy:8080
	if exe == "" || server == "" {
		log.Fatal("set CAMOUFOX_BIN and HTTP_PROXY_URL")
	}

	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()

	b, err := camoufox.Launch(ctx,
		camoufox.WithExecutablePath(exe),
		camoufox.WithOS("macos"),
		camoufox.WithHeadless(true),
		camoufox.WithProxy(proxy.Proxy{Server: server}),
		camoufox.WithGeoIP(true),
	)
	if err != nil {
		log.Fatalf("launch: %v", err)
	}
	defer b.Close()

	bc, _ := b.NewContext(ctx)
	p, _ := bc.NewPage(ctx)
	if err := p.Goto(ctx, "https://browserleaks.com/ip"); err != nil {
		log.Fatalf("goto: %v", err)
	}
	tz, _ := p.Evaluate(ctx, "Intl.DateTimeFormat().resolvedOptions().timeZone")
	fmt.Printf("page-side timezone = %v\n", tz)
}
