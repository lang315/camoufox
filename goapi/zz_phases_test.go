package camoufox_test

import (
	"context"
	"testing"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
)

func TestZZPhases(t *testing.T) {
	bin := browserBinary(t)
	for i := 0; i < 12; i++ {
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
		t.Logf("PHASES cold#%d launch=%.1fs context=%.1fs newpage=%.1fs", i, t1.Sub(t0).Seconds(), t2.Sub(t1).Seconds(), t3.Sub(t2).Seconds())
		_ = p.Close(ctx)
		b.Close()
		cancel()
	}
	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
	defer cancel()
	b, err := camoufox.Launch(ctx, camoufox.WithExecutablePath(bin), camoufox.WithHeadless(true))
	if err != nil {
		t.Fatal(err)
	}
	defer b.Close()
	for i := 0; i < 12; i++ {
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
		t.Logf("PHASES shared#%d context=%.1fs newpage=%.1fs", i, t2.Sub(t1).Seconds(), time.Since(t2).Seconds())
		_ = p.Close(ctx)
	}
}
