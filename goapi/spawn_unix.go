//go:build !windows

package camoufox

import (
	"os"
	"os/exec"
)

// cmdProc adapts *exec.Cmd to browserProc on Unix.
type cmdProc struct{ cmd *exec.Cmd }

func (p cmdProc) Signal(sig os.Signal) error { return p.cmd.Process.Signal(sig) }
func (p cmdProc) Kill() error                { return p.cmd.Process.Kill() }
func (p cmdProc) Wait() error                { return p.cmd.Wait() }

// startBrowser launches the command. On Unix the child inherits the
// juggler pipe as FDs 3/4 via cmd.ExtraFiles (set by setupPipes); the
// debug flag is already reflected in cmd.Stdout/Stderr by the caller.
func startBrowser(cmd *exec.Cmd, _ bool) (browserProc, error) {
	if err := cmd.Start(); err != nil {
		return nil, err
	}
	releaseChildSide(cmd)
	return cmdProc{cmd}, nil
}
