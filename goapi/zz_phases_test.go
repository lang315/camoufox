package camoufox_test

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"testing"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
)

// newestProfile returns the most recent camoufox-profile-* dir in the temp dir.
func newestProfile() string {
	m, _ := filepath.Glob(filepath.Join(os.TempDir(), "camoufox-profile-*"))
	var best string
	var bt time.Time
	for _, d := range m {
		if st, err := os.Stat(d); err == nil && st.ModTime().After(bt) {
			best, bt = d, st.ModTime()
		}
	}
	return best
}

func snapshot(dir string) string {
	var n int
	var bytes int64
	top := map[string]bool{}
	_ = filepath.Walk(dir, func(p string, st os.FileInfo, err error) error {
		if err != nil {
			return nil
		}
		if p != dir {
			if rel, _ := filepath.Rel(dir, p); !strings.ContainsAny(rel, `/\`) {
				top[rel] = true
			}
		}
		if !st.IsDir() {
			n++
			bytes += st.Size()
		}
		return nil
	})
	var names []string
	for k := range top {
		names = append(names, k)
	}
	sort.Strings(names)
	return fmt.Sprintf("files=%d bytes=%d top=%s", n, bytes, strings.Join(names, ","))
}

func deltas(marks []camoufox.ZZMark, t0 time.Time) string {
	var sb strings.Builder
	prev := t0
	for _, m := range marks {
		fmt.Fprintf(&sb, " %s=%.2f", m.Label, m.At.Sub(prev).Seconds())
		prev = m.At
	}
	return sb.String()
}

func TestZZPhases(t *testing.T) {
	bin := browserBinary(t)
	reused := t.TempDir()
	for i := 0; i < 36; i++ {
		arm := "fresh"
		opts := []camoufox.Option{camoufox.WithExecutablePath(bin), camoufox.WithHeadless(true)}
		if i >= 24 {
			arm = "reused"
			opts = append(opts, camoufox.WithUserDataDir(reused))
		}
		camoufox.ZZTake()
		logBase := filepath.Join(t.TempDir(), "moz.log")
		if os.Getenv("ZZ_MOZLOG") == "1" {
			opts = append(opts, camoufox.WithEnv(append(os.Environ(),
				"MOZ_LOG=timestamp,sync,nsHttp:3,nsSocketTransport:3,nsHostResolver:3", "MOZ_LOG_FILE="+logBase)...))
		}
		ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
		t0 := time.Now()
		b, err := camoufox.Launch(ctx, opts...)
		if err != nil {
			t.Fatal(err)
		}
		t1 := time.Now()
		bc, err := b.NewContext(ctx)
		if err != nil {
			t.Fatal(err)
		}
		t2 := time.Now()
		p, err := bc.NewPage(ctx)
		if err != nil {
			t.Fatal(err)
		}
		t3 := time.Now()
		plat, _ := p.Evaluate(ctx, "navigator.platform")
		var ctlSrv *httptest.Server
		if os.Getenv("ZZ_MOZLOG") == "1" && i == 0 {
			ctlSrv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = w.Write([]byte("zz-control")) }))
			if err := p.Goto(ctx, ctlSrv.URL+"/zz-control-path"); err != nil {
				t.Logf("CONTROL goto error: %v", err)
			}
			time.Sleep(500 * time.Millisecond)
		}
		dir := reused
		if arm == "fresh" {
			dir = newestProfile()
		}
		cpu := cpuSecs()
		snap := snapshot(dir)
		marks := camoufox.ZZTake()
		_ = p.Close(ctx)
		b.Close()
		t.Logf("PHASES moz=%s %s#%d platform=%v launch=%.1f context=%.1f newpage=%.1f stages:%s | profile(after newpage) %s",
			os.Getenv("ZZ_MOZLOG"), arm, i, plat, t1.Sub(t0).Seconds(), t2.Sub(t1).Seconds(), t3.Sub(t2).Seconds(), deltas(marks, t0), snap)
		t.Logf("NET moz=%s %s#%d wall=%.1fs cpu_sum=%.1fs %s", os.Getenv("ZZ_MOZLOG"), arm, i, t3.Sub(t0).Seconds(), cpu, netSummary(logBase))
		if ctlSrv != nil {
			// The arm is void unless the browser's own request to this local server appears in the log.
			found := strings.Contains(readLogs(logBase), "zz-control-path")
			t.Logf("CONTROL moz positive: request to local http server in log = %v (false = the MOZ_LOG arm is VOID)", found)
			ctlSrv.Close()
		}
		cancel()
	}
}

var hostRe = regexp.MustCompile(`https?://([A-Za-z0-9.\-]+)`)

// cpuSecs sums the CPU time of every camoufox process.
func cpuSecs() float64 {
	if runtime.GOOS == "windows" {
		out, _ := exec.Command("powershell", "-NoProfile", "-Command",
			"(Get-Process camoufox -ErrorAction SilentlyContinue | Measure-Object CPU -Sum).Sum").Output()
		v, _ := strconv.ParseFloat(strings.TrimSpace(string(out)), 64)
		return v
	}
	out, _ := exec.Command("sh", "-c", "ps -A -o time=,comm= | grep -i camoufox").Output()
	var tot float64
	for _, l := range strings.Split(string(out), "\n") {
		f := strings.Fields(l)
		if len(f) == 0 {
			continue
		}
		var secs float64
		for _, part := range strings.Split(f[0], ":") {
			v, _ := strconv.ParseFloat(part, 64)
			secs = secs*60 + v
		}
		tot += secs
	}
	return tot
}

// netSummary reads the MOZ_LOG files of one launch.
func netSummary(base string) string {
	files, _ := filepath.Glob(base + "*")
	hosts := map[string]int{}
	lines := 0
	for _, f := range files {
		b, _ := os.ReadFile(f)
		for _, l := range strings.Split(string(b), "\n") {
			lines++
			for _, m := range hostRe.FindAllStringSubmatch(l, -1) {
				hosts[m[1]]++
			}
		}
	}
	var hs []string
	for h, n := range hosts {
		hs = append(hs, fmt.Sprintf("%s:%d", h, n))
	}
	sort.Strings(hs)
	if len(hs) > 8 {
		hs = hs[:8]
	}
	return fmt.Sprintf("logfiles=%d lines=%d hosts=%d [%s]", len(files), lines, len(hosts), strings.Join(hs, " "))
}

func readLogs(base string) string {
	files, _ := filepath.Glob(base + "*")
	var sb strings.Builder
	for _, f := range files {
		b, _ := os.ReadFile(f)
		sb.Write(b)
	}
	return sb.String()
}

// TestZZProfile takes a Gecko startup profile of each of 8 cold launches.
func TestZZProfile(t *testing.T) {
	dir := os.Getenv("ZZ_PROF_DIR")
	if dir == "" {
		t.Skip("probe only: ZZ_PROF_DIR unset")
	}
	_ = os.MkdirAll(dir, 0o755)
	bin := browserBinary(t)
	var rows []string
	for i := 0; i < 8; i++ {
		out := filepath.Join(dir, fmt.Sprintf("prof-%d.json", i))
		env := append(os.Environ(),
			"MOZ_PROFILER_STARTUP=1", "MOZ_PROFILER_STARTUP_FEATURES=js,stackwalk,cpu",
			"MOZ_PROFILER_STARTUP_FILTERS=*", "MOZ_PROFILER_SHUTDOWN="+out)
		ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
		t0 := time.Now()
		b, err := camoufox.Launch(ctx, camoufox.WithExecutablePath(bin), camoufox.WithHeadless(true), camoufox.WithEnv(env...))
		if err != nil {
			t.Fatal(err)
		}
		t1 := time.Now()
		bc, _ := b.NewContext(ctx)
		p, err := bc.NewPage(ctx)
		if err != nil {
			t.Fatal(err)
		}
		t2 := time.Now()
		plat, _ := p.Evaluate(ctx, "navigator.platform")
		_ = p.Close(ctx)
		b.Close()
		time.Sleep(3 * time.Second)
		st, _ := os.Stat(out)
		size := int64(-1)
		if st != nil {
			size = st.Size()
		}
		row := fmt.Sprintf("PROF prof-%d platform=%v launch=%.1fs newpage=%.1fs profile_bytes=%d", i, plat, t1.Sub(t0).Seconds(), t2.Sub(t1).Seconds(), size)
		rows = append(rows, row)
		t.Log(row)
		cancel()
	}
	_ = os.WriteFile(filepath.Join(dir, "timings.txt"), []byte(strings.Join(rows, "\n")+"\n"), 0o644)
}

// TestZZPinned launches cold browsers with the identity's OS pinned, interleaved.
func TestZZPinned(t *testing.T) {
	bin := browserBinary(t)
	oses := []string{"windows", "linux", "macos"}
	for round := 0; round < 8; round++ {
		for _, o := range oses {
			ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
			t0 := time.Now()
			b, err := camoufox.Launch(ctx, camoufox.WithExecutablePath(bin), camoufox.WithHeadless(true), camoufox.WithOS(o))
			if err != nil {
				t.Fatal(err)
			}
			t1 := time.Now()
			bc, _ := b.NewContext(ctx)
			p, err := bc.NewPage(ctx)
			if err != nil {
				t.Fatal(err)
			}
			t2 := time.Now()
			plat, _ := p.Evaluate(ctx, "navigator.platform")
			cpu := cpuSecs()
			_ = p.Close(ctx)
			b.Close()
			t.Logf("PINNED os=%s round=%d platform=%v launch=%.1fs newpage=%.1fs cpu_sum=%.1fs", o, round, plat, t1.Sub(t0).Seconds(), t2.Sub(t1).Seconds(), cpu)
			cancel()
		}
	}
}
