package camoufox

import "os"

// browserProc is the minimal process control that Browser.Close needs.
// It is satisfied by an *exec.Cmd wrapper on Unix and by a raw
// CreateProcessW handle on Windows (see spawn_unix.go / pipe_windows.go).
type browserProc interface {
	Signal(os.Signal) error
	Kill() error
	Wait() error
}
