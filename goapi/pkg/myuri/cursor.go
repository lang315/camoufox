package myuri

import (
	"context"
	"math"
)

// myuri's default overshoot settings (settings.ts): a move longer than the
// threshold overshoots the target and corrects after a short dwell.
const (
	overshootRadius       = 120
	overshootThreshold    = 500
	correctionSpeedFactor = 1
	dwellMinMS            = 20
	dwellMaxMS            = 60
)

// moveWith plans a move from start to end as the actions play it. settle maps a
// point to where the pointer actually ends up, which is where the correction
// after an overshoot starts.
func moveWith(start, end Point, rng RNG, overshoot bool, settle func(Point) Point) ([]trajPoint, error) {
	if !overshoot {
		return trajectory(start, end, 0, rng)
	}
	out, err := trajectory(start, overshootPoint(end, overshootRadius, rng), 0, rng)
	if err != nil {
		return nil, err
	}
	last := out[len(out)-1]
	resume := last.T + dwellMinMS + float64(rng()*math.Max(0, dwellMaxMS-dwellMinMS))
	back, err := trajectory(settle(Point{last.X, last.Y}), end, correctionSpeedFactor, rng)
	if err != nil {
		return nil, err
	}
	for _, p := range back {
		out = append(out, trajPoint{p.X, p.Y, resume + p.T})
	}
	return out, nil
}

// Moved records a move the host made outside these actions.
func (a *Actions) Moved(x, y float64) {
	a.cursor, a.hasCursor, a.placed = Point{x, y}, true, true
	a.movedAt = a.host.Now()
}

// here is where the cursor is; before it is known, a point the person's hand
// might rest at in the viewport.
func (a *Actions) here(ctx context.Context) (Point, error) {
	if !a.hasCursor {
		w, h, err := a.host.Viewport(ctx)
		if err != nil {
			return Point{}, err
		}
		x := a.rng() * w
		a.cursor, a.hasCursor = Point{x, a.rng() * h}, true
	}
	return a.cursor, nil
}

// Move moves the cursor to (x, y), clamped to the viewport and rounded to a pixel.
func (a *Actions) Move(ctx context.Context, x, y float64) error {
	if a.rawMove {
		return a.Play(ctx, []Step{{Kind: StepMove, X: x, Y: y}})
	}
	w, h, err := a.host.Viewport(ctx)
	if err != nil {
		return err
	}
	settle := func(p Point) Point {
		return Point{math.Min(math.Max(jsRound(p.X), 0), w-1), math.Min(math.Max(jsRound(p.Y), 0), h-1)}
	}
	end := settle(Point{x, y})
	if a.placed && a.cursor == end {
		return nil
	}
	start, err := a.here(ctx)
	if err != nil {
		return err
	}
	points, err := moveWith(start, end, a.rng, shouldOvershoot(start, end, overshootThreshold), settle)
	if err != nil {
		return err
	}
	var steps []Step
	last, hasLast := a.cursor, a.placed
	for _, p := range points {
		pos := settle(Point{p.X, p.Y})
		// Only macOS reports a mouse that has not left its pixel; elsewhere it sends nothing.
		if hasLast && pos == last && a.os != "macos" {
			continue
		}
		steps = append(steps, Step{Kind: StepMove, X: pos.X, Y: pos.Y, T: p.T})
		last, hasLast = pos, true
	}
	return a.Play(ctx, steps)
}
