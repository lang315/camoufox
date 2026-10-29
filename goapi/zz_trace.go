package camoufox

import (
	"sync"
	"time"
)

type ZZMark struct {
	Label string
	At    time.Time
}

var (
	zzMu    sync.Mutex
	zzMarks []ZZMark
)

func zzMark(l string) {
	zzMu.Lock()
	zzMarks = append(zzMarks, ZZMark{l, time.Now()})
	zzMu.Unlock()
}

// ZZTake returns and clears the marks.
func ZZTake() []ZZMark {
	zzMu.Lock()
	defer zzMu.Unlock()
	m := zzMarks
	zzMarks = nil
	return m
}
