package camoufox

import (
	"context"
	"testing"
	"time"
)

// #166: a fresh page announces executionContextsCleared before its first
// executionContextCreated. Clearing swapped contextReadyCh for a new channel
// while a waiter still held the old one, so the created event closed a
// channel nobody was waiting on and every NewPage sat out its timeout.
func TestContextWaiterSurvivesClearBeforeCreate(t *testing.T) {
	h := newGotoHarness(t)
	h.page.subscribe()
	done := make(chan error, 1)
	go func() {
		_, err := h.page.awaitMainContext(context.Background(), 2*time.Second)
		done <- err
	}()
	time.Sleep(50 * time.Millisecond)
	h.send(`{"method":"Runtime.executionContextsCleared","sessionId":"s1","params":{}}`)
	h.send(`{"method":"Runtime.executionContextCreated","sessionId":"s1","params":{"executionContextId":"id-1","auxData":{"frameId":"f1","name":""}}}`)
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("waiter: %v", err)
		}
	case <-time.After(time.Second):
		t.Fatal("waiter missed the context created after a clear")
	}
}
