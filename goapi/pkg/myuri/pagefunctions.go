package myuri

import (
	_ "embed"
	"encoding/json"
)

//go:embed page_functions.json
var pageFunctions []byte

// The functions the smart actions run in the page, as source, from myuri 4.0.0
// (testdata/gen writes page_functions.json). Each is an arrow function of the
// element: `(el, arg) => ...`. Coordinates are in the viewport of the window that runs them.
var (
	// ScrollPlanJS takes PlanArgs and returns a ScrollPlan, or null when the element is not visible.
	ScrollPlanJS string
	// HitTestJS takes {x, y, pressing} and returns why a press there would miss the element, or null when it lands.
	HitTestJS string
)

func init() {
	var src struct {
		ScrollPlan string `json:"SCROLL_PLAN_JS"`
		HitTest    string `json:"HIT_TEST_JS"`
	}
	if err := json.Unmarshal(pageFunctions, &src); err != nil || src.ScrollPlan == "" || src.HitTest == "" {
		panic("myuri: page_functions.json is not the two page functions")
	}
	ScrollPlanJS, HitTestJS = src.ScrollPlan, src.HitTest
}
