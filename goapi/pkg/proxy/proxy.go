// Package proxy mirrors pythonlib/camoufox/ip.py: a small proxy
// dataclass plus a helper to resolve the visible egress IP and
// timezone through that proxy.
package proxy

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// Proxy describes an outbound HTTP/SOCKS proxy. Server is the only
// required field; Username/Password override credentials embedded in
// the URL.
type Proxy struct {
	Server   string
	Username string
	Password string
	Bypass   string // comma-separated hosts that should bypass the proxy
}

// URL builds a fully-qualified URL ("scheme://user:pass@host:port")
// suitable for net/url and net/http.
func (p Proxy) URL() (*url.URL, error) {
	if p.Server == "" {
		return nil, errors.New("proxy: empty server")
	}
	raw := p.Server
	if !strings.Contains(raw, "://") {
		raw = "http://" + raw
	}
	u, err := url.Parse(raw)
	if err != nil {
		return nil, fmt.Errorf("proxy: parse %q: %w", p.Server, err)
	}
	if p.Username != "" {
		if p.Password != "" {
			u.User = url.UserPassword(p.Username, p.Password)
		} else {
			u.User = url.User(p.Username)
		}
	}
	return u, nil
}

// HTTPClient returns a *http.Client routed through the proxy.
// timeout caps the entire request including connect+TLS.
func (p Proxy) HTTPClient(timeout time.Duration) (*http.Client, error) {
	u, err := p.URL()
	if err != nil {
		return nil, err
	}
	tr := &http.Transport{
		Proxy:                 http.ProxyURL(u),
		DialContext:           (&net.Dialer{Timeout: timeout}).DialContext,
		TLSHandshakeTimeout:   timeout,
		ResponseHeaderTimeout: timeout,
	}
	return &http.Client{Transport: tr, Timeout: timeout}, nil
}

// GeoInfo is the subset of ip-api.com's JSON response we care about.
type GeoInfo struct {
	IP         string  `json:"query"`
	Timezone   string  `json:"timezone"`
	Country    string  `json:"country"`
	CountryISO string  `json:"countryCode"`
	Region     string  `json:"regionName"`
	City       string  `json:"city"`
	Latitude   float64 `json:"lat"`
	Longitude  float64 `json:"lon"`
	ISP        string  `json:"isp"`
	Status     string  `json:"status"`
	Message    string  `json:"message,omitempty"`
}

const ipAPIURL = "http://ip-api.com/json/?fields=status,message,country,countryCode,regionName,city,lat,lon,timezone,isp,query"

// Resolve queries ip-api.com through the proxy and returns the public
// IP plus geolocation/timezone. Pass a nil Proxy to use the direct
// internet path.
func Resolve(ctx context.Context, p *Proxy, timeout time.Duration) (*GeoInfo, error) {
	var client *http.Client
	if p == nil {
		client = &http.Client{Timeout: timeout}
	} else {
		c, err := p.HTTPClient(timeout)
		if err != nil {
			return nil, err
		}
		client = c
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, ipAPIURL, nil)
	if err != nil {
		return nil, err
	}
	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("proxy: resolve: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("proxy: resolve: status %d", resp.StatusCode)
	}
	var info GeoInfo
	if err := json.NewDecoder(resp.Body).Decode(&info); err != nil {
		return nil, fmt.Errorf("proxy: decode: %w", err)
	}
	if info.Status != "success" {
		return nil, fmt.Errorf("proxy: ip-api error: %s", info.Message)
	}
	return &info, nil
}

// SplitHostPort returns the host and port from a proxy URL ready to be
// passed to Browser.setBrowserProxy / setContextProxy.
func SplitHostPort(u *url.URL) (host string, port int, err error) {
	h, ps, err := net.SplitHostPort(u.Host)
	if err != nil {
		return "", 0, err
	}
	var p int
	if _, err := fmt.Sscanf(ps, "%d", &p); err != nil {
		return "", 0, fmt.Errorf("proxy: bad port %q: %w", ps, err)
	}
	return h, p, nil
}

// Scheme returns the proxy type expected by the Juggler protocol:
// "http", "https", "socks", or "socks4".
func Scheme(u *url.URL) string {
	s := strings.ToLower(u.Scheme)
	switch s {
	case "socks5", "socks5h", "socks":
		return "socks"
	case "socks4", "socks4a":
		return "socks4"
	case "https":
		return "https"
	default:
		return "http"
	}
}
