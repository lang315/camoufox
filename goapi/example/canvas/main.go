// Canvas determinism smoke test.
//
// Pre-patch (current binary): two reads in the same context return
// identical bytes (no perturbation), and two reads across contexts
// also return identical bytes. The harness PRINTS the same-context
// determinism PASS, and the cross-context determinism FAIL is the
// expected pre-patch outcome.
//
// Post-patch: same-context still PASSES, cross-context FAILS reverses
// to PASS (different hashes per BrowserContext).
package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"log"
	"os"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
)

const drawJS = `(() => {
	const c = document.createElement('canvas');
	c.width = 220; c.height = 30;
	const g = c.getContext('2d');
	g.textBaseline = 'top';
	g.font = '14px Arial';
	g.fillStyle = '#f60';
	g.fillRect(125, 1, 62, 20);
	g.fillStyle = '#069';
	g.fillText('Camoufox 1.0!', 2, 15);
	g.fillStyle = 'rgba(102,204,0,0.7)';
	g.fillText('Camoufox 1.0!', 4, 17);
	return c.toDataURL();
})()`

func hashBytes(s string) string {
	sum := sha256.Sum256([]byte(s))
	return hex.EncodeToString(sum[:16])
}

func main() {
	exe := os.Getenv("CAMOUFOX_BIN")
	if exe == "" {
		log.Fatal("set CAMOUFOX_BIN")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()

	b, err := camoufox.Launch(ctx,
		camoufox.WithExecutablePath(exe),
		camoufox.WithOS("windows"),
		camoufox.WithHeadless(true),
		camoufox.WithCanvasNoise(0.0005, 1), // no-op vs unpatched binary
	)
	if err != nil {
		log.Fatalf("launch: %v", err)
	}
	defer b.Close()

	bc1, _ := b.NewContext(ctx)
	p1, _ := bc1.NewPage(ctx)
	_ = p1.Goto(ctx, "about:blank")
	d1a, _ := p1.Evaluate(ctx, drawJS)
	d1b, _ := p1.Evaluate(ctx, drawJS)

	bc2, _ := b.NewContext(ctx)
	p2, _ := bc2.NewPage(ctx)
	_ = p2.Goto(ctx, "about:blank")
	d2, _ := p2.Evaluate(ctx, drawJS)

	h1a := hashBytes(d1a.(string))
	h1b := hashBytes(d1b.(string))
	h2 := hashBytes(d2.(string))

	fmt.Printf("ctx1 read1: %s\n", h1a)
	fmt.Printf("ctx1 read2: %s\n", h1b)
	fmt.Printf("ctx2 read1: %s\n", h2)

	sameCtxOK := h1a == h1b
	crossCtxDiffers := h1a != h2

	fmt.Printf("\nsame-context determinism: %v (must always PASS)\n", okStr(sameCtxOK))
	fmt.Printf("cross-context differs:    %v (pre-patch: FAIL expected; post-patch: PASS)\n",
		okStr(crossCtxDiffers))
}

func okStr(b bool) string {
	if b {
		return "PASS"
	}
	return "FAIL"
}
