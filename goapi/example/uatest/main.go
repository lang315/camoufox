// User-agent spoofing test.
//
// Sets a custom navigator.userAgent and (unless CF_UA_NOHEADER) the
// matching HTTP User-Agent header, lets the preset fill the rest of the
// fingerprint coherently, then verifies the fake UA is applied
// consistently across four surfaces that detectors cross-check:
//   - navigator.userAgent (main thread)
//   - navigator.userAgent (web worker)
//   - the HTTP User-Agent request header
//   - navigator.platform / oscpu coherence with the UA's claimed OS
//
// Run:
//   CAMOUFOX_BIN=... CF_UA="Mozilla/5.0 (Windows NT 10.0; ...)" ./uatest
//   CAMOUFOX_BIN=... CF_UA_NOHEADER=1 ./uatest   # show the mismatch trap
// Env: CF_UA, CF_OS, CF_UA_NOHEADER, CF_DISPLAY, CF_PROXY.
package main

import (
	"context"
	"fmt"
	"log"
	"os"
	"regexp"
	"strings"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
	"github.com/lang315/camoufox/goapi/pkg/config"
	"github.com/lang315/camoufox/goapi/pkg/proxy"
)

func osFromUA(ua string) string {
	l := strings.ToLower(ua)
	switch {
	case strings.Contains(l, "windows"):
		return "windows"
	case strings.Contains(l, "mac os"), strings.Contains(l, "macintosh"):
		return "macos"
	case strings.Contains(l, "linux"), strings.Contains(l, "x11"):
		return "linux"
	}
	return "windows"
}

func env(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}

var headerUARE = regexp.MustCompile(`"user-agent"\s*:\s*"([^"]+)"`)

func main() {
	exe := os.Getenv("CAMOUFOX_BIN")
	if exe == "" {
		log.Fatal("set CAMOUFOX_BIN")
	}
	ua := env("CF_UA", "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0")
	targetOS := env("CF_OS", osFromUA(ua))
	syncHeader := os.Getenv("CF_UA_NOHEADER") == ""

	cfg := &config.Config{NavigatorUserAgent: ua}
	if syncHeader {
		cfg.HeadersUserAgent = ua
	}

	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()
	opts := []camoufox.Option{
		camoufox.WithExecutablePath(exe),
		camoufox.WithConfig(cfg), // preset fills the rest; our UA fields are kept
		camoufox.WithOS(targetOS),
	}
	if disp := os.Getenv("CF_DISPLAY"); disp != "" {
		opts = append(opts, camoufox.WithVirtualDisplay(disp))
	} else {
		opts = append(opts, camoufox.WithHeadless(true))
	}
	if px := os.Getenv("CF_PROXY"); px != "" {
		opts = append(opts, camoufox.WithProxy(proxy.Proxy{Server: px}), camoufox.WithGeoIP(true))
	}
	b, err := camoufox.Launch(ctx, opts...)
	if err != nil {
		log.Fatalf("launch: %v", err)
	}
	defer b.Close()
	bc, _ := b.NewContext(ctx)
	p, _ := bc.NewPage(ctx)
	_ = p.Goto(ctx, "about:blank")

	// Kick a web-worker UA probe (Evaluate does not await promises, so
	// stash the result on a global and read it after a short settle).
	_, _ = p.Evaluate(ctx, `window.__wua='pending'; try{
		const w=new Worker(URL.createObjectURL(new Blob(["onmessage=()=>postMessage(navigator.userAgent)"],{type:"application/javascript"})));
		w.onmessage=e=>window.__wua=e.data; w.postMessage(0);
	}catch(e){window.__wua='err:'+e}`)

	navRaw, _ := p.Evaluate(ctx, `({ua:navigator.userAgent, appVersion:navigator.appVersion,
		platform:navigator.platform, oscpu:navigator.oscpu||'', vendor:navigator.vendor,
		productSub:navigator.productSub, appName:navigator.appName})`)
	nav, _ := navRaw.(map[string]any)

	time.Sleep(1500 * time.Millisecond)
	wuaRaw, _ := p.Evaluate(ctx, `window.__wua`)
	workerUA := fmt.Sprintf("%v", wuaRaw)

	// HTTP User-Agent header via an echo endpoint.
	headerUA := "<unread>"
	if err := p.Goto(ctx, "https://httpbin.org/user-agent", camoufox.GotoOptions{WaitUntil: camoufox.WaitUntilDOMContentLoaded, Timeout: 40 * time.Second}); err == nil {
		time.Sleep(1500 * time.Millisecond)
		if bodyRaw, e := p.Evaluate(ctx, `document.body.innerText`); e == nil {
			if m := headerUARE.FindStringSubmatch(fmt.Sprintf("%v", bodyRaw)); len(m) == 2 {
				headerUA = m[1]
			}
		}
	}

	navUA := fmt.Sprintf("%v", nav["ua"])
	platform := fmt.Sprintf("%v", nav["platform"])
	wantPlatform := map[string]string{"windows": "Win32", "macos": "MacIntel", "linux": "Linux x86_64"}[targetOS]

	fmt.Println("=== fake UA test ===")
	fmt.Printf("requested UA : %s\n", ua)
	fmt.Printf("navigator.ua : %s\n", navUA)
	fmt.Printf("worker.ua    : %s\n", workerUA)
	fmt.Printf("HTTP header  : %s\n", headerUA)
	fmt.Printf("platform     : %s (want %s)\n", platform, wantPlatform)
	fmt.Printf("oscpu        : %v\n", nav["oscpu"])
	fmt.Printf("vendor       : %v | productSub: %v | appName: %v\n", nav["vendor"], nav["productSub"], nav["appName"])

	ok := navUA == ua
	okWorker := workerUA == ua
	okHeader := headerUA == ua
	okPlat := platform == wantPlatform

	// Engine coherence: Camoufox is Firefox. A UA claiming a different
	// engine (Chrome/Safari/Edge) still leaks Firefox's navigator.vendor
	// ("" not "Google Inc.") and productSub (20100101 not 20030107), so a
	// detector cross-checking those against the UA catches the lie.
	vendor := fmt.Sprintf("%v", nav["vendor"])
	productSub := fmt.Sprintf("%v", nav["productSub"])
	claimsChromium := strings.Contains(ua, "Chrome/") || strings.Contains(ua, "Edg/") || strings.Contains(ua, "Safari/537")
	engineOK := true
	if claimsChromium {
		engineOK = vendor == "Google Inc." && productSub == "20030107"
	}
	fmt.Println("--- coherence ---")
	fmt.Printf("navigator.ua == requested : %v\n", ok)
	fmt.Printf("worker.ua    == requested : %v\n", okWorker)
	fmt.Printf("HTTP header  == requested : %v%s\n", okHeader, hdrNote(syncHeader, okHeader))
	fmt.Printf("platform coherent         : %v\n", okPlat)
	if claimsChromium {
		fmt.Printf("engine coherent (vendor/productSub match a real Chromium): %v\n", engineOK)
	}
	if ok && okWorker && okHeader && okPlat && engineOK {
		fmt.Println("VERDICT: PASS — fake UA applied coherently on every surface")
	} else if !engineOK {
		fmt.Println("VERDICT: MISMATCH — UA claims a non-Firefox engine but navigator.vendor/productSub still read Firefox (Camoufox spoofs within Firefox, not across engines)")
	} else {
		fmt.Println("VERDICT: MISMATCH — a detector could cross-check the differing surfaces")
	}
}

func hdrNote(sync, ok bool) string {
	if !sync && !ok {
		return "  (expected: CF_UA_NOHEADER left the header at the preset UA — this is the trap)"
	}
	return ""
}
