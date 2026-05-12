// Bot-detection oracle harness.
//
// Probes Camoufox against the dedicated headless / automation detection
// sites (vs the fingerprint-uniqueness oracles in example/baseline).
// One CSV row per (session, oracle, field). Designed for integration
// validation of the Go launcher: if Camoufox is configured correctly,
// these sites should report "not a bot" / no headless flags.
//
// Run:
//   CAMOUFOX_BIN=/path/to/camoufox ./botdetect -n 3 -out botdetect.csv
package main

import (
	"context"
	"crypto/rand"
	"encoding/binary"
	"encoding/csv"
	"flag"
	"fmt"
	"log"
	mathrand "math/rand/v2"
	"os"
	"strings"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
)

type probe struct {
	URL     string
	Wait    string
	Settle  time.Duration
	Extract string
	Fields  []string
}

var probes = map[string]probe{
	// Sannysoft — classic headless/automation detection matrix. Renders
	// a table with green/red rows for webdriver, chrome, plugins,
	// languages, etc. We pull each row's pass/fail flag.
	"sannysoft": {
		URL:    "https://bot.sannysoft.com/",
		Wait:   "#fp2",
		Settle: 4 * time.Second,
		Extract: `(() => {
			const rows = Array.from(document.querySelectorAll('table tr'));
			const out = {};
			for (const r of rows) {
				const cells = r.querySelectorAll('td');
				if (cells.length < 2) continue;
				const name = cells[0].textContent.trim().replace(/\s+/g, '_').toLowerCase();
				const verdict = cells[1].textContent.trim();
				if (name) out[name] = verdict;
			}
			out._webdriver = String(navigator.webdriver);
			out._plugins_len = String(navigator.plugins.length);
			out._languages = (navigator.languages||[]).join(',');
			return out;
		})()`,
		Fields: []string{"_webdriver", "_plugins_len", "_languages",
			"user_agent", "webdriver_(new)", "webdriver_advanced",
			"chrome_(new)", "permissions_(new)", "plugins_length_(old)",
			"languages_(old)", "webgl_vendor", "webgl_renderer", "broken_image_dimensions"},
	},

	// AreYouHeadless — Antoine Vastel's single-page headless probe.
	// Returns "You are not Chrome headless" or red banner.
	"areyouheadless": {
		URL:    "https://arh.antoinevastel.com/bots/areyouheadless",
		Wait:   "#res",
		Settle: 3 * time.Second,
		Extract: `(() => ({
			verdict: (document.getElementById('res')||{}).textContent || '',
			body_snippet: (document.body.innerText||'').slice(0, 300),
		}))()`,
		Fields: []string{"verdict", "body_snippet"},
	},

	// Rebrowser bot detector — scores 0-100, lower = stealthier.
	"rebrowser": {
		URL:    "https://bot-detector.rebrowser.net/",
		Wait:   "",
		Settle: 5 * time.Second,
		Extract: `(() => {
			const txt = document.body.innerText || '';
			return {
				body_snippet: txt.slice(0, 800),
			};
		})()`,
		Fields: []string{"body_snippet"},
	},

	// BrowserLeaks JS — broad JS-level fingerprint.
	"browserleaks_js": {
		URL:    "https://browserleaks.com/javascript",
		Wait:   "table",
		Settle: 3 * time.Second,
		Extract: `(() => {
			const out = {};
			const rows = document.querySelectorAll('tr');
			for (const r of rows) {
				const th = r.querySelector('th'), td = r.querySelector('td');
				if (!th || !td) continue;
				const k = th.textContent.trim().replace(/\s+/g, '_').toLowerCase();
				out[k] = (td.textContent || '').trim().slice(0, 200);
			}
			return out;
		})()`,
		Fields: []string{"user_agent", "platform", "languages", "screen_resolution",
			"timezone", "hardware_concurrency", "device_memory"},
	},

	// BrowserLeaks WebGL — WebGL vendor/renderer leakage.
	"browserleaks_webgl": {
		URL:    "https://browserleaks.com/webgl",
		Wait:   "#webgl-unmasked-vendor",
		Settle: 3 * time.Second,
		Extract: `(() => ({
			unmasked_vendor:   (document.getElementById('webgl-unmasked-vendor')||{}).textContent || '',
			unmasked_renderer: (document.getElementById('webgl-unmasked-renderer')||{}).textContent || '',
			webgl_vendor:      (document.getElementById('webgl-vendor')||{}).textContent || '',
			webgl_renderer:    (document.getElementById('webgl-renderer')||{}).textContent || '',
		}))()`,
		Fields: []string{"unmasked_vendor", "unmasked_renderer", "webgl_vendor", "webgl_renderer"},
	},
}

func main() {
	var (
		bin     = os.Getenv("CAMOUFOX_BIN")
		nFlag   = flag.Int("n", 3, "number of sessions")
		outFlag = flag.String("out", "botdetect-results.csv", "CSV output path")
		osFlag  = flag.String("os", "windows", "spoofed OS")
		timeout = flag.Duration("timeout", 240*time.Second, "per-session timeout")
	)
	flag.Parse()
	if bin == "" {
		log.Fatal("set CAMOUFOX_BIN")
	}

	out, err := os.Create(*outFlag)
	if err != nil {
		log.Fatalf("create csv: %v", err)
	}
	defer out.Close()
	w := csv.NewWriter(out)
	defer w.Flush()

	if err := w.Write([]string{"session", "seed_hi", "seed_lo", "oracle", "field", "value"}); err != nil {
		log.Fatal(err)
	}

	for s := 0; s < *nFlag; s++ {
		hi, lo := randSeed()
		log.Printf("session %d/%d (seed %d/%d)...", s+1, *nFlag, hi, lo)
		rng := mathrand.New(mathrand.NewPCG(hi, lo))

		ctx, cancel := context.WithTimeout(context.Background(), *timeout)
		b, err := camoufox.Launch(ctx,
			camoufox.WithExecutablePath(bin),
			camoufox.WithOS(*osFlag),
			camoufox.WithHeadless(true),
			camoufox.WithRand(rng),
		)
		if err != nil {
			log.Printf("  launch: %v", err)
			cancel()
			continue
		}

		bc, _ := b.NewContext(ctx)
		p, err := bc.NewPage(ctx)
		if err != nil {
			log.Printf("  newpage: %v", err)
			b.Close()
			cancel()
			continue
		}

		for name, pr := range probes {
			row, err := runProbe(ctx, p, pr)
			if err != nil {
				log.Printf("  %s: %v", name, err)
				for _, f := range pr.Fields {
					w.Write([]string{fmt.Sprintf("%d", s), fmt.Sprintf("%d", hi), fmt.Sprintf("%d", lo), name, f, "<error>"})
				}
				continue
			}
			for _, f := range pr.Fields {
				w.Write([]string{fmt.Sprintf("%d", s), fmt.Sprintf("%d", hi), fmt.Sprintf("%d", lo), name, f, row[f]})
			}
		}
		w.Flush()
		b.Close()
		cancel()
	}
	log.Printf("done → %s", *outFlag)
}

func runProbe(ctx context.Context, p *camoufox.Page, pr probe) (map[string]string, error) {
	if err := p.Goto(ctx, pr.URL, camoufox.GotoOptions{
		WaitUntil: camoufox.WaitUntilDOMContentLoaded,
		Timeout:   60 * time.Second,
	}); err != nil {
		return nil, fmt.Errorf("goto: %w", err)
	}
	if pr.Wait != "" {
		waitCtx, cancel := context.WithTimeout(ctx, 30*time.Second)
		_, _ = p.WaitFor(waitCtx, pr.Wait, camoufox.WaitForOptions{State: camoufox.WaitAttached})
		cancel()
	}
	if pr.Settle > 0 {
		time.Sleep(pr.Settle)
	}
	v, err := p.Evaluate(ctx, pr.Extract)
	if err != nil {
		return nil, fmt.Errorf("eval: %w", err)
	}
	out := make(map[string]string)
	m, ok := v.(map[string]any)
	if !ok {
		return nil, fmt.Errorf("extract returned %T", v)
	}
	for k, val := range m {
		s := fmt.Sprintf("%v", val)
		s = strings.ReplaceAll(s, "\n", " ")
		s = strings.ReplaceAll(s, "\r", " ")
		out[k] = s
	}
	return out, nil
}

func randSeed() (uint64, uint64) {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		return uint64(time.Now().UnixNano()), 0
	}
	return binary.LittleEndian.Uint64(b[:8]), binary.LittleEndian.Uint64(b[8:])
}
