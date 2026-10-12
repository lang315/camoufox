package camoufox

import (
	"context"
	"sync/atomic"
	"testing"
	"time"
)

// #166: Goto gave up after a fixed 2 s while a loaded browser attached the
// main frame after ~7 s (context 11 of 50, Windows).
func TestWaitMainFrame(t *testing.T) {
	var frame atomic.Value
	frame.Store("")
	get := func() string { return frame.Load().(string) }
	go func() { time.Sleep(300 * time.Millisecond); frame.Store("f1") }()
	if f, err := waitMainFrame(context.Background(), get, 5*time.Second); err != nil || f != "f1" {
		t.Fatalf("late frame: got %q, %v", f, err)
	}
	frame.Store("")
	if _, err := waitMainFrame(context.Background(), get, 100*time.Millisecond); err == nil {
		t.Fatal("no frame: want a timeout error")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := waitMainFrame(ctx, get, time.Second); err != context.Canceled {
		t.Fatalf("cancelled: got %v, want context.Canceled", err)
	}
}
