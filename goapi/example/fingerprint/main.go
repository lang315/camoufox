// Example: launch Camoufox with a hand-built CAMOU_CONFIG instead of
// the bundled preset sampler.
package main

import (
	"context"
	"fmt"
	"log"
	"os"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
	"github.com/lang315/camoufox/goapi/pkg/config"
)

func main() {
	exe := os.Getenv("CAMOUFOX_BIN")
	if exe == "" {
		log.Fatal("set CAMOUFOX_BIN")
	}

	cfg := &config.Config{
		NavigatorUserAgent:           "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:134.0) Gecko/20100101 Firefox/134.0",
		NavigatorPlatform:            "MacIntel",
		NavigatorOscpu:               "Intel Mac OS X 10.15",
		NavigatorHardwareConcurrency: config.Uint32(10),
		ScreenWidth:                  config.Uint32(1680),
		ScreenHeight:                 config.Uint32(1050),
		ScreenColorDepth:             config.Uint32(30),
		Timezone:                     "Europe/London",
		LocaleLanguage:               "en",
		LocaleRegion:                 "GB",
		Humanize:                     config.Bool(true),
	}

	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	b, err := camoufox.Launch(ctx,
		camoufox.WithExecutablePath(exe),
		camoufox.WithConfig(cfg),
		camoufox.WithNoFingerprint(),
		camoufox.WithHeadless(true),
	)
	if err != nil {
		log.Fatalf("launch: %v", err)
	}
	defer b.Close()

	bc, _ := b.NewContext(ctx)
	p, _ := bc.NewPage(ctx)
	_ = p.Goto(ctx, "about:blank")
	plat, _ := p.Evaluate(ctx, "navigator.platform")
	fmt.Printf("navigator.platform = %v\n", plat)
}
