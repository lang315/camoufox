package config

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
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
