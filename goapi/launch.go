// Package camoufox is a native Go launcher and Juggler-protocol driver
// for the Camoufox patched Firefox build. See README.md.
package camoufox

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"runtime"
	"slices"
	"strings"
	"sync"
	"time"

	"github.com/lang315/camoufox/goapi/pkg/config"
	"github.com/lang315/camoufox/goapi/pkg/fingerprint"
	"github.com/lang315/camoufox/goapi/pkg/juggler"
	"github.com/lang315/camoufox/goapi/pkg/proxy"
)

// Browser is a running Camoufox instance. Obtain one via Launch.
type Browser struct {
	proc browserProc
	conn *juggler.Connection
	root *juggler.Session

	debug bool

	// profileDir is removed by Close only when ownsProfileDir is true --
	// a caller-supplied WithUserDataDir is their data, never ours to delete.
	profileDir     string
	ownsProfileDir bool

	mu       sync.Mutex
	contexts map[string]*BrowserContext
	pages    map[string]*Page // by targetId

	defaultCtx *BrowserContext
	info       juggler.BrowserGetInfoResult
	attachSub  juggler.Subscription
	detachSub  juggler.Subscription

	// pageAwaiters hands a NewPage the Page for the target Browser.newPage
	// named, if its attach event has not been seen yet. Guarded by mu.
	pageAwaiters map[string]chan *Page
}

// Launch spawns the Camoufox binary and connects via the Juggler pipe
// transport. The returned Browser owns the subprocess; call Close.
func Launch(ctx context.Context, opts ...Option) (*Browser, error) {
	lc := &launchConfig{
		geoIPTimeout: 8 * time.Second,
	}
	for _, opt := range opts {
		opt(lc)
	}
	if lc.executablePath == "" {
		return nil, errors.New("camoufox: WithExecutablePath is required")
	}
	// Launch prepends its own -profile and Firefox honors the FIRST
	// occurrence, so a caller-supplied one here would be dropped without a
	// word -- and because lc.userDataDir stays empty, the profile Firefox
	// actually uses is our temp dir, which Close deletes. A caller relying on
	// WithArgs("-profile", dir) for persistence would silently get none at
	// all. Fail loudly instead. (-P is Firefox's named-profile flag, different
	// semantics, deliberately not covered.)
	for _, a := range lc.args {
		if a == "-profile" || a == "--profile" {
			return nil, errors.New("camoufox: -profile is managed by Launch and cannot be passed via WithArgs; use WithUserDataDir to run against a specific profile directory")
		}
	}
	_ = runtime.GOOS // pipe wiring is build-tag dispatched

	cfg := lc.cfg
	if cfg == nil {
		cfg = &config.Config{}
	}

	// Geo resolution before fingerprint so we can use the resolved
	// timezone/locale even when the fingerprint preset has its own.
	if lc.geoIPEnabled && lc.proxy != nil {
		info, err := proxy.Resolve(ctx, lc.proxy, lc.geoIPTimeout)
		if err != nil {
			return nil, fmt.Errorf("camoufox: resolve proxy geo: %w", err)
		}
		applyGeo(cfg, info)
	}

	// Fingerprint injection (skipped if caller passed a complete
	// config or asked to skip).
	if !lc.skipFingerprint {
		fpOpts := fingerprint.Options{
			OS:             lc.os,
			FirefoxVersion: lc.firefoxVersion,
			Rand:           lc.rand,
			HostOS:         config.HostOS(),
		}
		if err := fingerprint.Generate(cfg, fpOpts); err != nil {
			return nil, fmt.Errorf("camoufox: generate fingerprint: %w", err)
		}
	}
	if lc.debug {
		cfg.Debug = config.Bool(true)
	}
	if len(lc.addons) > 0 {
		cfg.Addons = append(cfg.Addons, lc.addons...)
	}

	// Detection-risk warnings (mirrors pythonlib LeakWarning). Evaluated
	// after geo resolution + fingerprint so cfg reflects the final config.
	seedUncoveredCanvas(cfg, lc.canvasPlaceholder, lc.rand)
	emitLeakWarnings(os.Stderr, leakWarnings(cfg, lc.proxy != nil, lc.geoIPEnabled, coversCanvas(lc.canvasPlaceholder)))

	envVars, err := cfg.EnvVars(config.HostOS())
	if err != nil {
		return nil, err
	}

	// Build the firefox CLI. The Juggler bootstrap requires
	// --juggler-pipe; --no-remote is recommended so a stale profile
	// lock cannot redirect commands to an existing instance.
	// Without an explicit -profile, Firefox falls back to a persistent default
	// profile keyed per install path, so prefs and browsing state leak between
	// launches that callers expect to be independent (#50).
	profileDir := lc.userDataDir
	ownsProfileDir := false
	if profileDir == "" {
		profileDir, err = os.MkdirTemp("", "camoufox-profile-")
		if err != nil {
			return nil, fmt.Errorf("camoufox: create profile dir: %w", err)
		}
		ownsProfileDir = true
	}
	launched := false
	defer func() {
		if ownsProfileDir && !launched {
			_ = os.RemoveAll(profileDir)
		}
	}()

	args := []string{"--juggler-pipe", "--no-remote", "-profile", profileDir}
	if lc.headless {
		args = append(args, "--headless")
	}
	args = append(args, lc.args...)

	cmd := exec.CommandContext(ctx, lc.executablePath, args...)

	env, err := launchEnv(lc, cfg, envVars, config.HostOS())
	if err != nil {
		return nil, err
	}
	cmd.Env = env

	parentRead, parentWrite, closePipes, err := setupPipes(cmd)
	if err != nil {
		return nil, err
	}

	if lc.debug {
		cmd.Stdout = os.Stderr
		cmd.Stderr = os.Stderr
	} else {
		cmd.Stdout = io.Discard
		cmd.Stderr = io.Discard
	}

	// startBrowser spawns the child and releases the parent's copy of
	// the child-side pipe handles. On Windows this is a raw
	// CreateProcessW that wires the juggler pipe to CRT fds 3/4; on Unix
	// it is cmd.Start() with fd 3/4 inherited via ExtraFiles.
	proc, err := startBrowser(cmd, lc.debug)
	if err != nil {
		_ = closePipes()
		return nil, fmt.Errorf("camoufox: start: %w", err)
	}

	pipe := juggler.NewPipe(parentRead, parentWrite, closePipes)
	conn := juggler.NewConnection(pipe)
	b := &Browser{
		proc:           proc,
		conn:           conn,
		root:           conn.RootSession(),
		debug:          lc.debug,
		profileDir:     profileDir,
		ownsProfileDir: ownsProfileDir,
		contexts:       make(map[string]*BrowserContext),
		pages:          make(map[string]*Page),
		pageAwaiters:   make(map[string]chan *Page),
	}
	b.subscribeAttach()

	// Default hardening prefs. Caller-supplied prefs override these via
	// the lc.firefoxUserPrefs map (last-write-wins below).
	prefs := map[string]any{}
	if !lc.keepMDNSObfuscation {
		// Phase 5 — disable Firefox's mDNS host-address obfuscation so
		// the existing webrtc-ip-spoofing.patch IP regex catches every
		// host candidate uniformly. Without this, host candidates emit
		// as <uuid>.local hostnames that pass through unmasked.
		// Opt out via camoufox.WithMDNSObfuscation(true) when running
		// real WebRTC calls that need mDNS connectivity.
		prefs["media.peerconnection.ice.obfuscate_host_addresses"] = false
	}
	// The bundled browser/settings/camoufox.cfg ships these at 0, which disables
	// session history and leaves Page.GoBack/GoForward inert. Restore the
	// Firefox defaults so navigation works (matches donutbrowser). A
	// userPref overrides the cfg defaultPref.
	prefs["browser.sessionhistory.max_entries"] = 50
	prefs["browser.sessionhistory.max_total_viewers"] = -1
	if lc.proxy != nil {
		// HTTP/3 runs over UDP and is not tunneled by an HTTP CONNECT or
		// SOCKS proxy, so QUIC requests would bypass the proxy and leak
		// the real egress IP. Disable it whenever a proxy is in use.
		prefs["network.http.http3.enable"] = false
		prefs["network.http.http3.enabled"] = false
	}
	// Spoof the CSS2 system fonts (caption/menu/message-box/...) to match the
	// spoofed OS. These resolve via LookAndFeel to the host's real UI font
	// (e.g. "Segoe UI" on Windows) which CreepJS reads — via getComputedStyle
	// on `font: menu` etc. — to detect the host OS. The ui.font.* prefs
	// override that native lookup (nsXPLookAndFeel::GetFontValue). Without
	// this a Windows host spoofing macOS still leaks "Segoe UI:Windows".
	if sf := systemUIFont(cfg.NavigatorPlatform); sf != "" {
		for _, k := range []string{
			"ui.font.caption", "ui.font.icon", "ui.font.menu",
			"ui.font.message-box", "ui.font.small-caption", "ui.font.status-bar",
		} {
			prefs[k] = sf
		}
	}
	// #162: see genericFamilies. CAMOUFOX_NO_GENERIC_PREFS=1 is a test hook, so
	// the browser-side fix can be measured without these prefs hiding it.
	if os.Getenv("CAMOUFOX_NO_GENERIC_PREFS") != "1" {
		for k, v := range genericFontPrefs(uaOSDir(cfg.NavigatorUserAgent, config.HostOS())) {
			prefs[k] = v
		}
	}
	if syncFontFallback(uaOSDir(cfg.NavigatorUserAgent, config.HostOS()), config.HostOS()) {
		prefs["gfx.font_rendering.fallback.async"] = false
	}
	for k, v := range lc.firefoxUserPrefs {
		prefs[k] = v
	}
	if coversCanvas(lc.canvasPlaceholder) {
		addCanvasPlaceholder(prefs)
	}
	setWebGPU(prefs, uaOSDir(cfg.NavigatorUserAgent, config.HostOS()), cfg.WebGLVendor)
	if err := b.enable(ctx, prefs); err != nil {
		_ = b.Close()
		return nil, err
	}
	if lc.proxy != nil {
		if err := b.applyBrowserProxy(ctx, lc.proxy); err != nil {
			_ = b.Close()
			return nil, err
		}
	}
	launched = true
	return b, nil
}

// launchEnv builds the browser's environment: the caller's env (or the parent's),
// CAMOU_CONFIG_N, the per-OS fontconfig on Linux and the optional Xvfb display.
// cfg must be the final config, so the fontconfig follows the generated
// identity. Firefox preferences are not env vars; they go through the
// browser's userPrefs facility via Browser.enable.
func launchEnv(lc *launchConfig, cfg *config.Config, envVars []string, hostOS string) ([]string, error) {
	fontconfig, err := fontconfigEnv(hostOS, lc.executablePath, cfg.NavigatorUserAgent)
	if err != nil {
		return nil, err
	}
	env := append([]string(nil), lc.env...)
	if len(env) == 0 {
		env = append(env, os.Environ()...)
	}
	env = append(env, envVars...)
	// A caller-supplied FONTCONFIG_FILE wins, as in pythonlib's `**env`.
	if fontconfig != "" && !slices.ContainsFunc(lc.env, func(e string) bool {
		return strings.HasPrefix(e, "FONTCONFIG_FILE=")
	}) {
		env = append(env, fontconfig)
	}
	if lc.virtualDisplay != "" {
		env = append(env,
			"DISPLAY="+lc.virtualDisplay,
			"GDK_BACKEND=x11",
			"MOZ_ENABLE_WAYLAND=0",
		)
	}
	return env, nil
}

// applyBrowserProxy issues Browser.setBrowserProxy so the running
// Camoufox routes its traffic through the supplied proxy. This is the
// Go analogue of the `proxy={...}` argument that the Python launcher
// hands to playwright.firefox.launch.
func (b *Browser) applyBrowserProxy(ctx context.Context, p *proxy.Proxy) error {
	u, err := p.URL()
	if err != nil {
		return fmt.Errorf("camoufox: parse proxy: %w", err)
	}
	host, port, err := proxy.SplitHostPort(u)
	if err != nil {
		return fmt.Errorf("camoufox: split proxy host:port: %w", err)
	}
	scheme := proxy.Scheme(u)
	params := map[string]any{
		"type":   scheme,
		"bypass": splitBypass(p.Bypass),
		"host":   host,
		"port":   port,
	}
	if u.User != nil {
		if user := u.User.Username(); user != "" {
			params["username"] = user
		}
		if pw, ok := u.User.Password(); ok {
			params["password"] = pw
		}
	}
	if p.Username != "" {
		params["username"] = p.Username
	}
	if p.Password != "" {
		params["password"] = p.Password
	}
	if err := b.root.Call(ctx, "Browser.setBrowserProxy", params, nil); err != nil {
		return fmt.Errorf("camoufox: setBrowserProxy: %w", err)
	}
	return nil
}

func splitBypass(s string) []string {
	if s == "" {
		return []string{}
	}
	parts := strings.Split(s, ",")
	out := parts[:0]
	for _, p := range parts {
		if t := strings.TrimSpace(p); t != "" {
			out = append(out, t)
		}
	}
	return out
}

// applyGeo writes proxy-resolved geolocation onto cfg without
// overriding caller-provided values.
func applyGeo(cfg *config.Config, info *proxy.GeoInfo) {
	if info.Timezone != "" && cfg.Timezone == "" {
		cfg.Timezone = info.Timezone
	}
	if cfg.GeolocationLatitude == nil {
		cfg.GeolocationLatitude = config.Float64(info.Latitude)
	}
	if cfg.GeolocationLongitude == nil {
		cfg.GeolocationLongitude = config.Float64(info.Longitude)
	}
	if cfg.GeolocationAccuracy == nil {
		cfg.GeolocationAccuracy = config.Float64(50.0)
	}
	if info.IP != "" {
		if strings.Contains(info.IP, ":") {
			if cfg.WebRTCIPv6 == "" {
				cfg.WebRTCIPv6 = info.IP
			}
		} else if cfg.WebRTCIPv4 == "" {
			cfg.WebRTCIPv4 = info.IP
		}
	}
}

func (b *Browser) enable(ctx context.Context, userPrefs map[string]any) error {
	params := juggler.BrowserEnableParams{AttachToDefaultContext: true}
	for name, val := range userPrefs {
		params.UserPrefs = append(params.UserPrefs, juggler.UserPreference{Name: name, Value: val})
	}
	if err := b.root.Call(ctx, "Browser.enable", params, nil); err != nil {
		return fmt.Errorf("camoufox: Browser.enable: %w", err)
	}
	// Best-effort: cache version/userAgent.
	_ = b.root.Call(ctx, "Browser.getInfo", nil, &b.info)
	return nil
}

func (b *Browser) subscribeAttach() {
	b.attachSub = b.conn.On("Browser.attachedToTarget", func(ev juggler.Event) {
		var p juggler.AttachedToTargetEvent
		if err := json.Unmarshal(ev.Params, &p); err != nil {
			return
		}
		// Every attach is a page target. Whoever opened it -- NewPage, a
		// popup, the browser itself -- it is wrapped at once, on the read
		// loop, so none of its session's events are lost.
		bc := b.contextByID(p.TargetInfo.BrowserContextID)
		if p.TargetInfo.Type != "page" || bc == nil {
			return
		}
		page := bc.attachPage(&p)
		go func() {
			ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
			defer cancel()
			if _, err := page.awaitMainContext(ctx, 30*time.Second); err != nil {
				return // closed before it loaded; the detach event cleans up
			}
			bc.publish(page)
		}()
	})
	b.detachSub = b.conn.On("Browser.detachedFromTarget", func(ev juggler.Event) {
		var d juggler.DetachedFromTargetEvent
		if err := json.Unmarshal(ev.Params, &d); err != nil {
			return
		}
		b.mu.Lock()
		p := b.pages[d.TargetID]
		delete(b.pages, d.TargetID)
		b.mu.Unlock()
		if p != nil {
			p.bc.dropPage(p)
			p.finish()
		}
	})
}

// contextByID returns the context with this browserContextId, the default
// context for "", and nil for an id this Browser never created.
func (b *Browser) contextByID(id string) *BrowserContext {
	if id == "" {
		return b.DefaultContext()
	}
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.contexts[id]
}

// awaitPage returns the Page for targetID, waiting for its attach event if it
// has not arrived (the reply to Browser.newPage can precede it).
func (b *Browser) awaitPage(ctx context.Context, targetID string) (*Page, error) {
	b.mu.Lock()
	if p, ok := b.pages[targetID]; ok {
		b.mu.Unlock()
		return p, nil
	}
	ch := make(chan *Page, 1)
	b.pageAwaiters[targetID] = ch
	b.mu.Unlock()

	select {
	case p := <-ch:
		return p, nil
	case <-ctx.Done():
		b.mu.Lock()
		delete(b.pageAwaiters, targetID)
		b.mu.Unlock()
		return nil, ctx.Err()
	case <-b.conn.Done():
		return nil, errors.New("camoufox: connection closed before attachedToTarget")
	}
}

// Close terminates the browser process and tears down the connection.
func (b *Browser) Close() error {
	// Try a graceful Browser.close first; ignore errors because the
	// connection may already be torn down.
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	_ = b.root.Call(ctx, "Browser.close", nil, nil)
	_ = b.conn.Close()
	if b.proc != nil {
		_ = b.proc.Signal(os.Interrupt)
		done := make(chan error, 1)
		go func() { done <- b.proc.Wait() }()
		select {
		case <-done:
		case <-time.After(3 * time.Second):
			_ = b.proc.Kill()
			<-done
		}
	}
	if b.ownsProfileDir && b.profileDir != "" {
		_ = os.RemoveAll(b.profileDir)
	}
	return nil
}

// Info returns the result of Browser.getInfo (userAgent + version)
// captured at launch.
func (b *Browser) Info() juggler.BrowserGetInfoResult { return b.info }

// systemUIFont maps navigator.platform to the CSS2 system-font family that a
// real machine of that OS reports (what Firefox resolves `font: menu` to).
// Empty means "leave the native lookup" (e.g. unknown platform).
func systemUIFont(platform string) string {
	switch {
	case strings.Contains(platform, "Win"):
		return "Segoe UI"
	case strings.Contains(platform, "Mac"):
		return "-apple-system"
	case strings.Contains(platform, "Linux"):
		return "Cantarell"
	}
	return ""
}
