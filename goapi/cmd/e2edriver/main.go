// Command e2edriver exposes goapi's public API over JSON lines on stdin and
// stdout, so the Python end-to-end suite (e2e/) can run its journeys through
// goapi as well as through the Python package. One request per line:
//
//	{"id":1,"op":"page.goto","h":"p3","args":{"url":"http://..."}}
//
// and one reply per line: {"id":1,"result":...} or {"id":1,"error":"..."}.
package main

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"sync"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
	"github.com/lang315/camoufox/goapi/pkg/proxy"
)

type request struct {
	ID   int             `json:"id"`
	Op   string          `json:"op"`
	H    string          `json:"h"`
	Args json.RawMessage `json:"args"`
}

type reply struct {
	ID     int    `json:"id"`
	Result any    `json:"result,omitempty"`
	Error  string `json:"error,omitempty"`
}

type args struct {
	Binary   string         `json:"binary"`
	OS       string         `json:"os"`
	Headless bool           `json:"headless"`
	Proxy    *proxy.Proxy   `json:"proxy"`
	Prefs    map[string]any `json:"prefs"`
	URL      string         `json:"url"`
	JS       string         `json:"js"`
	Sel      string         `json:"sel"`
	Text     string         `json:"text"`
	Path     string         `json:"path"`
	Ctx      string         `json:"ctx"`
	Prompt   string         `json:"prompt"`
}

type state struct {
	mu   sync.Mutex
	n    int
	objs map[string]any
}

func (s *state) put(prefix string, v any) string {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.n++
	h := fmt.Sprintf("%s%d", prefix, s.n)
	s.objs[h] = v
	return h
}

func (s *state) get(h string) any {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.objs[h]
}

func main() {
	st := &state{objs: map[string]any{}}
	in := bufio.NewScanner(os.Stdin)
	in.Buffer(make([]byte, 1<<20), 1<<26)
	out := json.NewEncoder(os.Stdout)
	for in.Scan() {
		var r request
		if err := json.Unmarshal(in.Bytes(), &r); err != nil {
			_ = out.Encode(reply{Error: err.Error()})
			continue
		}
		ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
		res, err := st.do(ctx, r)
		cancel()
		rep := reply{ID: r.ID, Result: res}
		if err != nil {
			rep.Error = err.Error()
		}
		_ = out.Encode(rep)
	}
}

// handle returns the object behind h as T, or an error naming the handle (a
// restarted driver has none of the old ones).
func handle[T any](s *state, h string) (T, error) {
	v, ok := s.get(h).(T)
	if !ok {
		var zero T
		return zero, fmt.Errorf("no %T handle %q", zero, h)
	}
	return v, nil
}

func (s *state) page(h string) (*camoufox.Page, error) {
	p, ok := s.get(h).(*camoufox.Page)
	if !ok {
		return nil, fmt.Errorf("no page %q", h)
	}
	return p, nil
}

func (s *state) do(ctx context.Context, r request) (any, error) {
	var a args
	if len(r.Args) > 0 {
		if err := json.Unmarshal(r.Args, &a); err != nil {
			return nil, err
		}
	}
	switch r.Op {
	case "launch":
		opts := []camoufox.Option{camoufox.WithExecutablePath(a.Binary), camoufox.WithHeadless(a.Headless)}
		if a.OS != "" {
			opts = append(opts, camoufox.WithOS(a.OS))
		}
		if a.Proxy != nil {
			opts = append(opts, camoufox.WithProxy(*a.Proxy))
		}
		for k, v := range a.Prefs {
			opts = append(opts, camoufox.WithFirefoxUserPref(k, v))
		}
		// Launch ties the browser process to its context, so it must outlive this request.
		b, err := camoufox.Launch(context.Background(), opts...)
		if err != nil {
			return nil, err
		}
		return s.put("b", b), nil
	case "browser.close":
		b, err := handle[*camoufox.Browser](s, r.H)
		if err != nil {
			return nil, err
		}
		return nil, b.Close()
	case "browser.new_context":
		b, err := handle[*camoufox.Browser](s, r.H)
		if err != nil {
			return nil, err
		}
		c, err := b.NewContext(ctx)
		if err != nil {
			return nil, err
		}
		return s.put("c", c), nil
	case "ctx.new_page":
		bc, err := handle[*camoufox.BrowserContext](s, r.H)
		if err != nil {
			return nil, err
		}
		p, err := bc.NewPage(ctx)
		if err != nil {
			return nil, err
		}
		return s.put("p", p), nil
	case "ctx.cookies", "ctx.close":
		bc, err := handle[*camoufox.BrowserContext](s, r.H)
		if err != nil {
			return nil, err
		}
		if r.Op == "ctx.cookies" {
			return bc.Cookies(ctx)
		}
		return nil, bc.Close(ctx)
	}

	p, err := s.page(r.H)
	if err != nil {
		return nil, err
	}
	switch r.Op {
	case "page.goto":
		return nil, p.Goto(ctx, a.URL)
	case "page.eval":
		return p.Evaluate(ctx, a.JS)
	case "page.click":
		return nil, p.Click(ctx, a.Sel)
	case "page.type":
		return nil, p.Type(ctx, a.Sel, a.Text)
	case "page.hover", "page.upload":
		el, err := p.QuerySelector(ctx, a.Sel)
		if err != nil {
			return nil, err
		}
		if el == nil {
			return nil, fmt.Errorf("no element %q", a.Sel)
		}
		if r.Op == "page.hover" {
			return nil, el.Hover(ctx)
		}
		return nil, el.SetInputFiles(ctx, []string{a.Path})
	case "page.download":
		bc, err := handle[*camoufox.BrowserContext](s, a.Ctx)
		if err != nil {
			return nil, err
		}
		dir, err := os.MkdirTemp("", "e2e-download")
		if err != nil {
			return nil, err
		}
		if err := bc.SetDownloadOptions(ctx, camoufox.DownloadOptions{Behavior: "saveToDisk", DownloadsDir: dir}); err != nil {
			return nil, err
		}
		got := make(chan *camoufox.Download, 1)
		// ponytail: the subscription is never removed; one per download call is fine for a test driver.
		bc.OnDownload(func(d *camoufox.Download) {
			select {
			case got <- d:
			default:
			}
		})
		if err := p.Click(ctx, a.Sel); err != nil {
			return nil, err
		}
		select {
		case d := <-got:
			if err := d.Wait(ctx); err != nil {
				return nil, err
			}
			return os.ReadFile(d.Path()) // []byte encodes as base64
		case <-ctx.Done():
			return nil, fmt.Errorf("no download started: %w", ctx.Err())
		}
	case "page.on_dialog":
		prompt := a.Prompt
		p.OnDialog(func(d *camoufox.Dialog) {
			// Answer off the event goroutine: Accept is itself a protocol call.
			go func() {
				text := ""
				if d.Type == "prompt" {
					text = prompt
				}
				_ = d.Accept(context.Background(), text)
			}()
		})
		return nil, nil
	}
	return nil, fmt.Errorf("unknown op %q", r.Op)
}
