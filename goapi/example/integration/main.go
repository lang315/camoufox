// Integration smoke against anti-browser detection sites.
//
// One session, four oracles in series:
//
//   1. creepjs           — headless / lies / FP ID
//   2. sannysoft         — bot detection matrix
//   3. areyouheadless    — Antoine Vastel single-page check
//   4. browserleaks/webrtc — IP leakage confirmation
//
// Writes per-oracle JSON to ./integration-results/ for human review.
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
)

type oracle struct {
	Name    string
	URL     string
	Settle  time.Duration
	Extract string
}

var oracles = []oracle{
	{
		Name:   "creepjs",
		URL:    "https://abrahamjuliot.github.io/creepjs/",
		Settle: 40 * time.Second,
		Extract: `(() => {
			const txt = document.body.innerText || '';
			const lines = txt.split(/\n/).map(s => s.trim()).filter(s => s);
			const grab = (re) => lines.find(l => re.test(l)) || '';
			const fpId = (() => {
				const e = document.querySelector('.fingerprint-header-container, .fingerprint-header');
				if (!e) return '';
				const t = e.textContent.replace(/\s+/g, ' ');
				const m = t.match(/FP ID:\s*([a-f0-9]{32,})/i);
				return m ? m[1] : '';
			})();
			const fuzzy = (() => {
				const e = document.querySelector('.fingerprint-header-container, .fingerprint-header');
				if (!e) return '';
				const t = e.textContent.replace(/\s+/g, ' ');
				const m = t.match(/Fuzzy:\s*([a-f0-9]{32,})/i);
				return m ? m[1] : '';
			})();
			return {
				fp_id:        fpId,
				fuzzy_hash:   fuzzy,
				headless_pct: grab(/% like headless/),
				bot_pct:      grab(/% bot|% like a bot/i),
				lies_line:    grab(/^Lies/i),
				trust_line:   grab(/Trust Score|^Trust:|truthy/i),
				ua_line:      grab(/^User\s*Agent/i),
				webrtc_line:  grab(/WebRTC/i),
			};
		})()`,
	},
	{
		Name:   "sannysoft",
		URL:    "https://bot.sannysoft.com/",
		Settle: 5 * time.Second,
		Extract: `(() => {
			const out = { _webdriver: String(navigator.webdriver),
			              _plugins:   navigator.plugins.length,
			              _languages: (navigator.languages||[]).join(','),
			              _platform:  navigator.platform };
			const rows = document.querySelectorAll('table tr');
			const tests = {};
			for (const r of rows) {
				const cells = r.querySelectorAll('td');
				if (cells.length < 2) continue;
				const k = cells[0].textContent.trim();
				if (!k) continue;
				tests[k] = cells[1].textContent.trim();
			}
			out.tests = tests;
			return out;
		})()`,
	},
	{
		Name:   "areyouheadless",
		URL:    "https://arh.antoinevastel.com/bots/areyouheadless",
		Settle: 4 * time.Second,
		Extract: `(() => ({
			body: (document.body.innerText || '').slice(0, 600),
		}))()`,
	},
	{
		Name:   "browserleaks_webrtc",
		URL:    "https://browserleaks.com/webrtc",
		Settle: 8 * time.Second,
		Extract: `(() => {
			const out = {};
			// Try multiple selector strategies for IP rows.
			const t = (sel) => {
				const e = document.querySelector(sel);
				return e ? (e.textContent || '').trim() : '';
			};
			out.public_ip = t('#public-ip') || t('[id*=public]');
			out.local_ip  = t('#local-ip')  || t('[id*=local]');
			out.mdns      = t('#mdns');
			out.fp        = t('#fp');
			// SDP table dump.
			const tables = document.querySelectorAll('table');
			let sdp = '';
			for (const tbl of tables) {
				const txt = tbl.textContent || '';
				if (/candidate|srflx|host|raddr/i.test(txt)) sdp += txt.slice(0, 1000) + '\n';
			}
			out.sdp_excerpt = sdp.slice(0, 2000);
			out.body_snippet = (document.body.innerText || '').slice(0, 1200);
			return out;
		})()`,
	},
}

func main() {
	exe := os.Getenv("CAMOUFOX_BIN")
	if exe == "" {
		log.Fatal("set CAMOUFOX_BIN")
	}
	outDir := "integration-results"
	_ = os.MkdirAll(outDir, 0755)

	ctx, cancel := context.WithTimeout(context.Background(), 600*time.Second)
	defer cancel()

	b, err := camoufox.Launch(ctx,
		camoufox.WithExecutablePath(exe),
		camoufox.WithOS("windows"),
		camoufox.WithHeadless(true),
	)
	if err != nil {
		log.Fatalf("launch: %v", err)
	}
	defer b.Close()

	bc, _ := b.NewContext(ctx)
	p, _ := bc.NewPage(ctx)

	for _, o := range oracles {
		log.Printf("== %s ==", o.Name)
		log.Printf("  GET %s", o.URL)
		if err := p.Goto(ctx, o.URL, camoufox.GotoOptions{
			WaitUntil: camoufox.WaitUntilDOMContentLoaded,
			Timeout:   90 * time.Second,
		}); err != nil {
			log.Printf("  goto: %v", err)
			continue
		}
		log.Printf("  settle %s", o.Settle)
		time.Sleep(o.Settle)
		v, err := p.Evaluate(ctx, o.Extract)
		if err != nil {
			log.Printf("  eval: %v", err)
			continue
		}
		b2, _ := json.MarshalIndent(v, "", "  ")
		path := filepath.Join(outDir, o.Name+".json")
		_ = os.WriteFile(path, b2, 0644)
		fmt.Printf("== %s ==\n%s\n\n", o.Name, string(b2))
		log.Printf("  wrote %s", path)
	}
}
