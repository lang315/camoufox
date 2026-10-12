package camoufox

import (
	"path/filepath"
	"testing"
)

// The browser saves a download as <downloadsDir>/<uuid> (juggler
// TargetRegistry.js:75-80), never under the suggested name (#166).
func TestDownloadPathIsDirPlusUUID(t *testing.T) {
	d := &Download{UUID: "ae100b25-e025-4039-b96b-9dea5b347235", SuggestedFileName: "file.bin", downloadsDir: "/tmp/dl"}
	if got, want := d.Path(), filepath.Join("/tmp/dl", "ae100b25-e025-4039-b96b-9dea5b347235"); got != want {
		t.Fatalf("Path() = %q, want %q", got, want)
	}
	if got := (&Download{UUID: "x"}).Path(); got != "" {
		t.Fatalf("Path() with no downloads dir = %q, want empty (nothing was saved)", got)
	}
}
