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
// prints "Couldn't load XPCOM." and exits for a path it cannot resolve that
// way. Launch must hand it an absolute path to the real binary whatever
// spelling the caller used (#362).
func TestLaunchResolvesTheExecutablePath(t *testing.T) {
	bin, err := filepath.Abs(browserBinary(t))
	if err != nil {
		t.Fatal(err)
	}
	cwd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	rel, err := filepath.Rel(cwd, bin)
	if err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(t.TempDir(), "camoufox-link")
	if err := os.Symlink(bin, link); err != nil {
		t.Fatal(err)
	}
	dir := filepath.Dir(bin)
	for name, path := range map[string]string{
		"relative": rel,
		"dotdot":   dir + "/../" + filepath.Base(dir) + "/" + filepath.Base(bin),
		"symlink":  link,
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
