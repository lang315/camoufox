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

	mu       sync.Mutex
	contexts map[string]*BrowserContext
	pages    map[string]*Page // by targetId

	defaultCtx *BrowserContext
	info       juggler.BrowserGetInfoResult
	attachSub  juggler.Subscription

	// attachMu protects both the buffered events and the awaiter
	// channels. NewPage either consumes a previously-buffered event
	// (if attachedToTarget arrived first) or registers a channel to
	// be signalled when the matching event lands.
	attachMu       sync.Mutex
	attachBuffered map[string]*bufferedAttach
	attachAwaiters map[string]chan *juggler.AttachedToTargetEvent
}

// bufferedAttach holds an early-arrival attachedToTarget event along
// with its arrival time so a sweeper can drop orphans (events that
// never get claimed because NewPage was canceled). 30s TTL is plenty
// — NewPage normally claims its event within ms of issuing the call.
type bufferedAttach struct {
	ev *juggler.AttachedToTargetEvent
	at time.Time
}

const attachBufferTTL = 30 * time.Second

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
	emitLeakWarnings(os.Stderr, leakWarnings(cfg, lc.proxy != nil, lc.geoIPEnabled))

	envVars, err := cfg.EnvVars(config.HostOS())
	if err != nil {
		return nil, err
	}

	// Build the firefox CLI. The Juggler bootstrap requires
	// --juggler-pipe; --no-remote is recommended so a stale profile
	// lock cannot redirect commands to an existing instance.
	args := []string{"--juggler-pipe", "--no-remote"}
	if lc.headless {
		args = append(args, "--headless")
	}
	args = append(args, lc.args...)

	cmd := exec.CommandContext(ctx, lc.executablePath, args...)

	// Environment: parent env (or user-provided), CAMOU_CONFIG_N,
	// optional DISPLAY for Xvfb. Firefox preferences are not env
	// vars; they are handled by the browser's userPrefs facility via
	// Browser.enable.
	env := append([]string(nil), lc.env...)
	if len(env) == 0 {
		env = append(env, os.Environ()...)
	}
	env = append(env, envVars...)
	if lc.virtualDisplay != "" {
		env = append(env,
			"DISPLAY="+lc.virtualDisplay,
			"GDK_BACKEND=x11",
			"MOZ_ENABLE_WAYLAND=0",
		)
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
		contexts:       make(map[string]*BrowserContext),
		pages:          make(map[string]*Page),
		attachBuffered: make(map[string]*bufferedAttach),
		attachAwaiters: make(map[string]chan *juggler.AttachedToTargetEvent),
	}
	b.subscribeAttach()
	go b.sweepAttachBuffer()

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
	// The bundled settings/camoufox.cfg ships these at 0, which disables
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
	for k, v := range lc.firefoxUserPrefs {
		prefs[k] = v
	}
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
	return b, nil
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
	if cfg.PDFViewerEnabled == nil {
		cfg.PDFViewerEnabled = config.Bool(true)
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
		b.attachMu.Lock()
		if ch, ok := b.attachAwaiters[p.TargetInfo.TargetID]; ok {
			delete(b.attachAwaiters, p.TargetInfo.TargetID)
			b.attachMu.Unlock()
			select {
			case ch <- &p:
			default:
			}
			return
		}
		pp := p
		b.attachBuffered[p.TargetInfo.TargetID] = &bufferedAttach{ev: &pp, at: time.Now()}
		b.attachMu.Unlock()
	})
}

// sweepAttachBuffer drops orphan early-arrival events older than
// attachBufferTTL. Runs until the connection closes.
func (b *Browser) sweepAttachBuffer() {
	t := time.NewTicker(attachBufferTTL / 2)
	defer t.Stop()
	for {
		select {
		case <-b.conn.Done():
			return
		case now := <-t.C:
			b.attachMu.Lock()
			for id, ba := range b.attachBuffered {
				if now.Sub(ba.at) > attachBufferTTL {
					delete(b.attachBuffered, id)
				}
			}
			b.attachMu.Unlock()
		}
	}
}

// awaitAttach returns the attachedToTarget event for targetID,
// pulling from the buffer if it arrived early or blocking on a
// channel until it does.
func (b *Browser) awaitAttach(ctx context.Context, targetID string) (*juggler.AttachedToTargetEvent, error) {
	b.attachMu.Lock()
	if ba, ok := b.attachBuffered[targetID]; ok {
		delete(b.attachBuffered, targetID)
		b.attachMu.Unlock()
		return ba.ev, nil
	}
	ch := make(chan *juggler.AttachedToTargetEvent, 1)
	b.attachAwaiters[targetID] = ch
	b.attachMu.Unlock()

	select {
	case ev := <-ch:
		return ev, nil
	case <-ctx.Done():
		b.attachMu.Lock()
		delete(b.attachAwaiters, targetID)
		b.attachMu.Unlock()
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
	return nil
}

// Info returns the result of Browser.getInfo (userAgent + version)
// captured at launch.
func (b *Browser) Info() juggler.BrowserGetInfoResult { return b.info }
