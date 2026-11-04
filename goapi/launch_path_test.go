package camoufox_test

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
)

// Firefox finds libxul from the path it was started with, and on macOS it
// prints "Couldn't load XPCOM." and exits for a path with a ".." component or
// a symlink to the binary. A plain relative path works. Launch must hand the
// browser an absolute path to the real binary whatever spelling the caller
// used (#362, #378).
func TestLaunchResolvesTheExecutablePath(t *testing.T) {
	bin, err := filepath.Abs(browserBinary(t))
	if err != nil {
		t.Fatal(err)
	}
	// Go 1.22 in go.mod has no t.Chdir; no test in this package is parallel.
	cwd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chdir(cwd) })
	if err := os.Chdir(filepath.Dir(filepath.Dir(bin))); err != nil {
		t.Fatal(err)
	}
	rel := filepath.Join(filepath.Base(filepath.Dir(bin)), filepath.Base(bin))
	// Windows runs a file only if its name carries the binary's own extension (".exe").
	ext := filepath.Ext(bin)
	link := filepath.Join(t.TempDir(), "camoufox-link"+ext)
	if err := os.Symlink(bin, link); err != nil {
		t.Fatal(err)
	}
	pathDir := t.TempDir()
	if err := os.Symlink(bin, filepath.Join(pathDir, "camoufox"+ext)); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", pathDir)
	dir := filepath.Dir(bin)
	for name, path := range map[string]string{
		"relative": rel, // no "..": it works unresolved, and must keep working
		"dotdot":   dir + "/../" + filepath.Base(dir) + "/" + filepath.Base(bin),
		"symlink":  link,
		"path":     "camoufox", // a bare name is searched on PATH, as exec does
	} {
		t.Run(name, func(t *testing.T) {
			ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
			defer cancel()
			b, err := camoufox.Launch(ctx, camoufox.WithExecutablePath(path), camoufox.WithHeadless(true))
			if err != nil {
				t.Fatalf("Launch(%q): %v", path, err)
			}
			b.Close()
		})
	}
}
