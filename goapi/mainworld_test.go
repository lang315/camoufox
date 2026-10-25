package camoufox

import (
	"encoding/json"
	"math"
	"reflect"
	"testing"
)

func TestDecodeSerialized(t *testing.T) {
	cases := []struct {
		name string
		in   string
		want any
	}{
		{"string", `"hi"`, "hi"},
		{"number", `42`, float64(42)},
		{"bool", `true`, true},
		{"undefined", `{"v":"undefined"}`, nil},
		{"null", `{"v":"null"}`, nil},
		{"Infinity", `{"v":"Infinity"}`, math.Inf(1)},
		{"-Infinity", `{"v":"-Infinity"}`, math.Inf(-1)},
		{"negative zero", `{"v":"-0"}`, math.Copysign(0, -1)},
		{"array", `{"a":[1,"x",{"v":"null"}],"id":1}`, []any{float64(1), "x", nil}},
		{"object", `{"o":[{"k":"a","v":1},{"k":"b","v":{"a":[true],"id":2}}],"id":1}`,
			map[string]any{"a": float64(1), "b": []any{true}}},
		{"cycle", `{"o":[{"k":"self","v":{"ref":1}}],"id":1}`, map[string]any{"self": nil}},
		{"date", `{"d":"2026-10-25T00:00:00.000Z"}`, "2026-10-25T00:00:00.000Z"},
		{"url", `{"u":"https://example.com/"}`, "https://example.com/"},
		{"bigint", `{"bi":"9007199254740993"}`, "9007199254740993"},
		{"node", `"ref: <Node>"`, "ref: <Node>"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			var raw any
			if err := json.Unmarshal([]byte(tc.in), &raw); err != nil {
				t.Fatal(err)
			}
			if got := decodeSerialized(raw); !reflect.DeepEqual(got, tc.want) {
				t.Errorf("decodeSerialized(%s) = %#v, want %#v", tc.in, got, tc.want)
			}
		})
	}

	if got, ok := decodeSerialized(map[string]any{"v": "NaN"}).(float64); !ok || !math.IsNaN(got) {
		t.Errorf(`decodeSerialized({"v":"NaN"}) = %#v, want NaN`, got)
	}
}
