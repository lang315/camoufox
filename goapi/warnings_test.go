package camoufox

import (
	"bytes"
	"strings"
	"testing"

	"github.com/lang315/camoufox/goapi/pkg/config"
)

func TestLeakWarningProxyWithoutGeoIP(t *testing.T) {
	cfg := &config.Config{} // no timezone, no locale

	if w := leakWarnings(cfg, true /*proxy*/, false /*geoip*/); len(w) != 1 {
		t.Fatalf("proxy without geoip: expected 1 warning, got %d: %v", len(w), w)
	}
	if w := leakWarnings(cfg, true, true /*geoip on*/); len(w) != 0 {
		t.Errorf("proxy WITH geoip: expected 0 warnings, got %v", w)
	}
	if w := leakWarnings(cfg, false /*no proxy*/, false); len(w) != 0 {
		t.Errorf("no proxy: expected 0 warnings, got %v", w)
	}
	// Explicit timezone closes the leak even without geoip.
	if w := leakWarnings(&config.Config{Timezone: "Europe/Paris"}, true, false); len(w) != 0 {
		t.Errorf("proxy + explicit timezone: expected 0 warnings, got %v", w)
	}
}

func TestEmitLeakWarnings(t *testing.T) {
	var buf bytes.Buffer
	emitLeakWarnings(&buf, []string{"boom"})
	if got := buf.String(); !strings.Contains(got, "LEAK WARNING: boom") {
		t.Errorf("emit format = %q", got)
	}
}
