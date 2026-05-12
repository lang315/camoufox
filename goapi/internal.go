package camoufox

import "encoding/json"

// jsonUnmarshal is a thin alias used inside the package so the same
// helper can be wrapped (logging, future test injection) in one place.
func jsonUnmarshal(data []byte, v any) error { return json.Unmarshal(data, v) }
