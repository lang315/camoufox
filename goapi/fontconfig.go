package camoufox

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// fontconfigEnv returns the FONTCONFIG_FILE=<path> entry that confines the
// browser to the bundled fonts of the identity's OS, or "" off Linux (the other
// hosts render with their own font stack). It ports pythonlib/camoufox/utils.py
// get_env_vars + _generate_fontconfig: without it a Linux launch resolves
// against the host's fontconfig and renders host fonts under a foreign-OS
// identity.
//
// ua is the identity's user agent; empty means the host OS, as in Python.
func fontconfigEnv(hostOS, exe, ua string) (string, error) {
	if hostOS != "linux" {
		return "", nil
	}
	osDir := uaOSDir(ua, hostOS)
	bin := filepath.Dir(exe)

	// v150+ uses "fontconfig/"; older bundles shipped "fontconfigs/".
	confDir := filepath.Join(bin, "fontconfig", osDir)
	if !fileExists(filepath.Join(confDir, "fonts.conf")) {
		confDir = filepath.Join(bin, "fontconfigs", osDir)
	}
	if !fileExists(filepath.Join(confDir, "fonts.conf")) {
		return "", fmt.Errorf("camoufox: fonts.conf not found in %s; something is wrong with the camoufox bundle", confDir)
	}

	scanDirs, err := fontScanDirs(filepath.Join(bin, "fonts"), osDir)
	if err != nil {
		return "", err
	}
	conf, err := os.ReadFile(filepath.Join(confDir, "fonts.conf"))
	if err != nil {
		return "", fmt.Errorf("camoufox: read fonts.conf: %w", err)
	}
	dirs := make([]string, len(scanDirs))
	for i, d := range scanDirs {
		dirs[i] = "<dir>" + d + "</dir>"
	}
	runtimeConf := strings.ReplaceAll(string(conf), `<dir prefix="cwd">fonts</dir>`, strings.Join(dirs, "\n\t"))

	path, err := writeRuntimeFontconfig(runtimeConf)
	if err != nil {
		return "", err
	}
	return "FONTCONFIG_FILE=" + path, nil
}

// uaOSDir maps a user agent to the bundle's per-OS directory name, like
// pythonlib's determine_ua_os: anything that is neither Windows nor Macintosh
// is Linux. An empty UA means the host.
func uaOSDir(ua, hostOS string) string {
	switch {
	case ua == "":
		return hostOS
	case strings.Contains(ua, "Windows"):
		return "windows"
	case strings.Contains(ua, "Macintosh"):
		return "macos"
	default:
		return "linux"
	}
}

// fontScanDirs lists the directories fontconfig may scan for osDir.
//
// fontconfig scans <dir> recursively, so the fonts/ parent must not be named
// when the bundle has a per-OS layout: every other OS's files would become
// glyph-fallback candidates. The bundle stores each face once, in a group
// directory named for the OSes that use it, and groups.json's readBy lists the
// groups each OS reads. Older bundles hold a full copy per OS in fonts/<os>/.
func fontScanDirs(fontsDir, osDir string) ([]string, error) {
	var dirs []string
	osKey := map[string]string{"linux": "lin", "macos": "mac", "windows": "win"}[osDir]
	raw, err := os.ReadFile(filepath.Join(fontsDir, "groups.json"))
	switch {
	case err == nil:
		var groups struct {
			ReadBy map[string][]string `json:"readBy"`
		}
		if err := json.Unmarshal(raw, &groups); err != nil {
			// Falling back would widen the scan to fonts/, every OS's files.
			return nil, fmt.Errorf("camoufox: parse %s: %w", filepath.Join(fontsDir, "groups.json"), err)
		}
		for _, g := range groups.ReadBy[osKey] {
			if d := filepath.Join(fontsDir, g); isDir(d) {
				dirs = append(dirs, d)
			}
		}
	case !os.IsNotExist(err):
		return nil, fmt.Errorf("camoufox: read groups.json: %w", err)
	}
	if len(dirs) > 0 {
		return dirs, nil
	}
	if d := filepath.Join(fontsDir, osDir); isDir(d) {
		return []string{d}, nil
	}
	return []string{fontsDir}, nil
}

// writeRuntimeFontconfig stores conf under the user cache dir, named by its
// content hash so concurrent launches share one file. It must not live in the
// bundle: that is commonly baked into an image as root and run read-only.
func writeRuntimeFontconfig(conf string) (string, error) {
	base := strings.TrimSpace(os.Getenv("XDG_CACHE_HOME"))
	if base == "" {
		home, err := os.UserHomeDir()
		if err != nil {
			return "", fmt.Errorf("camoufox: locate cache dir: %w", err)
		}
		base = filepath.Join(home, ".cache")
	}
	dir := filepath.Join(base, "camoufox", "fontconfig")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", fmt.Errorf("camoufox: create %s: %w", dir, err)
	}
	sum := sha256.Sum256([]byte(conf))
	path := filepath.Join(dir, "fonts-"+hex.EncodeToString(sum[:])[:12]+".conf")
	if fileExists(path) {
		return path, nil
	}
	// Rename into place so a browser starting beside us never reads a partial file.
	tmp, err := os.CreateTemp(dir, "fonts-*.tmp")
	if err != nil {
		return "", fmt.Errorf("camoufox: write fontconfig: %w", err)
	}
	_, werr := tmp.WriteString(conf)
	cerr := tmp.Close()
	err = errors.Join(werr, cerr)
	if err == nil {
		err = os.Rename(tmp.Name(), path)
	}
	if err != nil {
		_ = os.Remove(tmp.Name())
		return "", fmt.Errorf("camoufox: write fontconfig %s: %w", path, err)
	}
	return path, nil
}

func fileExists(p string) bool {
	st, err := os.Stat(p)
	return err == nil && !st.IsDir()
}

func isDir(p string) bool {
	st, err := os.Stat(p)
	return err == nil && st.IsDir()
}
