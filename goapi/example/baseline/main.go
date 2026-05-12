// Multi-oracle baseline harness.
//
// Launches N fresh Camoufox sessions with distinct RNG seeds. For each
// session, probes a set of fingerprint oracles and emits one CSV row
// per (session, attribute). Used twice:
//
//  1. Before the WebRTC + canvas patches land, to capture the
//     unique-per-instance baseline (CreepJS trust score, canvas hash,
//     WebRTC public/local/mDNS/DTLS lines, AmIUnique ratios).
//  2. After patches land, to prove uniqueness drops on the targeted
//     vectors without regressing the others.
//
// Run:
//   CAMOUFOX_BIN=/path/to/camoufox ./baseline -n 10 -out results.csv
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
	Wait    string                          // CSS selector to wait for (or "" = none)
	Extract string                          // JS that returns a flat string→string map
	Fields  []string                        // CSV column suffixes (in order)
}

var probes = map[string]probe{
	"creepjs": {
		URL:  "https://abrahamjuliot.github.io/creepjs/",
		Wait: ".trust-score",
		Extract: `(() => {
			const get = sel => {
				const e = document.querySelector(sel);
				return e ? (e.textContent || '').trim().replace(/\s+/g, ' ') : '';
			};
			return {
				trust: get('.trust-score'),
				fp_hash: get('#fingerprint-data .fingerprint-hash'),
				ua_os: get('.os-system'),
			};
		})()`,
		Fields: []string{"trust", "fp_hash", "ua_os"},
	},
	"browserleaks_canvas": {
		URL:  "https://browserleaks.com/canvas",
		Wait: "#crc",
		Extract: `(() => ({
			crc: (document.getElementById('crc')||{}).textContent || '',
			pict: (document.getElementById('pict')||{}).textContent || '',
			uniq: (document.getElementById('uniq')||{}).textContent || '',
		}))()`,
		Fields: []string{"crc", "pict", "uniq"},
	},
	"browserleaks_webrtc": {
		URL:  "https://browserleaks.com/webrtc",
		Wait: "#public-ip",
		Extract: `(() => ({
			public_ip: (document.getElementById('public-ip')||{}).textContent || '',
			local_ip:  (document.getElementById('local-ip')||{}).textContent  || '',
			mdns:      (document.getElementById('mdns')     ||{}).textContent || '',
			fp:        (document.getElementById('fp')       ||{}).textContent || '',
		}))()`,
		Fields: []string{"public_ip", "local_ip", "mdns", "fp"},
	},
	"client_eval": {
		// Pure JS introspection — no network, fastest, runs even if
		// the external oracles are flaky. Captures the values our
		// patches will affect directly.
		URL:  "about:blank",
		Wait: "",
		Extract: `(() => {
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
			const dataURL = c.toDataURL();
			let hash = 0;
			for (let i = 0; i < dataURL.length; i++) {
				hash = ((hash << 5) - hash + dataURL.charCodeAt(i)) | 0;
			}
			return {
				canvas_hash: String(hash >>> 0),
				canvas_len:  String(dataURL.length),
				ua:          navigator.userAgent,
				platform:    navigator.platform,
				tz:          Intl.DateTimeFormat().resolvedOptions().timeZone,
			};
		})()`,
		Fields: []string{"canvas_hash", "canvas_len", "ua", "platform", "tz"},
	},
}

func main() {
	var (
		bin      = os.Getenv("CAMOUFOX_BIN")
		nFlag    = flag.Int("n", 10, "number of sessions")
		outFlag  = flag.String("out", "baseline-results.csv", "CSV output path")
		osFlag   = flag.String("os", "windows", "spoofed OS")
		timeout  = flag.Duration("timeout", 90*time.Second, "per-session timeout")
		offline  = flag.Bool("offline", false, "skip network oracles, only run client_eval")
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

	// Header.
	header := []string{"session", "seed_hi", "seed_lo", "oracle", "field", "value"}
	if err := w.Write(header); err != nil {
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
			if *offline && name != "client_eval" {
				continue
			}
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
		waitCtx, cancel := context.WithTimeout(ctx, 60*time.Second)
		defer cancel()
		_ = p.WaitForSelector(waitCtx, pr.Wait) // best-effort
		// Give async fingerprinting widgets a chance to settle.
		time.Sleep(2 * time.Second)
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
		// Strip embedded newlines so each value sits in a single CSV cell.
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
