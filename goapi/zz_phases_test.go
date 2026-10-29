package camoufox_test

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"sort"
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
		dir := reused
		if arm == "fresh" {
			dir = newestProfile()
		}
		snap := snapshot(dir)
		marks := camoufox.ZZTake()
		_ = p.Close(ctx)
		b.Close()
		t.Logf("PHASES %s#%d launch=%.1f context=%.1f newpage=%.1f stages:%s | profile(after newpage) %s",
			arm, i, t1.Sub(t0).Seconds(), t2.Sub(t1).Seconds(), t3.Sub(t2).Seconds(), deltas(marks, t0), snap)
		cancel()
	}
}
