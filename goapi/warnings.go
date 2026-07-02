package camoufox

import (
	"fmt"
	"io"

	"github.com/lang315/camoufox/goapi/pkg/config"
)

// leakWarnings returns detection-risk warnings for the resolved launch
// configuration. It mirrors the LeakWarning surface in pythonlib/camoufox
// (_warnings.py). The one goapi currently lacked: a proxy set without
// geolocation spoofing leaks the host timezone and locale, which a site can
// cross-check against the proxy's egress region and flag as inconsistent.
//
// Presets carry no timezone, so the generator cannot supply one as a default
// without fabricating a value that may contradict the proxy — the correct fix
// is to warn, not to guess. Callers close the leak with WithGeoIP(true) or by
// setting Config.Timezone / Config.Locale* explicitly.
func leakWarnings(cfg *config.Config, hasProxy, geoIPEnabled bool) []string {
	var w []string
	if cfg == nil {
		return w
	}
	noTZ := cfg.Timezone == ""
	noLocale := cfg.LocaleAll == "" && cfg.LocaleLanguage == ""
	if hasProxy && !geoIPEnabled && noTZ && noLocale {
		w = append(w, "proxy set without geolocation spoofing: the host timezone and locale "+
			"leak and can be cross-checked against the proxy's egress region. Enable "+
			"WithGeoIP(true) or set Config.Timezone / Config.Locale* explicitly.")
	}
	return w
}

// emitLeakWarnings writes each warning to w. Warnings are always surfaced —
// a leak warning suppressed by default is useless.
func emitLeakWarnings(w io.Writer, warnings []string) {
	for _, msg := range warnings {
		fmt.Fprintf(w, "camoufox: LEAK WARNING: %s\n", msg)
	}
}
