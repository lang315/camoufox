package camoufox

import (
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strings"
	"testing"

	"github.com/lang315/camoufox/goapi/pkg/config"
	"github.com/lang315/camoufox/goapi/pkg/fingerprint"
)

const (
	macUA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:156.0) Gecko/20100101 Firefox/156.0"
	winUA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:156.0) Gecko/20100101 Firefox/156.0"
	linUA = "Mozilla/5.0 (X11; Linux x86_64; rv:156.0) Gecko/20100101 Firefox/156.0"

	cwdFontsDir = `<dir prefix="cwd">fonts</dir>`
	groupsJSON  = `{"readBy":{"lin":["L","LM","LW","LMW"],"mac":["M","LM","MW","LMW"],"win":["W","LW","MW","LMW"]}}`
)

var allGroups = []string{"L", "M", "W", "LM", "LW", "MW", "LMW"}

func writeFile(t *testing.T, path, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}

// fakeBundle lays out <bin>/fontconfig/{linux,macos,windows}/fonts.conf, the
// grouped fonts/ tree with its groups.json, and returns the path of the
// (nonexistent) executable beside them. The cache dir is redirected into the
// test's temp dir.
func fakeBundle(t *testing.T) (exe, cache string) {
	t.Helper()
	bin := t.TempDir()
	for _, osDir := range []string{"linux", "macos", "windows"} {
		writeFile(t, filepath.Join(bin, "fontconfig", osDir, "fonts.conf"),
			"<fontconfig>\n\t"+cwdFontsDir+"\n<!-- "+osDir+" -->\n</fontconfig>\n")
	}
	for _, g := range allGroups {
		if err := os.MkdirAll(filepath.Join(bin, "fonts", g), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	writeFile(t, filepath.Join(bin, "fonts", "groups.json"), groupsJSON)
	cache = t.TempDir()
	t.Setenv("XDG_CACHE_HOME", cache)
	return filepath.Join(bin, "camoufox-bin"), cache
}

func confPath(t *testing.T, entry string) string {
	t.Helper()
	path, ok := strings.CutPrefix(entry, "FONTCONFIG_FILE=")
	if !ok {
		t.Fatalf("not a FONTCONFIG_FILE entry: %q", entry)
	}
	return path
}

func scanDirsOf(t *testing.T, conf, fontsDir string) []string {
	t.Helper()
	b, err := os.ReadFile(conf)
	if err != nil {
		t.Fatal(err)
	}
	var out []string
	for _, m := range regexp.MustCompile(`<dir>([^<]*)</dir>`).FindAllStringSubmatch(string(b), -1) {
		out = append(out, strings.TrimPrefix(m[1], fontsDir+string(filepath.Separator)))
	}
	return out
}

func TestFontconfigEnvScanDirsFollowTheIdentityOS(t *testing.T) {
	exe, _ := fakeBundle(t)
	fontsDir := filepath.Join(filepath.Dir(exe), "fonts")
	for _, tc := range []struct {
		ua   string
		want []string
	}{
		{linUA, []string{"L", "LM", "LW", "LMW"}},
		{macUA, []string{"M", "LM", "MW", "LMW"}},
		{winUA, []string{"W", "LW", "MW", "LMW"}},
	} {
		entry, err := fontconfigEnv("linux", exe, tc.ua)
		if err != nil {
			t.Fatal(err)
		}
		got := scanDirsOf(t, confPath(t, entry), fontsDir)
		if strings.Join(got, ",") != strings.Join(tc.want, ",") {
			t.Errorf("%s: scan dirs %v, want %v", tc.ua, got, tc.want)
		}
		b, _ := os.ReadFile(confPath(t, entry))
		if strings.Contains(string(b), `prefix="cwd"`) {
			t.Errorf("%s: relative cwd dir survived in the runtime conf", tc.ua)
		}
	}
}

func TestFontconfigEnvPicksTheConfOfTheIdentityOS(t *testing.T) {
	exe, _ := fakeBundle(t)
	entry, err := fontconfigEnv("linux", exe, macUA)
	if err != nil {
		t.Fatal(err)
	}
	b, _ := os.ReadFile(confPath(t, entry))
	if !strings.Contains(string(b), "<!-- macos -->") {
		t.Errorf("macos identity read the wrong fonts.conf:\n%s", b)
	}
}

func TestFontconfigEnvSkipsMissingGroupDirs(t *testing.T) {
	exe, _ := fakeBundle(t)
	fontsDir := filepath.Join(filepath.Dir(exe), "fonts")
	if err := os.Remove(filepath.Join(fontsDir, "MW")); err != nil {
		t.Fatal(err)
	}
	entry, err := fontconfigEnv("linux", exe, macUA)
	if err != nil {
		t.Fatal(err)
	}
	if got := strings.Join(scanDirsOf(t, confPath(t, entry), fontsDir), ","); got != "M,LM,LMW" {
		t.Errorf("scan dirs %s, want M,LM,LMW", got)
	}
}

func TestFontconfigEnvLegacyBundleLayout(t *testing.T) {
	exe, _ := fakeBundle(t)
	fontsDir := filepath.Join(filepath.Dir(exe), "fonts")
	if err := os.Remove(filepath.Join(fontsDir, "groups.json")); err != nil {
		t.Fatal(err)
	}
	// Older bundles: fonts/<os>/ holds that OS's full set, others do not exist.
	if err := os.MkdirAll(filepath.Join(fontsDir, "macos"), 0o755); err != nil {
		t.Fatal(err)
	}
	entry, err := fontconfigEnv("linux", exe, macUA)
	if err != nil {
		t.Fatal(err)
	}
	if got := strings.Join(scanDirsOf(t, confPath(t, entry), fontsDir), ","); got != "macos" {
		t.Errorf("legacy scan dirs %s, want macos", got)
	}
	// No fonts/<os> either: the fonts/ root itself.
	entry, err = fontconfigEnv("linux", exe, winUA)
	if err != nil {
		t.Fatal(err)
	}
	b, _ := os.ReadFile(confPath(t, entry))
	if !strings.Contains(string(b), "<dir>"+fontsDir+"</dir>") {
		t.Errorf("expected the fonts/ root, got:\n%s", b)
	}
}

func TestFontconfigEnvRejectsCorruptGroups(t *testing.T) {
	exe, _ := fakeBundle(t)
	writeFile(t, filepath.Join(filepath.Dir(exe), "fonts", "groups.json"), "{not json")
	if _, err := fontconfigEnv("linux", exe, macUA); err == nil {
		t.Fatal("corrupt groups.json must fail loudly, not widen the scan to every OS's fonts")
	}
}

func TestFontconfigEnvMissingFontsConfFails(t *testing.T) {
	exe, _ := fakeBundle(t)
	bin := filepath.Dir(exe)
	if err := os.Remove(filepath.Join(bin, "fontconfig", "macos", "fonts.conf")); err != nil {
		t.Fatal(err)
	}
	_, err := fontconfigEnv("linux", exe, macUA)
	if err == nil || !strings.Contains(err.Error(), "fonts.conf not found") {
		t.Fatalf("want a fonts.conf not found error, got %v", err)
	}
	// The pre-v150 directory name still resolves.
	writeFile(t, filepath.Join(bin, "fontconfigs", "macos", "fonts.conf"), cwdFontsDir)
	if _, err := fontconfigEnv("linux", exe, macUA); err != nil {
		t.Fatalf("fontconfigs/ fallback: %v", err)
	}
}

func TestFontconfigEnvOutputIsContentAddressed(t *testing.T) {
	exe, cache := fakeBundle(t)
	a, err := fontconfigEnv("linux", exe, macUA)
	if err != nil {
		t.Fatal(err)
	}
	b, err := fontconfigEnv("linux", exe, macUA)
	if err != nil {
		t.Fatal(err)
	}
	if a != b {
		t.Errorf("same content, different path: %q vs %q", a, b)
	}
	c, err := fontconfigEnv("linux", exe, winUA)
	if err != nil {
		t.Fatal(err)
	}
	if a == c {
		t.Errorf("different OS, same conf path %q", a)
	}
	want := filepath.Join(cache, "camoufox", "fontconfig") + string(filepath.Separator)
	if p := confPath(t, a); !strings.HasPrefix(p, want) || !regexp.MustCompile(`fonts-[0-9a-f]{12}\.conf$`).MatchString(p) {
		t.Errorf("conf path %q is not <cache>/camoufox/fontconfig/fonts-<12 hex>.conf", p)
	}
	left, _ := filepath.Glob(filepath.Join(cache, "camoufox", "fontconfig", "*.tmp*"))
	if len(left) != 0 {
		t.Errorf("temp files left behind: %v", left)
	}
}

func TestFontconfigEnvOnlyOnLinux(t *testing.T) {
	exe, _ := fakeBundle(t)
	for _, host := range []string{"macos", "windows"} {
		entry, err := fontconfigEnv(host, exe, linUA)
		if err != nil || entry != "" {
			t.Errorf("%s host: got (%q, %v), want no entry", host, entry, err)
		}
	}
}

func TestFontconfigEnvFallsBackToHostOSWithoutUA(t *testing.T) {
	exe, _ := fakeBundle(t)
	entry, err := fontconfigEnv("linux", exe, "")
	if err != nil {
		t.Fatal(err)
	}
	b, _ := os.ReadFile(confPath(t, entry))
	if !strings.Contains(string(b), "<!-- linux -->") {
		t.Errorf("no UA must mean the host OS (linux), got:\n%s", b)
	}
}

// The shipped confs are what the placeholder replacement runs against: if one
// loses the line, the runtime conf would carry no scan dir at all.
func TestShippedFontConfsCarryThePlaceholder(t *testing.T) {
	for _, osDir := range []string{"linux", "macos", "windows"} {
		b, err := os.ReadFile(filepath.Join("..", "bundle", "fontconfig", osDir, "fonts.conf"))
		if err != nil {
			t.Fatal(err)
		}
		if !strings.Contains(string(b), cwdFontsDir) {
			t.Errorf("%s/fonts.conf lacks %s", osDir, cwdFontsDir)
		}
	}
}

// The runtime conf lives in the cache dir, so a scan dir derived from a
// relative executable path would resolve against the browser's cwd and the
// browser would silently lose every bundled font.
func TestFontconfigEnvAbsolutizesRelativeExecutable(t *testing.T) {
	exe, _ := fakeBundle(t)
	bin := filepath.Dir(exe)
	wd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Chdir(filepath.Dir(bin)); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chdir(wd) })

	entry, err := fontconfigEnv("linux", filepath.Join(filepath.Base(bin), "camoufox-bin"), macUA)
	if err != nil {
		t.Fatal(err)
	}
	b, _ := os.ReadFile(confPath(t, entry))
	dirs := regexp.MustCompile(`<dir>([^<]*)</dir>`).FindAllStringSubmatch(string(b), -1)
	if len(dirs) == 0 {
		t.Fatalf("no scan dirs in:\n%s", b)
	}
	for _, m := range dirs {
		if !filepath.IsAbs(m[1]) {
			t.Errorf("relative scan dir %q", m[1])
		}
	}
}

// launchEnv is the env Launch hands the browser. These run it with a real
// generated identity so the UA that reaches fontconfigEnv is the one the
// fingerprint produced, not whatever the caller's config held beforehand.
func generatedConfig(t *testing.T, targetOS string) *config.Config {
	t.Helper()
	cfg := &config.Config{}
	if err := fingerprint.Generate(cfg, fingerprint.Options{OS: targetOS}); err != nil {
		t.Fatal(err)
	}
	return cfg
}

func fontconfigEntries(env []string) []string {
	var out []string
	for _, e := range env {
		if strings.HasPrefix(e, "FONTCONFIG_FILE=") {
			out = append(out, e)
		}
	}
	return out
}

func TestLaunchEnvConfinesFontsToTheIdentityOS(t *testing.T) {
	exe, _ := fakeBundle(t)
	fontsDir := filepath.Join(filepath.Dir(exe), "fonts")
	for targetOS, want := range map[string]string{
		"macos":   "M,LM,MW,LMW",
		"windows": "W,LW,MW,LMW",
		"linux":   "L,LM,LW,LMW",
	} {
		cfg := generatedConfig(t, targetOS)
		env, err := launchEnv(&launchConfig{executablePath: exe}, cfg, []string{"CAMOU_CONFIG_1={}"}, "linux")
		if err != nil {
			t.Fatal(err)
		}
		entries := fontconfigEntries(env)
		if len(entries) != 1 {
			t.Fatalf("%s: want one FONTCONFIG_FILE, got %v", targetOS, entries)
		}
		if got := strings.Join(scanDirsOf(t, confPath(t, entries[0]), fontsDir), ","); got != want {
			t.Errorf("%s identity scans %s, want %s", targetOS, got, want)
		}
	}
}

func TestLaunchEnvCallerFontconfigWins(t *testing.T) {
	exe, _ := fakeBundle(t)
	lc := &launchConfig{executablePath: exe, env: []string{"FONTCONFIG_FILE=/caller/fonts.conf"}}
	env, err := launchEnv(lc, generatedConfig(t, "macos"), nil, "linux")
	if err != nil {
		t.Fatal(err)
	}
	if got := fontconfigEntries(env); len(got) != 1 || got[0] != "FONTCONFIG_FILE=/caller/fonts.conf" {
		t.Errorf("caller's FONTCONFIG_FILE must be the only one, got %v", got)
	}
}

func TestLaunchEnvKeepsTheRestOfTheEnv(t *testing.T) {
	exe, _ := fakeBundle(t)
	lc := &launchConfig{executablePath: exe, env: []string{"A=1"}, virtualDisplay: ":99"}
	env, err := launchEnv(lc, generatedConfig(t, "windows"), []string{"CAMOU_CONFIG_1={}"}, "linux")
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"A=1", "CAMOU_CONFIG_1={}", "DISPLAY=:99"} {
		if !slices.Contains(env, want) {
			t.Errorf("env lost %q: %v", want, env)
		}
	}
}

func TestLaunchEnvOffLinuxHasNoFontconfig(t *testing.T) {
	exe, _ := fakeBundle(t)
	env, err := launchEnv(&launchConfig{executablePath: exe}, generatedConfig(t, "macos"), nil, "macos")
	if err != nil {
		t.Fatal(err)
	}
	if got := fontconfigEntries(env); len(got) != 0 {
		t.Errorf("non-Linux host got %v", got)
	}
}

func TestLaunchEnvFailsOnBrokenBundle(t *testing.T) {
	exe, _ := fakeBundle(t)
	if err := os.Remove(filepath.Join(filepath.Dir(exe), "fontconfig", "macos", "fonts.conf")); err != nil {
		t.Fatal(err)
	}
	if _, err := launchEnv(&launchConfig{executablePath: exe}, generatedConfig(t, "macos"), nil, "linux"); err == nil {
		t.Fatal("a bundle without fonts.conf must fail the launch")
	}
}
