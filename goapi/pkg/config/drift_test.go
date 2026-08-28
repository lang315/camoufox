package config

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"regexp"
	"strings"
	"testing"
)

// knownConfigOnlyKeys are CAMOU keys the patched binary reads and config.go
// emits, but which are not yet registered in settings/properties.json (the
// canonical schema). They are live — shipped in patches (css-media-spoofing,
// media-codec-spoofing, screen-orientation-spoofing) — so properties.json
// simply lags. Freezing them here means a NEW divergence fails the test while
// this documented lag passes. When properties.json is updated to register a
// key, remove it from this set. See plan/anti-detect-review-and-optimize.md (T10).
var knownConfigOnlyKeys = map[string]bool{
	"cssMedia:colorGamut":            true,
	"cssMedia:dynamicRange":          true,
	"cssMedia:prefersColorScheme":    true,
	"mediaCapabilities:canPlayType":  true,
	"mediaCapabilities:decodingInfo": true,
	"screen:orientation":             true,
	"screen:orientationAngle":        true,
}

// configJSONKeys reflects the top-level CAMOU_CONFIG keys config.Config emits.
func configJSONKeys() map[string]bool {
	keys := map[string]bool{}
	t := reflect.TypeFor[Config]()
	for i := 0; i < t.NumField(); i++ {
		name := strings.Split(t.Field(i).Tag.Get("json"), ",")[0]
		if name == "" || name == "-" {
			continue
		}
		keys[name] = true
	}
	return keys
}

// TestProducerSchemaDrift asserts the goapi producer (config.go) and the
// canonical schema (settings/properties.json) stay in sync: no spoofable
// property is silently undroppable by the producer, and no producer key
// escapes the schema without being a documented lag. A new patch key added to
// only one side fails here — that is exactly the "dead key / partial spoof"
// class that optimize-for-donut.md found by hand.
func TestProducerSchemaDrift(t *testing.T) {
	data, err := os.ReadFile(filepath.Join("..", "..", "..", "settings", "properties.json"))
	if err != nil {
		t.Fatalf("read properties.json: %v", err)
	}
	var props []struct {
		Property string `json:"property"`
	}
	if err := json.Unmarshal(data, &props); err != nil {
		t.Fatalf("parse properties.json: %v", err)
	}
	schema := map[string]bool{}
	for _, p := range props {
		schema[p.Property] = true
	}
	cfg := configJSONKeys()

	// Every schema property must have a config.go field.
	for k := range schema {
		if !cfg[k] {
			t.Errorf("properties.json key %q has no config.go field (producer cannot emit it)", k)
		}
	}
	// Every config.go key must be registered in the schema, or be a
	// documented lag in knownConfigOnlyKeys.
	for k := range cfg {
		if !schema[k] && !knownConfigOnlyKeys[k] {
			t.Errorf("config.go emits %q that is absent from properties.json and not in knownConfigOnlyKeys — register it in the schema or add it to the allowlist", k)
		}
	}
}

// TestVoiceKeysMatchReader pins config.Voice's JSON keys to the set
// MaskConfig::MVoices actually requires.
//
// TestProducerSchemaDrift above only compares TOP-LEVEL Config keys against
// properties.json, so nested object fields were checked against nothing. That
// gap shipped a real bug: config.go emitted "voiceURI" (mirroring
// settings/camoucfg.jvv, which was itself wrong) while MVoices reads
// "voiceUri". JSON keys are case-sensitive, MVoices skips any entry missing a
// required field, so every goapi-configured voice was dropped and the host's
// own voices stayed exposed. CI passed throughout: the runtime subtest only
// compared voices it recognised, and recognised none.
//
// The oracle here is the reader itself, not a second schema -- agreeing with
// the wrong spec is how the bug got in.
func TestVoiceKeysMatchReader(t *testing.T) {
	src, err := os.ReadFile(filepath.Join("..", "..", "..", "additions", "camoucfg", "MaskConfig.hpp"))
	if err != nil {
		t.Fatalf("read MaskConfig.hpp: %v", err)
	}
	want := map[string]bool{}
	for _, m := range regexp.MustCompile(`voice\.contains\("([^"]+)"\)`).FindAllStringSubmatch(string(src), -1) {
		want[m[1]] = true
	}
	if len(want) == 0 {
		t.Fatal(`no voice.contains("...") found in MaskConfig.hpp -- MVoices was refactored; retarget this test at its new required-field check`)
	}

	got := map[string]bool{}
	vt := reflect.TypeFor[Voice]()
	for i := 0; i < vt.NumField(); i++ {
		if name := strings.Split(vt.Field(i).Tag.Get("json"), ",")[0]; name != "" && name != "-" {
			got[name] = true
		}
	}

	for k := range want {
		if !got[k] {
			t.Errorf("MVoices requires voice key %q but config.Voice emits no such json tag; every voice would be skipped", k)
		}
	}
	for k := range got {
		if !want[k] {
			t.Errorf("config.Voice emits %q which MVoices never reads", k)
		}
	}
}
