// Deep detection-site harness.
//
// Drives Camoufox against the strongest public fingerprint / anti-bot
// oracles (Pixelscan, CreepJS, BrowserLeaks, Cover Your Tracks,
// Fingerprint, IPhey) and records a screenshot + extracted verdict per
// oracle. Screenshots are the primary evidence; the CSV fields are
// best-effort (these are SPAs whose markup shifts).
//
// Run:
//   CAMOUFOX_BIN=/path/to/camoufox CF_OS=windows ./deepcheck -n 2
// Env: CF_OS (windows|macos|linux), CF_DISPLAY (Xvfb), CF_PROXY.
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
	"github.com/lang315/camoufox/goapi/pkg/proxy"
)

type probe struct {
	Name        string
	URL         string
	Wait        string        // optional selector to wait for
	ClickJS     string        // optional JS to run before settling (e.g. a button click)
	Settle      time.Duration
	GotoTimeout time.Duration // navigation timeout (default 60s)
	Extract     string        // JS returning an object
	Fields      []string
	// Verdict maps extracted fields to PASS / PARTIAL / FLAG.
	Verdict func(map[string]string) string
}

func has(s, sub string) bool { return strings.Contains(strings.ToLower(s), sub) }

var probes = []probe{
	{
		Name: "pixelscan", URL: "https://pixelscan.net/", Settle: 24 * time.Second,
		Extract: `(() => { const t=(document.body.innerText||'').toLowerCase();
			return { inconsistent: t.includes('inconsistent')?'yes':'no',
			  automation: (t.includes('automation')||t.includes('webdriver')||t.includes('headless'))?'FLAG':'clean',
			  masking: (t.includes('masking')||t.includes('do not mask')||t.includes('is being spoofed'))?'FLAG':'clean',
			  snippet: (document.body.innerText||'').replace(/\s+/g,' ').slice(0,400) }; })()`,
		Fields: []string{"inconsistent", "automation", "masking", "snippet"},
		Verdict: func(m map[string]string) string {
			if m["automation"] == "FLAG" {
				return "FLAG"
			}
			if m["inconsistent"] == "yes" || m["masking"] == "FLAG" {
				return "PARTIAL"
			}
			return "PASS"
		},
	},
	{
		Name: "creepjs", URL: "https://abrahamjuliot.github.io/creepjs/", Settle: 55 * time.Second,
		Extract: `(() => { const t=document.body.innerText||'';
			const hp=(t.match(/(\d+)%\s*headless/i)||[])[1]||'?';
			return { headless_pct: hp,
			  chromium: /chromium:\s*false/i.test(t)?'false':(/chromium:\s*true/i.test(t)?'true':'?'),
			  lies: (t.match(/(\d+)\s*lies/i)||[])[1]||'?',
			  platform_hints: ((t.match(/platform hints:\s*([^\n]+)/i)||[])[1]||'').trim(),
			  ua: navigator.userAgent, platform: navigator.platform,
			  tz: Intl.DateTimeFormat().resolvedOptions().timeZone }; })()`,
		Fields: []string{"headless_pct", "chromium", "lies", "platform_hints", "ua", "platform", "tz"},
		Verdict: func(m map[string]string) string {
			if m["headless_pct"] == "0" && m["chromium"] == "false" {
				return "PASS"
			}
			if m["chromium"] == "true" {
				return "FLAG"
			}
			return "PARTIAL"
		},
	},
	{
		Name: "browserleaks_webrtc", URL: "https://browserleaks.com/webrtc", Settle: 6 * time.Second,
		Extract: `(() => { const t=document.body.innerText||'';
			return { private_ip_leak: /(\b10\.\d|\b192\.168\.|\b172\.(1[6-9]|2\d|3[01])\.)/.test(t)?'LEAK':'none',
			  public: (t.match(/\b\d{1,3}(?:\.\d{1,3}){3}\b/)||[])[0]||'' }; })()`,
		Fields: []string{"private_ip_leak", "public"},
		Verdict: func(m map[string]string) string {
			if m["private_ip_leak"] == "LEAK" {
				return "FLAG"
			}
			return "PASS"
		},
	},
	{
		Name: "browserleaks_canvas", URL: "https://browserleaks.com/canvas", Wait: "table", Settle: 5 * time.Second,
		Extract: `(() => { const t=document.body.innerText||'';
			return { signature: (t.match(/Signature[\s:]+([0-9a-fA-F]{6,})/)||[])[1]||'',
			  uniqueness: ((t.match(/Uniqueness[\s:]+([^\n]+)/)||[])[1]||'').trim().slice(0,80) }; })()`,
		Fields: []string{"signature", "uniqueness"},
		Verdict: func(m map[string]string) string {
			if m["signature"] != "" {
				return "PASS"
			}
			return "PARTIAL"
		},
	},
	{
		Name: "browserleaks_webgl", URL: "https://browserleaks.com/webgl", Wait: "table", Settle: 5 * time.Second,
		Extract: `(() => { const out={unmasked_vendor:'',unmasked_renderer:''};
			for(const r of document.querySelectorAll('tr')){const c=r.querySelectorAll('td');
			  if(c.length<2)continue; const k=c[0].textContent.trim().toLowerCase();
			  if(k.includes('unmasked vendor'))out.unmasked_vendor=c[1].textContent.trim().slice(0,120);
			  if(k.includes('unmasked renderer'))out.unmasked_renderer=c[1].textContent.trim().slice(0,120);}
			return out; })()`,
		Fields: []string{"unmasked_vendor", "unmasked_renderer"},
		Verdict: func(m map[string]string) string {
			if m["unmasked_renderer"] != "" && !has(m["unmasked_renderer"], "no webgl") {
				return "PASS"
			}
			return "FLAG"
		},
	},
	{
		Name: "browserleaks_fonts", URL: "https://browserleaks.com/fonts", Settle: 5 * time.Second,
		Extract: `(() => { const t=document.body.innerText||'';
			return { font_count:(t.match(/([0-9]+)\s+fonts?/i)||[])[1]||'',
			  snippet:t.replace(/\s+/g,' ').slice(0,160) }; })()`,
		Fields: []string{"font_count", "snippet"},
		Verdict: func(m map[string]string) string {
			if m["font_count"] != "" {
				return "PASS"
			}
			return "PARTIAL"
		},
	},
	{
		Name: "browserleaks_ip", URL: "https://browserleaks.com/ip", Settle: 4 * time.Second,
		Extract: `(() => ({ ip:((document.body.innerText||'').match(/\b\d{1,3}(?:\.\d{1,3}){3}\b/)||[])[0]||'' }))()`,
		Fields:  []string{"ip"},
		Verdict: func(m map[string]string) string {
			if m["ip"] != "" {
				return "INFO"
			}
			return "PARTIAL"
		},
	},
	{
		Name: "coveryourtracks", URL: "https://coveryourtracks.eff.org/", Settle: 25 * time.Second, GotoTimeout: 90 * time.Second,
		ClickJS: `(()=>{const b=[...document.querySelectorAll('a,button')].find(e=>/test your browser/i.test(e.textContent)); if(b) b.click();})()`,
		Extract: `(() => { const t=document.body.innerText||'';
			return { verdict:((t.match(/(randomized fingerprint|unique fingerprint|nearly unique|no protection|partial protection|strong protection)/i)||[])[0]||''),
			  bits:(t.match(/([0-9.]+)\s*bits of identifying/i)||[])[1]||'',
			  oneinx:(t.match(/one in ([0-9.,x]+)/i)||[])[1]||'' }; })()`,
		Fields: []string{"verdict", "bits", "oneinx"},
		Verdict: func(m map[string]string) string {
			if has(m["verdict"], "randomized") {
				return "PASS"
			}
			if m["verdict"] != "" {
				return "PARTIAL"
			}
			return "PARTIAL"
		},
	},
	{
		Name: "fingerprint", URL: "https://demo.fingerprint.com/", Settle: 14 * time.Second,
		Extract: `(() => { const t=(document.body.innerText||'').toLowerCase();
			// Only treat as a real detection when the live demo prints an explicit
			// verdict — not the marketing phrase "detect bots".
			const detected = t.includes('automation tool detected')||t.includes('you are a bot')||t.includes('bot detected: yes');
			const clean = t.includes('not a bot')||t.includes('no bot detected')||t.includes('you are human')||t.includes('good, you');
			return { bot: detected?'DETECTED':(clean?'not detected':'?'),
			  snippet:(document.body.innerText||'').replace(/\s+/g,' ').slice(0,300) }; })()`,
		Fields: []string{"bot", "snippet"},
		Verdict: func(m map[string]string) string {
			switch m["bot"] {
			case "DETECTED":
				return "FLAG"
			case "not detected":
				return "PASS"
			}
			return "PARTIAL" // demo needs interaction; rely on the screenshot
		},
	},
	{
		Name: "iphey", URL: "https://iphey.com/", Settle: 35 * time.Second,
		Extract: `(() => { const t=document.body.innerText||'';
			return { overall:(t.match(/\b(Trustworthy|Suspicious)\b/i)||[])[0]||'',
			  snippet:t.replace(/\s+/g,' ').slice(0,300) }; })()`,
		Fields: []string{"overall", "snippet"},
		Verdict: func(m map[string]string) string {
			if strings.EqualFold(m["overall"], "Trustworthy") {
				return "PASS"
			}
			if strings.EqualFold(m["overall"], "Suspicious") {
				return "PARTIAL" // expected without a matched proxy
			}
			return "PARTIAL"
		},
	},
}

func main() {
	var (
		bin     = os.Getenv("CAMOUFOX_BIN")
		nFlag   = flag.Int("n", 2, "sessions")
		outFlag = flag.String("out", "deepcheck.csv", "CSV output path")
		shotDir = flag.String("shots", ".", "screenshot directory")
		timeout = flag.Duration("timeout", 8*time.Minute, "per-session timeout")
	)
	flag.Parse()
	if bin == "" {
		log.Fatal("set CAMOUFOX_BIN")
	}
	targetOS := os.Getenv("CF_OS")
	if targetOS == "" {
		targetOS = "windows"
	}

	out, err := os.Create(*outFlag)
	if err != nil {
		log.Fatal(err)
	}
	defer out.Close()
	w := csv.NewWriter(out)
	defer w.Flush()
	w.Write([]string{"session", "oracle", "verdict", "field", "value"})

	for s := 0; s < *nFlag; s++ {
		hi, lo := randSeed()
		log.Printf("session %d/%d (os=%s)", s+1, *nFlag, targetOS)
		rng := mathrand.New(mathrand.NewPCG(hi, lo))

		ctx, cancel := context.WithTimeout(context.Background(), *timeout)
		opts := []camoufox.Option{
			camoufox.WithExecutablePath(bin),
			camoufox.WithOS(targetOS),
			camoufox.WithRand(rng),
		}
		if disp := os.Getenv("CF_DISPLAY"); disp != "" {
			opts = append(opts, camoufox.WithVirtualDisplay(disp),
				camoufox.WithFirefoxUserPref("webgl.force-enabled", true))
		} else {
			opts = append(opts, camoufox.WithHeadless(true))
		}
		if px := os.Getenv("CF_PROXY"); px != "" {
			opts = append(opts, camoufox.WithProxy(proxy.Proxy{Server: px}), camoufox.WithGeoIP(true))
		}
		b, err := camoufox.Launch(ctx, opts...)
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

		for _, pr := range probes {
			m, err := runProbe(ctx, p, pr)
			verdict := "ERROR"
			if err != nil {
				log.Printf("  %-20s ERROR: %v", pr.Name, err)
			} else {
				verdict = pr.Verdict(m)
				log.Printf("  %-20s %s", pr.Name, verdict)
			}
			// screenshot regardless (even on extract error the page rendered)
			if png, serr := p.Screenshot(ctx, camoufox.Clip{Width: 1280, Height: 1600}); serr == nil {
				_ = os.WriteFile(fmt.Sprintf("%s/deepcheck-%s-%d-%s.png", *shotDir, targetOS, s, pr.Name), png, 0644)
			}
			for _, f := range pr.Fields {
				w.Write([]string{fmt.Sprintf("%d", s), pr.Name, verdict, f, m[f]})
			}
			w.Flush()
		}
		b.Close()
		cancel()
	}
	log.Printf("done → %s (+ screenshots in %s)", *outFlag, *shotDir)
}

func runProbe(ctx context.Context, p *camoufox.Page, pr probe) (map[string]string, error) {
	gotoTimeout := pr.GotoTimeout
	if gotoTimeout == 0 {
		gotoTimeout = 60 * time.Second
	}
	gctx, gcancel := context.WithTimeout(ctx, gotoTimeout+10*time.Second)
	defer gcancel()
	if err := p.Goto(gctx, pr.URL, camoufox.GotoOptions{WaitUntil: camoufox.WaitUntilDOMContentLoaded, Timeout: gotoTimeout}); err != nil {
		return nil, fmt.Errorf("goto: %w", err)
	}
	if pr.Wait != "" {
		wctx, wcancel := context.WithTimeout(ctx, 30*time.Second)
		_, _ = p.WaitFor(wctx, pr.Wait, camoufox.WaitForOptions{State: camoufox.WaitAttached})
		wcancel()
	}
	if pr.ClickJS != "" {
		_, _ = p.Evaluate(ctx, pr.ClickJS)
	}
	if pr.Settle > 0 {
		time.Sleep(pr.Settle)
	}
	v, err := p.Evaluate(ctx, pr.Extract)
	if err != nil {
		return map[string]string{}, fmt.Errorf("eval: %w", err)
	}
	out := map[string]string{}
	if mp, ok := v.(map[string]any); ok {
		for k, val := range mp {
			out[k] = strings.ReplaceAll(strings.ReplaceAll(fmt.Sprintf("%v", val), "\n", " "), "\r", " ")
		}
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
