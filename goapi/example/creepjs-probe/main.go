// CreepJS DOM probe — dumps result text + headless-related lines.
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
)

func main() {
	exe := os.Getenv("CAMOUFOX_BIN")
	if exe == "" {
		log.Fatal("set CAMOUFOX_BIN")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 240*time.Second)
	defer cancel()

	b, err := camoufox.Launch(ctx,
		camoufox.WithExecutablePath(exe),
		camoufox.WithOS("windows"),
		camoufox.WithHeadless(true),
	)
	if err != nil {
		log.Fatal(err)
	}
	defer b.Close()
	bc, _ := b.NewContext(ctx)
	p, _ := bc.NewPage(ctx)
	if err := p.Goto(ctx, "https://abrahamjuliot.github.io/creepjs/", camoufox.GotoOptions{
		WaitUntil: camoufox.WaitUntilDOMContentLoaded,
		Timeout:   60 * time.Second,
	}); err != nil {
		log.Fatal(err)
	}
	// Wait long enough for async fingerprinting.
	time.Sleep(45 * time.Second)

	summary, err := p.Evaluate(ctx, `(() => {
		const out = {};
		// All text containing 'trust' / 'fingerprint' / 'headless' / 'bot'.
		const txt = document.body.innerText || '';
		const lines = txt.split(/\n/).map(s => s.trim()).filter(s => s.length > 0);
		const flagged = lines.filter(l => /trust|fingerprint hash|fingerprint id|headless|bot|automation|webdriver/i.test(l)).slice(0, 60);
		out.flagged_lines = flagged;
		// Try common CreepJS selectors.
		const trySel = (s) => {
			const e = document.querySelector(s);
			return e ? (e.textContent || '').trim().slice(0, 200) : null;
		};
		out.sel_trust_score = trySel('.trust-score');
		out.sel_trust = trySel('#trust');
		out.sel_trust_class = trySel('[class*=trust]');
		out.sel_score = trySel('[class*=score]');
		out.sel_fp_id = trySel('[class*=fingerprint]');
		// All classes containing trust/score/fingerprint.
		const candidates = Array.from(document.querySelectorAll('*')).filter(e => {
			const c = (e.className || '').toString();
			return /trust|score|fingerprint|visitor|lies/i.test(c) && c.length < 200;
		}).slice(0, 40);
		out.candidate_elements = candidates.map(e => ({
			tag: e.tagName,
			cls: (e.className || '').toString(),
			txt: (e.textContent || '').trim().slice(0, 100),
		}));
		return out;
	})()`)
	if err != nil {
		log.Fatal(err)
	}
	b2, _ := json.MarshalIndent(summary, "", "  ")
	fmt.Println(string(b2))
}
