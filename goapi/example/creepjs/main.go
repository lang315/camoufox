// Example: load CreepJS and read the computed trust score / flags
// to validate that CAMOU_CONFIG + Juggler injection actually fools
// the fingerprint detector.
package main

import (
	"context"
	"fmt"
	"log"
	"os"
	"strings"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
)

func main() {
	exe := os.Getenv("CAMOUFOX_BIN")
	if exe == "" {
		log.Fatal("set CAMOUFOX_BIN")
	}
	targetOS := os.Getenv("CF_OS")
	if targetOS == "" {
		targetOS = "windows"
	}

	ctx, cancel := context.WithTimeout(context.Background(), 180*time.Second)
	defer cancel()

	b, err := camoufox.Launch(ctx,
		camoufox.WithExecutablePath(exe),
		camoufox.WithOS(targetOS),
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

	const url = "https://abrahamjuliot.github.io/creepjs/"
	fmt.Printf("loading %s (target os=%s) ...\n", url, targetOS)
	if err := p.Goto(ctx, url, camoufox.GotoOptions{
		WaitUntil: camoufox.WaitUntilDOMContentLoaded,
		Timeout:   60 * time.Second,
	}); err != nil {
		log.Fatalf("goto: %v", err)
	}

	// CreepJS computes asynchronously; wait for #fingerprint-data .visitor row
	// to settle and for the trust-score badge to be filled in.
	fmt.Println("waiting for CreepJS results ...")
	deadline := time.Now().Add(120 * time.Second)
	for time.Now().Before(deadline) {
		ready, _ := p.Evaluate(ctx, `(() => {
			const t = document.querySelector('.trust-score');
			return !!(t && t.textContent && t.textContent.match(/\d/));
		})()`)
		if ok, _ := ready.(bool); ok {
			break
		}
		time.Sleep(1 * time.Second)
	}

	// Pull trust score and key flags.
	summary, err := p.Evaluate(ctx, `(() => {
		const get = sel => {
			const el = document.querySelector(sel);
			return el ? el.textContent.trim().replace(/\s+/g, ' ') : '';
		};
		return {
			trust: get('.trust-score'),
			osFromUA: get('.os-system'),
			osFromFonts: (Array.from(document.querySelectorAll('.fingerprint-data .reveal'))
				.find(e => e.previousSibling && /fonts/i.test(e.previousSibling.textContent || '')) || {}).textContent || '',
			ua: navigator.userAgent,
			platform: navigator.platform,
			timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
			webglVendor: (() => { try { const g = document.createElement('canvas').getContext('webgl'); return g.getParameter(g.getExtension('WEBGL_debug_renderer_info').UNMASKED_VENDOR_WEBGL); } catch(e){return 'n/a'} })(),
			webglRenderer: (() => { try { const g = document.createElement('canvas').getContext('webgl'); return g.getParameter(g.getExtension('WEBGL_debug_renderer_info').UNMASKED_RENDERER_WEBGL); } catch(e){return 'n/a'} })(),
		};
	})()`)
	if err != nil {
		log.Fatalf("eval summary: %v", err)
	}
	for k, v := range summary.(map[string]any) {
		fmt.Printf("%-15s %v\n", k+":", v)
	}

	// Save a screenshot for visual inspection.
	png, err := p.Screenshot(ctx, camoufox.Clip{Width: 1280, Height: 1600})
	if err != nil {
		log.Fatalf("screenshot: %v", err)
	}
	out := "creepjs-" + targetOS + ".png"
	if err := os.WriteFile(out, png, 0644); err != nil {
		log.Fatalf("write: %v", err)
	}
	fmt.Printf("wrote %s (%d bytes)\n", out, len(png))

	// Stealth red-flags: anything mentioning "headless", "automation",
	// "playwright", "puppeteer" in the page text is bad.
	bad, _ := p.Evaluate(ctx, `(() => {
		const t = document.body.innerText.toLowerCase();
		const flags = [];
		for (const w of ['headless','automation','playwright','puppeteer','webdriver']) {
			if (t.includes(w)) flags.push(w);
		}
		return flags;
	})()`)
	if arr, _ := bad.([]any); len(arr) > 0 {
		var ws []string
		for _, x := range arr {
			ws = append(ws, fmt.Sprintf("%v", x))
		}
		fmt.Printf("⚠ red flags in page text: %s\n", strings.Join(ws, ", "))
	} else {
		fmt.Println("no stealth red-flag words in page text")
	}
}
