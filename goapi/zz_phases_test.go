package camoufox_test

import (
	"context"
	"os/exec"
	"runtime"
	"strings"
	"testing"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
)

func alive() int {
	var out []byte
	if runtime.GOOS == "windows" {
		out, _ = exec.Command("tasklist", "/FI", "IMAGENAME eq camoufox.exe", "/NH").Output()
		n := 0
		for _, l := range strings.Split(string(out), "\n") {
			if strings.Contains(l, "camoufox.exe") {
				n++
			}
		}
		return n
	}
	out, _ = exec.Command("pgrep", "-fc", "camoufox").Output()
	n := 0
	for _, c := range strings.TrimSpace(string(out)) {
		n = n*10 + int(c-'0')
	}
	return n
}

func TestZZPhases(t *testing.T) {
	bin := browserBinary(t)
	for i := 0; i < 24; i++ {
		waitMode := i >= 12
		var waited float64
		if waitMode {
			w0 := time.Now()
			for alive() > 0 && time.Since(w0) < 60*time.Second {
				time.Sleep(200 * time.Millisecond)
			}
			waited = time.Since(w0).Seconds()
		}
		before := alive()
		ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
		t0 := time.Now()
		b, err := camoufox.Launch(ctx, camoufox.WithExecutablePath(bin), camoufox.WithHeadless(true))
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
		_ = p.Close(ctx)
		c0 := time.Now()
		b.Close()
		closeDur := time.Since(c0).Seconds()
		after := alive()
		t.Logf("PHASES cold#%d wait=%v waited=%.1fs procs_before=%d launch=%.1fs context=%.1fs newpage=%.1fs close=%.1fs procs_after_close=%d",
			i, waitMode, waited, before, t1.Sub(t0).Seconds(), t2.Sub(t1).Seconds(), t3.Sub(t2).Seconds(), closeDur, after)
		cancel()
	}
}
