package myuri

import (
	"context"
	"math"
)

// Scroll planning (scroll-plan.ts, actions.ts). The page-side reads are the
// Target's: myuri runs SCROLL_PLAN_JS and HIT_TEST_JS in the page, and so must
// whoever implements Target.

const (
	// finishPosition is where the planner puts the target: 0 top, 0.5 middle, 1
	// bottom of the clear band.
	finishPosition = 0.5
	// scrollPad is the top and bottom margin (px) of the band the target is scrolled into.
	scrollPad = 20 // max(20, viewportPadding+5)
	// scrollEdge is the left and right margin (px) of the region the cursor may land in.
	scrollEdge = viewportPadding
	// scrollPasses are the scroll plans played before an element is taken as in view
	// (one that moves as it scrolls needs more than one).
	scrollPasses = 3
	// landingEvery and landingLimit: how often a wheel's scroll is checked for
	// having landed, and how long it may take, in ms.
	landingEvery, landingLimit = 50, 1000
)

// PlanArgs are the arguments of SCROLL_PLAN_JS; FromX and FromY are the cursor
// in the target's own window.
type PlanArgs struct {
	FinishPosition float64 `json:"finishPosition"`
	Pad            float64 `json:"pad"`
	Edge           float64 `json:"edge"`
	FromX          float64 `json:"fromX"`
	FromY          float64 `json:"fromY"`
}

// ScrollPlan is what SCROLL_PLAN_JS returns, in the target's own window.
type ScrollPlan struct {
	InView  bool       `json:"inView"`
	DeltaY  float64    `json:"deltaY"`
	HoverX  float64    `json:"hoverX"`
	HoverY  float64    `json:"hoverY"`
	IsPage  bool       `json:"isPage"`
	Region  *Box       `json:"region"`  // where a press may land; nil if the target is outside the viewport or covered
	Box     Box        `json:"box"`     // the target's border box
	Borders [2]float64 `json:"borders"` // left and top border widths
}

// Target is an element on the page, read in the page. Coordinates are in the
// viewport of the window that holds the element; Offset is that window's origin
// in the top page, whose viewport mouse input is dispatched in.
type Target interface {
	// Offset is the element's frame origin in the top page; ok is false when the element is not found.
	Offset(ctx context.Context) (dx, dy float64, ok bool, err error)
	// Plan runs SCROLL_PLAN_JS on the element; nil when it is not visible.
	Plan(ctx context.Context, args PlanArgs) (*ScrollPlan, error)
	// HitTest runs HIT_TEST_JS at (x, y): why a press there would miss the element, or "" when it lands.
	HitTest(ctx context.Context, x, y float64, pressing bool) (string, error)
}

// measure is the scroll plan of target in top-page px, or nil when it is not visible.
func (a *Actions) measure(ctx context.Context, target Target) (*ScrollPlan, error) {
	dx, dy, ok, err := target.Offset(ctx)
	if err != nil || !ok {
		return nil, err
	}
	here, err := a.here(ctx)
	if err != nil {
		return nil, err
	}
	plan, err := target.Plan(ctx, PlanArgs{finishPosition, scrollPad, scrollEdge, here.X - dx, here.Y - dy})
	if err != nil || plan == nil {
		return nil, err
	}
	plan.HoverX += dx
	plan.HoverY += dy
	plan.Box.X += dx
	plan.Box.Y += dy
	if plan.Region != nil {
		r := *plan.Region
		r.X += dx
		r.Y += dy
		plan.Region = &r
	}
	return plan, nil
}

// IntoView scrolls target into view with the wheel, or as Options.IntoView does.
func (a *Actions) IntoView(ctx context.Context, target Target) error {
	if a.intoView != nil {
		return a.intoView(ctx, target)
	}
	for i := 0; i < scrollPasses; i++ {
		plan, err := a.measure(ctx, target)
		if err != nil {
			return err
		}
		if plan == nil || plan.InView || math.Abs(plan.DeltaY) < 1 {
			return nil
		}
		// Over the scroller the plan chose, so the wheel scrolls it.
		if err := a.Move(ctx, plan.HoverX, plan.HoverY); err != nil {
			return err
		}
		if err := a.Wheel(ctx, 0, plan.DeltaY); err != nil {
			return err
		}
		if err := a.landed(ctx, target); err != nil {
			return err
		}
	}
	return nil
}

// landed waits until the element stops moving, as a person waits for a scroll
// to land before aiming; a page that never stops is given landingLimit.
func (a *Actions) landed(ctx context.Context, target Target) error {
	deadline := a.host.Now() + landingLimit
	last, err := a.measure(ctx, target)
	if err != nil {
		return err
	}
	for a.host.Now() < deadline {
		if err := a.wait(ctx, landingEvery); err != nil {
			return err
		}
		plan, err := a.measure(ctx, target)
		if err != nil {
			return err
		}
		if (plan == nil) == (last == nil) && (plan == nil || plan.Box == last.Box) {
			return nil
		}
		last = plan
	}
	return nil
}
