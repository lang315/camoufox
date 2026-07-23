package fbtrack

import (
	"net/url"
	"regexp"
	"testing"
	"time"
)

var (
	fbpRe = regexp.MustCompile(`^fb\.1\.\d{13}\.\d{10}$`)
	eidRe = regexp.MustCompile(`^PageView\.123456789\.[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`)
)

func TestFBPFormat(t *testing.T) {
	got := FBP(1, time.UnixMilli(1_700_000_000_000))
	if !fbpRe.MatchString(got) {
		t.Fatalf("fbp %q does not match fb.1.<13ms>.<10digit>", got)
	}
}

func TestFBCFormat(t *testing.T) {
	got := FBC(1, time.UnixMilli(1_700_000_000_000), "abc123")
	if want := "fb.1.1700000000000.abc123"; got != want {
		t.Fatalf("fbc = %q, want %q", got, want)
	}
}

func TestEventIDFormat(t *testing.T) {
	got := EventID("PageView", "123456789")
	if !eidRe.MatchString(got) {
		t.Fatalf("eid %q does not match <event>.<pixel>.<uuidv4>", got)
	}
}

func TestBeaconParams(t *testing.T) {
	b := Beacon{
		PixelID: "123456789", Event: "PageView",
		DocLocation: "https://shop.example/checkout", Referrer: "https://google.com/",
		ScreenW: 1920, ScreenH: 1080, Version: "2.9.100", EventCount: 0,
		FBP: FBP(1, time.Now()), CustomData: map[string]string{"currency": "USD", "value": "9.99"},
	}
	v := b.Values()
	for _, k := range []string{"id", "ev", "dl", "rl", "if", "ts", "sw", "sh", "v", "ec", "fbp", "eid"} {
		if v.Get(k) == "" {
			t.Errorf("beacon missing param %q", k)
		}
	}
	if v.Get("cd[currency]") != "USD" || v.Get("cd[value]") != "9.99" {
		t.Errorf("custom-data not flattened to cd[...]: %v", v)
	}
	u, err := url.Parse(b.URL())
	if err != nil {
		t.Fatalf("beacon URL not parseable: %v", err)
	}
	q := u.Query()
	if q.Get("id") != b.PixelID || q.Get("ev") != b.Event || q.Get("dl") != b.DocLocation || q.Get("cd[currency]") != "USD" {
		t.Errorf("beacon URL dropped params, RawQuery=%q", u.RawQuery)
	}
}

// TestDemo prints a sample beacon (run: go test -run Demo -v) so the reproduction
// is inspectable, not just asserted.
func TestDemo(t *testing.T) {
	now := time.Now()
	fbp := FBP(1, now)
	b := Beacon{
		PixelID: "123456789012345", Event: "PageView",
		DocLocation: "https://shop.example/product/42", Referrer: "https://www.facebook.com/",
		InFrame: false, ScreenW: 1920, ScreenH: 1080, Version: "2.9.100", EventCount: 0, FBP: fbp,
	}
	t.Logf("fbp = %s", fbp)
	t.Logf("eid = %s", EventID("PageView", "123456789012345"))
	t.Logf("beacon = %s", b.URL())
}
