package camoufox

import (
	"encoding/json"
	"errors"
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
		{"shared reference", `{"a":[{"o":[{"k":"a","v":1}],"id":2},{"ref":2}],"id":1}`,
			[]any{map[string]any{"a": float64(1)}, map[string]any{"a": float64(1)}}},
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
			got, err := decodeSerialized(raw)
			if err != nil || !reflect.DeepEqual(got, tc.want) {
				t.Errorf("decodeSerialized(%s) = %#v, %v; want %#v, nil", tc.in, got, err, tc.want)
			}
		})
	}

	if v, err := decodeSerialized(map[string]any{"v": "NaN"}); err != nil || !math.IsNaN(v.(float64)) {
		t.Errorf(`decodeSerialized({"v":"NaN"}) = %#v, %v; want NaN`, v, err)
	}

	errCases := []struct {
		name, in string
		want     error
	}{
		{"self cycle", `{"o":[{"k":"self","v":{"ref":1}}],"id":1}`, errMainWorldCycle},
		{"cycle through an array", `{"o":[{"k":"list","v":{"a":[{"ref":1}],"id":2}}],"id":1}`, errMainWorldCycle},
	}
	for _, tc := range errCases {
		t.Run(tc.name, func(t *testing.T) {
			var raw any
			if err := json.Unmarshal([]byte(tc.in), &raw); err != nil {
				t.Fatal(err)
			}
			if got, err := decodeSerialized(raw); !errors.Is(err, tc.want) || got != nil {
				t.Errorf("decodeSerialized(%s) = %#v, %v; want nil, %v", tc.in, got, err, tc.want)
			}
		})
	}

	if _, err := decodeSerialized(map[string]any{"ref": float64(9)}); err == nil {
		t.Error("a ref to an object never serialized decoded without an error")
	}
}
