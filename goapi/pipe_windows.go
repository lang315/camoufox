//go:build windows

package camoufox

import (
	"fmt"
	"os"
	"os/exec"
	"strings"
	"sync"
	"syscall"
	"unsafe"
)

// winChildFiles carries the child-side pipe files from setupPipes to
// startBrowser (which spawns then closes them). Keyed by *exec.Cmd,
// which we use only as a builder for args/env on Windows.
var winChildFiles sync.Map // *exec.Cmd -> [2]*os.File{fd3read, fd4write}

// setupPipes wires the Camoufox pipe transport on Windows.
//
// The Windows camoufox.exe is the Firefox launcher stub. With
// --juggler-pipe it takes the read/write pipe from C runtime file
// descriptors 3 and 4 (_get_osfhandle) and hands them to the real
// browser process, whose wmain then republishes them as
// PW_PIPE_READ / PW_PIPE_WRITE for nsRemoteDebuggingPipe. Go's os/exec
// cannot populate CRT fds 3/4, so we spawn with a raw CreateProcessW
// carrying an lpReserved2 CRT-inheritance block (see winSpawn).
//
// We deliberately do NOT set PW_PIPE_READ/WRITE ourselves: wmain only
// derives the pipe from fds 3/4 when PW_PIPE_READ is unset, so setting
// it would pin the browser to the parent's handle values, which differ
// once the launcher relaunches the real browser process.
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
	// The two child-side handles (fd3=browser-read, fd4=browser-write)
	// must be inheritable so CreateProcess can hand them to the child.
	for _, f := range []*os.File{parentToChildR, childToParentW} {
		if err := setInheritable(syscall.Handle(f.Fd())); err != nil {
			parentToChildR.Close()
			parentToChildW.Close()
			childToParentR.Close()
			childToParentW.Close()
			return nil, nil, nil, fmt.Errorf("camoufox: SetHandleInformation: %w", err)
		}
	}
	winChildFiles.Store(cmd, [2]*os.File{parentToChildR, childToParentW})

	closer := func() error {
		childToParentR.Close()
		parentToChildW.Close()
		return nil
	}
	return childToParentR, parentToChildW, closer, nil
}

// releaseChildSide closes the child-side pipe halves after the browser
// process has inherited them.
func releaseChildSide(cmd *exec.Cmd) {
	if v, ok := winChildFiles.LoadAndDelete(cmd); ok {
		for _, f := range v.([2]*os.File) {
			f.Close()
		}
	}
}

// ---- raw process spawn with CRT fd 3/4 inheritance ----------------------

var (
	modkernel32        = syscall.NewLazyDLL("kernel32.dll")
	procCreateProcessW = modkernel32.NewProc("CreateProcessW")
)

// startupInfoEx mirrors STARTUPINFOW but exposes cbReserved2 /
// lpReserved2 — the CRT fd-inheritance block — which syscall.StartupInfo
// keeps unexported.
type startupInfoEx struct {
	Cb              uint32
	LpReserved      *uint16
	LpDesktop       *uint16
	LpTitle         *uint16
	DwX             uint32
	DwY             uint32
	DwXSize         uint32
	DwYSize         uint32
	DwXCountChars   uint32
	DwYCountChars   uint32
	DwFillAttribute uint32
	DwFlags         uint32
	WShowWindow     uint16
	CbReserved2     uint16
	LpReserved2     *byte
	HStdInput       syscall.Handle
	HStdOutput      syscall.Handle
	HStdError       syscall.Handle
}

const (
	_STARTF_USESTDHANDLES       = 0x00000100
	_CREATE_UNICODE_ENVIRONMENT = 0x00000400
	// msvcrt lowio per-fd flags used in the CRT inheritance block.
	_FOPEN = 0x01
	_FPIPE = 0x08
	_FDEV  = 0x40
)

func setInheritable(h syscall.Handle) error {
	return syscall.SetHandleInformation(h, syscall.HANDLE_FLAG_INHERIT, syscall.HANDLE_FLAG_INHERIT)
}

// crtInheritBlock builds the msvcrt lpReserved2 blob:
//
//	int32 count | byte flags[count] | uintptr handles[count]
//
// The child CRT maps entry i to file descriptor i.
func crtInheritBlock(handles []syscall.Handle, flags []byte) []byte {
	n := len(handles)
	hsz := int(unsafe.Sizeof(uintptr(0)))
	buf := make([]byte, 4+n+n*hsz)
	*(*int32)(unsafe.Pointer(&buf[0])) = int32(n)
	copy(buf[4:4+n], flags)
	base := 4 + n
	for i, h := range handles {
		*(*uintptr)(unsafe.Pointer(&buf[base+i*hsz])) = uintptr(h)
	}
	return buf
}

func utf16EnvBlock(env []string) (*uint16, error) {
	var b []uint16
	for _, e := range env {
		u, err := syscall.UTF16FromString(e)
		if err != nil {
			return nil, err
		}
		b = append(b, u...) // includes trailing NUL
	}
	b = append(b, 0) // final block terminator
	return &b[0], nil
}

// winProc is a raw-CreateProcessW child satisfying browserProc.
type winProc struct {
	handle syscall.Handle
	pid    int
}

func (p *winProc) Signal(os.Signal) error {
	// Windows GUI processes have no SIGINT equivalent; teardown goes
	// through the graceful juggler Browser.close and, failing that, Kill.
	return nil
}

func (p *winProc) Kill() error { return syscall.TerminateProcess(p.handle, 1) }

func (p *winProc) Wait() error {
	_, err := syscall.WaitForSingleObject(p.handle, syscall.INFINITE)
	syscall.CloseHandle(p.handle)
	return err
}

// startBrowser spawns camoufox.exe with the juggler pipe wired to CRT
// fds 3 and 4 via an lpReserved2 block, then releases the parent's copy
// of the child-side handles.
func startBrowser(cmd *exec.Cmd, debug bool) (browserProc, error) {
	v, ok := winChildFiles.Load(cmd)
	if !ok {
		return nil, fmt.Errorf("camoufox: windows pipe files missing")
	}
	files := v.([2]*os.File) // [fd3=browser-read, fd4=browser-write]

	// stdio: NUL for stdin; browser stderr to our stderr only in debug.
	nul, err := os.OpenFile("NUL", os.O_RDWR, 0)
	if err != nil {
		return nil, fmt.Errorf("camoufox: open NUL: %w", err)
	}
	defer nul.Close()
	stdin := syscall.Handle(nul.Fd())
	stdout := syscall.Handle(nul.Fd())
	stderr := syscall.Handle(nul.Fd())
	if debug {
		stdout = syscall.Handle(os.Stdout.Fd())
		stderr = syscall.Handle(os.Stderr.Fd())
	}
	h3 := syscall.Handle(files[0].Fd())
	h4 := syscall.Handle(files[1].Fd())
	for _, h := range []syscall.Handle{stdin, stdout, stderr, h3, h4} {
		_ = setInheritable(h)
	}

	handles := []syscall.Handle{stdin, stdout, stderr, h3, h4}
	flags := []byte{
		_FOPEN | _FDEV, _FOPEN | _FDEV, _FOPEN | _FDEV,
		_FOPEN | _FPIPE, _FOPEN | _FPIPE,
	}
	crt := crtInheritBlock(handles, flags)

	argv0p, err := syscall.UTF16PtrFromString(cmd.Path)
	if err != nil {
		return nil, err
	}
	cmdline, err := syscall.UTF16FromString(makeCmdLine(cmd.Args))
	if err != nil {
		return nil, err
	}
	envp, err := utf16EnvBlock(cmd.Env)
	if err != nil {
		return nil, err
	}

	si := startupInfoEx{}
	si.Cb = uint32(unsafe.Sizeof(si))
	si.DwFlags = _STARTF_USESTDHANDLES
	si.HStdInput = stdin
	si.HStdOutput = stdout
	si.HStdError = stderr
	si.CbReserved2 = uint16(len(crt))
	si.LpReserved2 = &crt[0]

	var pi syscall.ProcessInformation
	r1, _, e1 := procCreateProcessW.Call(
		uintptr(unsafe.Pointer(argv0p)),
		uintptr(unsafe.Pointer(&cmdline[0])),
		0, 0,
		1, // bInheritHandles = TRUE
		uintptr(_CREATE_UNICODE_ENVIRONMENT),
		uintptr(unsafe.Pointer(envp)),
		0,
		uintptr(unsafe.Pointer(&si)),
		uintptr(unsafe.Pointer(&pi)),
	)
	if r1 == 0 {
		return nil, fmt.Errorf("camoufox: CreateProcessW: %w", e1)
	}
	syscall.CloseHandle(pi.Thread)
	releaseChildSide(cmd)
	return &winProc{handle: pi.Process, pid: int(pi.ProcessId)}, nil
}

// makeCmdLine joins args into a single Windows command line with proper
// quoting (argv[0] included).
func makeCmdLine(args []string) string {
	var b strings.Builder
	for i, a := range args {
		if i > 0 {
			b.WriteByte(' ')
		}
		b.WriteString(syscall.EscapeArg(a))
	}
	return b.String()
}
