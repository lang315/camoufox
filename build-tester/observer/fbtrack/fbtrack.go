// Package fbtrack reproduces, in Go, the client-side tracking parameters that
// Facebook's public Pixel library (fbevents.js) generates -- the fbp/fbc cookies,
// the event id (eid), and the /tr beacon parameter assembly. It is a faithful
// reproduction of documented client behavior (see docs/observer/fb-beacon-generation.md),
// for tracking research / testing your OWN pixel.
//
// Fidelity notes (from the reverse-engineering, which disclosed these gaps):
//   - fbp's random payload: the exact RNG in fbevents.js was not located; this
//     reproduces the observed FORMAT (fb.<idx>.<unixMillis>.<random-integer>).
//   - The encoded per-event `e` payload and the cd[...] custom-data internals were
//     not decoded; this assembles the documented param KEYS, not those internals.
//
// This package only GENERATES parameters. Sending fabricated events to a pixel you
// do not own is attribution/conversion fraud; that is out of scope here by design.
package fbtrack

import (
	"crypto/rand"
	"fmt"
	"math/big"
	"net/url"
	"strconv"
	"time"
)

// randInt returns a uniform random integer in [0, n).
func randInt(n int64) int64 {
	v, err := rand.Int(rand.Reader, big.NewInt(n))
	if err != nil {
		// crypto/rand should never fail; fall back to a time-derived value.
		return time.Now().UnixNano() % n
	}
	return v.Int64()
}

// FBP builds the _fbp cookie value: fb.<subdomainIndex>.<creationTime>.<payload>
//
// subdomainIndex is fbevents' public-suffix probe result (1 for a normal
// example.com; higher for multi-label public suffixes like co.uk). Pass 1 for the
// common case. The payload is a random integer (10 digits, matching observed fbp).
func FBP(subdomainIndex int, t time.Time) string {
	payload := 1_000_000_000 + randInt(9_000_000_000) // 10-digit, like observed fbp
	return fmt.Sprintf("fb.%d.%d.%d", subdomainIndex, t.UnixMilli(), payload)
}

// FBC builds the _fbc cookie value from an fbclid URL parameter:
// fb.<subdomainIndex>.<creationTime>.<fbclid>
func FBC(subdomainIndex int, t time.Time, fbclid string) string {
	return fmt.Sprintf("fb.%d.%d.%s", subdomainIndex, t.UnixMilli(), fbclid)
}

// EventID reproduces fbevents' eid (browser+server dedup key), documented format
// <eventName>.<pixelID>.<uuid> with a v4-style uuid.
func EventID(event, pixelID string) string {
	return fmt.Sprintf("%s.%s.%s", event, pixelID, uuidV4())
}

// uuidV4 returns a random RFC-4122 v4 UUID (8-4-4-4-12 hex).
func uuidV4() string {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		for i := range b {
			b[i] = byte(time.Now().UnixNano() >> (i % 8))
		}
	}
	b[6] = (b[6] & 0x0f) | 0x40 // version 4
	b[8] = (b[8] & 0x3f) | 0x80 // variant 10
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[0:4], b[4:6], b[6:8], b[8:10], b[10:16])
}

// Beacon holds the browser-surface inputs the /tr beacon is assembled from.
type Beacon struct {
	PixelID    string            // -> id
	Event      string            // -> ev  (e.g. "PageView")
	DocLocation string           // -> dl  (window.location.href)
	Referrer   string            // -> rl  (document.referrer)
	InFrame    bool              // -> if  (window.top !== window)
	ScreenW    int               // -> sw  (screen.width)
	ScreenH    int               // -> sh  (screen.height)
	Version    string            // -> v   (fbevents version, e.g. "2.9.100")
	Release    string            // -> r   (internal release segment; optional)
	EventCount int               // -> ec  (per-pixel in-memory counter, starts 0)
	FBP        string            // -> fbp (the _fbp cookie value)
	EventID    string            // -> eid (dedup id; if empty, generated)
	CustomData map[string]string // -> cd[<key>] (site-supplied custom data)
}

// Values assembles the /tr query parameters in the documented layout. Timestamp
// (ts) is stamped at call time.
func (b Beacon) Values() url.Values {
	eid := b.EventID
	if eid == "" {
		eid = EventID(b.Event, b.PixelID)
	}
	v := url.Values{}
	v.Set("id", b.PixelID)
	v.Set("ev", b.Event)
	v.Set("dl", b.DocLocation)
	v.Set("rl", b.Referrer)
	v.Set("if", strconv.FormatBool(b.InFrame))
	v.Set("ts", strconv.FormatInt(time.Now().UnixMilli(), 10))
	v.Set("sw", strconv.Itoa(b.ScreenW))
	v.Set("sh", strconv.Itoa(b.ScreenH))
	if b.Version != "" {
		v.Set("v", b.Version)
	}
	if b.Release != "" {
		v.Set("r", b.Release)
	}
	v.Set("ec", strconv.Itoa(b.EventCount))
	if b.FBP != "" {
		v.Set("fbp", b.FBP)
	}
	v.Set("eid", eid)
	for k, val := range b.CustomData {
		v.Set("cd["+k+"]", val)
	}
	return v
}

// TrEndpoint is where fbevents transmits the beacon (image-pixel GET first).
const TrEndpoint = "https://www.facebook.com/tr/"

// URL renders the full GET beacon URL a browser would request.
func (b Beacon) URL() string { return TrEndpoint + "?" + b.Values().Encode() }
