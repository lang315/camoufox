package camoufox_test

import (
	"fmt"
	"os"
	"strings"
	"testing"
)

// browserBinary returns the browser under test, from CAMOUFOX_BIN. Without one the
// test skips on a developer machine and fails in CI unless the job lists "browser" in
// CAMOUFOX_TEST_ALLOW_MISSING, as e2e/util.py and typescript/tests/prereq.ts do: a
// skip reads as green, so a job that forgot the browser would pass having tested nothing.
func browserBinary(t *testing.T) string {
	t.Helper()
	bin, err := lookupBrowser(os.Getenv)
	if err != nil {
		t.Fatal(err)
	}
	if bin == "" {
		t.Skip("set CAMOUFOX_BIN to run")
	}
	return bin
}

// lookupBrowser returns the binary path, "" when a skip is allowed, or an error when CI requires one.
func lookupBrowser(getenv func(string) string) (string, error) {
	if bin := getenv("CAMOUFOX_BIN"); bin != "" {
		return bin, nil
	}
	if getenv("CI") == "" {
		return "", nil
	}
	for _, name := range strings.Split(getenv("CAMOUFOX_TEST_ALLOW_MISSING"), ",") {
		if strings.TrimSpace(name) == "browser" {
			return "", nil
		}
	}
	return "", fmt.Errorf(`test prerequisite missing in CI: browser (CAMOUFOX_BIN is unset); provide it or add "browser" to CAMOUFOX_TEST_ALLOW_MISSING with the reason it cannot be`)
}

func TestLookupBrowser(t *testing.T) {
	env := func(kv map[string]string) func(string) string {
		return func(k string) string { return kv[k] }
	}
	for _, c := range []struct {
		name    string
		env     map[string]string
		want    string
		wantErr bool
	}{
		{"binary set", map[string]string{"CAMOUFOX_BIN": "/b", "CI": "true"}, "/b", false},
		{"developer machine skips", map[string]string{}, "", false},
		{"CI without a binary fails", map[string]string{"CI": "true"}, "", true},
		{"CI allows the gap by name", map[string]string{"CI": "true", "CAMOUFOX_TEST_ALLOW_MISSING": "packaged-locales, browser"}, "", false},
		{"CI with another name still fails", map[string]string{"CI": "true", "CAMOUFOX_TEST_ALLOW_MISSING": "packaged-locales"}, "", true},
	} {
		got, err := lookupBrowser(env(c.env))
		if got != c.want || (err != nil) != c.wantErr {
			t.Errorf("%s: got (%q, %v), want (%q, err=%v)", c.name, got, err, c.want, c.wantErr)
		}
	}
}
