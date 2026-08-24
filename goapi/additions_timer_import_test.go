package camoufox_test

import (
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
)

// Chrome-privileged JS modules under additions/ do NOT get the window globals.
// setTimeout/clearTimeout must be imported from Timer.sys.mjs or the call throws
// ReferenceError at runtime -- and when the call sits inside a Promise executor
// (Helper.js awaitTopic did exactly this) the throw is swallowed into a rejected
// promise, so nothing crashes and nothing logs: every awaited juggler topic just
// fails. That shipped undetected from 2026-07-18 to 2026-08-24 because the only
// job running the full suite against a real binary is smoke.yml, which had not
// run since 2026-07-02.
//
// The same defect appeared independently in two files, so this is a recurring
// class rather than a one-off. Guarding it statically costs milliseconds and
// needs no browser.

// bareTimerCall matches setTimeout/clearTimeout used as a bare global. A leading
// '.' or word character means it is a property or method call (domWindow.setTimeout,
// this._setTimeout) which resolves on that object and needs no import.
var bareTimerCall = regexp.MustCompile(`(^|[^.\w])(setTimeout|clearTimeout)\s*\(`)

func TestAdditionsImportTimerBeforeUsingIt(t *testing.T) {
	root := filepath.Join("..", "additions")
	if _, err := os.Stat(root); err != nil {
		t.Skipf("additions/ not present: %v", err)
	}

	var offenders []string
	err := filepath.WalkDir(root, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() {
			return nil
		}
		switch filepath.Ext(path) {
		case ".js", ".mjs", ".jsm":
		default:
			return nil
		}
		src, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		text := string(src)
		if !bareTimerCall.MatchString(text) {
			return nil
		}
		if strings.Contains(text, "Timer.sys.mjs") {
			return nil
		}
		offenders = append(offenders, path)
		return nil
	})
	if err != nil {
		t.Fatalf("walk additions/: %v", err)
	}

	for _, f := range offenders {
		t.Errorf("%s calls setTimeout/clearTimeout as a bare global but never imports "+
			"Timer.sys.mjs -- add: "+
			`const {setTimeout, clearTimeout} = ChromeUtils.importESModule("resource://gre/modules/Timer.sys.mjs");`+
			" (or the ESM `import` form in a .sys.mjs module)", f)
	}
}
