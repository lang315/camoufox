//go:build windows

package camoufox

import (
	"fmt"
	"os"
	"os/exec"
	"syscall"
)

// setupPipes wires the Camoufox pipe transport on Windows. The C++
// reader in nsRemoteDebuggingPipe.cpp expects the child HANDLE values
// via PW_PIPE_READ / PW_PIPE_WRITE environment variables (decimal
// integer cast back to HANDLE). The handles must be marked
// inheritable so CreateProcess can hand them to the child.
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
	// Tag the child-side handles inheritable.
	for _, h := range []syscall.Handle{syscall.Handle(parentToChildR.Fd()), syscall.Handle(childToParentW.Fd())} {
		if err := syscall.SetHandleInformation(h, syscall.HANDLE_FLAG_INHERIT, syscall.HANDLE_FLAG_INHERIT); err != nil {
			parentToChildR.Close()
			parentToChildW.Close()
			childToParentR.Close()
			childToParentW.Close()
			return nil, nil, nil, fmt.Errorf("camoufox: SetHandleInformation: %w", err)
		}
	}

	sys := cmd.SysProcAttr
	if sys == nil {
		sys = &syscall.SysProcAttr{}
		cmd.SysProcAttr = sys
	}
	sys.AdditionalInheritedHandles = append(sys.AdditionalInheritedHandles,
		syscall.Handle(parentToChildR.Fd()),
		syscall.Handle(childToParentW.Fd()),
	)
	cmd.Env = append(cmd.Env,
		fmt.Sprintf("PW_PIPE_READ=%d", parentToChildR.Fd()),
		fmt.Sprintf("PW_PIPE_WRITE=%d", childToParentW.Fd()),
	)
	// Stash child-side files on the cmd so releaseChildSide can close
	// them after Start.
	cmd.ExtraFiles = []*os.File{parentToChildR, childToParentW}

	closer := func() error {
		childToParentR.Close()
		parentToChildW.Close()
		return nil
	}
	return childToParentR, parentToChildW, closer, nil
}

func releaseChildSide(cmd *exec.Cmd) {
	for _, f := range cmd.ExtraFiles {
		f.Close()
	}
	cmd.ExtraFiles = nil
}
