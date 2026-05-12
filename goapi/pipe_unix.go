//go:build !windows

package camoufox

import (
	"fmt"
	"os"
	"os/exec"
)

// setupPipes opens two pipes and binds the child halves to FDs 3
// (browser-read) and 4 (browser-write) via cmd.ExtraFiles. Returns
// the parent halves: parentRead reads what the browser writes;
// parentWrite writes what the browser reads.
//
// closeParent is invoked by Pipe.Close to release the parent ends
// after the browser has drained them.
func setupPipes(cmd *exec.Cmd) (parentRead, parentWrite *os.File, closeParent func() error, err error) {
	parentToChildR, parentToChildW, err := os.Pipe()
	if err != nil {
		return nil, nil, nil, fmt.Errorf("camoufox: pipe(child-read): %w", err)
	}
	childToParentR, childToParentW, err := os.Pipe()
	if err != nil {
		parentToChildR.Close()
		parentToChildW.Close()
		return nil, nil, nil, fmt.Errorf("camoufox: pipe(child-write): %w", err)
	}
	// Indices map to child FDs 3 and 4.
	cmd.ExtraFiles = []*os.File{parentToChildR, childToParentW}
	closeChildSide := func() {
		parentToChildR.Close()
		childToParentW.Close()
	}
	closer := func() error {
		childToParentR.Close()
		parentToChildW.Close()
		return nil
	}
	// The caller starts the command; after Start the child duplicates
	// the inherited fds and we release ours via closeChildSide.
	// We return closeChildSide indirectly through closer by closing
	// child halves at returnsite; Launch arranges this explicitly.
	_ = closeChildSide
	return childToParentR, parentToChildW, closer, nil
}

// releaseChildSide on POSIX is performed inline by Launch after the
// browser process is started — there is no Windows-specific work to
// match here.
func releaseChildSide(cmd *exec.Cmd) {
	for _, f := range cmd.ExtraFiles {
		f.Close()
	}
	cmd.ExtraFiles = nil
}
