package config

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestEnvVarsChunking(t *testing.T) {
	c := &Config{
		NavigatorUserAgent: "Mozilla/5.0 (X11; Linux x86_64; rv:134.0) Gecko/20100101 Firefox/134.0",
		ScreenWidth:        Uint32(1920),
		ScreenHeight:       Uint32(1080),
		CanvasSeed:         Uint32(42),
	}
	vars, err := c.EnvVars("linux")
	if err != nil {
		t.Fatal(err)
	}
	if len(vars) != 1 {
		t.Fatalf("expected 1 chunk for small config, got %d", len(vars))
	}
	if !strings.HasPrefix(vars[0], "CAMOU_CONFIG_1=") {
		t.Fatalf("bad prefix: %q", vars[0])
	}
	payload := strings.TrimPrefix(vars[0], "CAMOU_CONFIG_1=")
	var got map[string]any
	if err := json.Unmarshal([]byte(payload), &got); err != nil {
		t.Fatalf("payload not JSON: %v (payload=%q)", err, payload)
	}
	if got["navigator.userAgent"] != c.NavigatorUserAgent {
		t.Fatalf("UA mismatch: %v", got["navigator.userAgent"])
	}
	if got["screen.width"].(float64) != 1920 {
		t.Fatalf("width mismatch: %v", got["screen.width"])
	}
	if got["canvas:seed"].(float64) != 42 {
		t.Fatalf("canvas seed mismatch: %v", got["canvas:seed"])
	}
}

func TestEnvVarsCanvasNoiseKeys(t *testing.T) {
	c := &Config{
		CanvasSeed:          Uint32(7),
		CanvasNoiseDensity:  Float64(0.0005),
		CanvasNoiseStrength: Uint32(1),
	}
	vars, err := c.EnvVars("linux")
	if err != nil {
		t.Fatal(err)
	}
	payload := strings.TrimPrefix(strings.Join(vars, ""), "CAMOU_CONFIG_1=")
	for _, k := range []string{`"canvas:seed":7`, `"canvas:noiseDensity":0.0005`, `"canvas:noiseStrength":1`} {
		if !strings.Contains(payload, k) {
			t.Fatalf("missing %s in %s", k, payload)
		}
	}
}

func TestEnvVarsWebRTCLocalIP(t *testing.T) {
	c := &Config{
		WebRTCIPv4:      "203.0.113.1",
		WebRTCLocalIPv4: "10.0.0.42",
		WebRTCLocalIPv6: "fd00::42",
	}
	vars, err := c.EnvVars("linux")
	if err != nil {
		t.Fatal(err)
	}
	payload := strings.TrimPrefix(strings.Join(vars, ""), "CAMOU_CONFIG_1=")
	for _, k := range []string{`"webrtc:ipv4":"203.0.113.1"`, `"webrtc:localipv4":"10.0.0.42"`, `"webrtc:localipv6":"fd00::42"`} {
		if !strings.Contains(payload, k) {
			t.Fatalf("missing %s in %s", k, payload)
		}
	}
}

func TestEnvVarsExtraMerge(t *testing.T) {
	c := &Config{
		NavigatorPlatform: "Win32",
		Extra: map[string]any{
			"custom:experimental": true,
		},
	}
	vars, err := c.EnvVars("linux")
	if err != nil {
		t.Fatal(err)
	}
	payload := strings.TrimPrefix(strings.Join(vars, ""), "CAMOU_CONFIG_1=")
	if !strings.Contains(payload, `"custom:experimental":true`) {
		t.Fatalf("extra key missing in payload: %s", payload)
	}
	if !strings.Contains(payload, `"navigator.platform":"Win32"`) {
		t.Fatalf("named key missing in payload: %s", payload)
	}
}

func TestEnvVarsWindowsChunking(t *testing.T) {
	// Build a payload larger than the Windows 2047-byte cap.
	big := strings.Repeat("x", 5000)
	c := &Config{NavigatorUserAgent: big}
	vars, err := c.EnvVars("windows")
	if err != nil {
		t.Fatal(err)
	}
	if len(vars) < 2 {
		t.Fatalf("expected multiple chunks for large payload on windows, got %d", len(vars))
	}
	for i, v := range vars {
		expectedPrefix := "CAMOU_CONFIG_" + itoa(i+1) + "="
		if !strings.HasPrefix(v, expectedPrefix) {
			t.Fatalf("chunk %d has bad prefix: %q", i, v[:32])
		}
		body := strings.TrimPrefix(v, expectedPrefix)
		if len(body) > chunkSizeWindows {
			t.Fatalf("chunk %d exceeds windows budget: len=%d", i, len(body))
		}
	}
}

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	var buf [20]byte
	i := len(buf)
	for n > 0 {
		i--
		buf[i] = byte('0' + n%10)
		n /= 10
	}
	return string(buf[i:])
}
