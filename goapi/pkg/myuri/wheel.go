package myuri

import (
	"context"
	"math"
)

// A notched mouse wheel (motion/wheel-model.ts, plan.ts). Camoufox identities
// point with a mouse, so the trackpad model is not ported. Each value is a
// lognormal in ms fitted to recorded wheel gestures.
const (
	strokeMu, strokeSD     = 5.215, 0.552
	strokeMinMS            = 60
	strokeMaxMS            = 450
	regripMu, regripSD     = 4.952, 0.563
	regripMinMS            = 50
	regripMaxMS            = 600
	loneNotchProbability   = 0.33
	notchesMu, notchesSD   = 2.833, 0.27
	flickMu, flickSD       = 5.064, 0.18
	flickRegripMu          = 4.258
	flickRegripSD          = 0.446
	frameMS                = 1000.0 / 60
	notchMaxMS             = 2 * frameMS
	nudgeMaxNotches        = 7
	nudgeSD                = 0.54
	macFrameMS             = 20
	macDroppedFrameProb    = 0.1
	macPeakMean, macPeakSD = 10, 1.6
	macPeakMin, macPeakMax = 6, 13
	macCarryMS             = 150
	macCarryDropProb       = 0.45
	pxPerNotch             = 100 // notched: one event a notch
	pxPerLine              = 16  // macos: lines
)

var nudgeMu = math.Log(2)

func clamp(x, lo, hi float64) float64 { return math.Max(lo, math.Min(hi, x)) }

func lognormal(rng RNG, mu, sd float64) float64 { return math.Exp(gaussian(rng, mu, sd)) }

type wheelEvent struct{ deltaTime, deltaY float64 }

func notchedPath(target float64, rng RNG) []wheelEvent {
	sign := math.Copysign(1, target)
	left := math.Max(1, jsRound(math.Abs(target)/pxPerNotch))
	// Each event's frame and notch count; the notches of one frame are one event.
	type frame struct{ frame, notches float64 }
	var frames []frame
	start := 0.0
	nudged := left <= nudgeMaxNotches
	for left > 0 {
		var size float64
		switch {
		case !nudged:
			size = lognormal(rng, notchesMu, notchesSD)
		case len(frames) == 0:
			size = 1
		default:
			size = lognormal(rng, nudgeMu, nudgeSD)
		}
		n := math.Min(left, math.Max(1, jsRound(size)))
		duration := math.Min(n*notchMaxMS, clamp(lognormal(rng, flickMu, flickSD), strokeMinMS, strokeMaxMS))
		regrip := clamp(lognormal(rng, flickRegripMu, flickRegripSD), regripMinMS, regripMaxMS)
		last := start
		for i := 0.0; i < n; i++ {
			last = start + float64(duration*(1-math.Sqrt(1-(i+0.5)/n)))
			f := jsRound(last / frameMS)
			if len(frames) > 0 && frames[len(frames)-1].frame == f {
				frames[len(frames)-1].notches++
			} else {
				frames = append(frames, frame{f, 1})
			}
		}
		left -= n
		start = last + regrip
	}
	// The last event waits out the final re-grip.
	at := func(i int) float64 {
		if i < len(frames) {
			return jsRound(float64(frames[i].frame * frameMS))
		}
		return jsRound(start)
	}
	out := make([]wheelEvent, len(frames))
	for i, f := range frames {
		out[i] = wheelEvent{at(i+1) - at(i), float64(sign*f.notches) * pxPerNotch}
	}
	return out
}

func macPath(target float64, rng RNG) []wheelEvent {
	sign := math.Copysign(1, target)
	left := math.Max(1, jsRound(math.Abs(target)/pxPerLine))
	var events []wheelEvent
	lines := 0.0
	for left > 0 {
		var frames float64
		if rng() < loneNotchProbability {
			frames = 1
		} else {
			duration := clamp(lognormal(rng, strokeMu, strokeSD), strokeMinMS, strokeMaxMS)
			frames = math.Max(2, jsRound(duration/macFrameMS))
		}
		// A stroke after a short re-grip goes on at the speed macOS kept.
		if lines > 0 {
			drop := 0.0
			if rng() < macCarryDropProb {
				drop = 1
			}
			lines = math.Max(1, lines-drop)
		} else {
			lines = 1
		}
		peak := math.Max(lines, jsRound(clamp(gaussian(rng, macPeakMean, macPeakSD), macPeakMin, macPeakMax)))
		for f := 0.0; f < frames && left > 0; f++ {
			if f > 0 {
				step := 5.0
				if !(rng() < 0.2) {
					step = 1 + math.Floor(rng()*3)
				}
				lines = math.Min(peak, lines+step)
			}
			sent := math.Min(lines, left)
			left -= sent
			last := f+1 == frames || left == 0
			var gap float64
			switch {
			case last:
				gap = jsRound(clamp(lognormal(rng, regripMu, regripSD), regripMinMS, regripMaxMS))
			case rng() < macDroppedFrameProb:
				gap = jsRound(2 * macFrameMS)
			default:
				gap = jsRound(macFrameMS)
			}
			events = append(events, wheelEvent{gap, float64(sign*sent) * pxPerLine})
			if last && gap > macCarryMS {
				lines = 0
			}
		}
	}
	return events
}

// wheelPath plans a mouse-wheel scroll of about desired px: whole notches (or
// lines), at least one. Each event's deltaTime is the wait after it. A request
// that rounds to 0 px plans nothing.
func wheelPath(desired float64, rng RNG, macos bool) []wheelEvent {
	if jsRound(desired) == 0 {
		return nil
	}
	if macos {
		return macPath(desired, rng)
	}
	return notchedPath(desired, rng)
}

// wheelEvents is one wheel gesture of distance px as [at ms, delta px] events,
// and the ms it ends at.
func wheelEvents(distance float64, rng RNG, macos bool) (events [][2]float64, end float64) {
	for _, ev := range wheelPath(distance, rng, macos) {
		events = append(events, [2]float64{end, ev.deltaY})
		end += ev.deltaTime
	}
	return events, end
}

// Shift is held for a horizontal scroll: Shift down -> first wheel event (lead)
// and last wheel event -> Shift up (trail), lognormal [mu, sd] in ms.
var (
	shiftLead  = [2]float64{7.023, 0.411}
	shiftTrail = [2]float64{7.501, 0.559}
)

// wheelSteps plans scrolling deltaY px down (negative: up), then deltaX px right
// (negative: left). The horizontal part is Shift held around wheel events, as
// people scroll sideways with a mouse. On macOS the OS turns them horizontal, so
// the events carry dx; elsewhere Firefox does, so they carry the delta in dy.
func wheelSteps(deltaX, deltaY float64, rng RNG, os string) []Step {
	var out []Step
	macos := os == "macos"
	t := 0.0
	if deltaY != 0 {
		events, end := wheelEvents(deltaY, rng, macos)
		for _, ev := range events {
			out = append(out, Step{Kind: StepWheel, Y: ev[1], T: ev[0]})
		}
		t = end
	}
	if deltaX != 0 {
		out = append(out, Step{Kind: StepKey, Name: "Shift", Down: true, T: t})
		t += math.Exp(gaussian(rng, shiftLead[0], shiftLead[1]))
		events, _ := wheelEvents(deltaX, rng, macos)
		for _, ev := range events {
			if macos {
				out = append(out, Step{Kind: StepWheel, X: ev[1], T: t + ev[0]})
			} else {
				out = append(out, Step{Kind: StepWheel, Y: ev[1], T: t + ev[0]})
			}
		}
		t = out[len(out)-1].T + math.Exp(gaussian(rng, shiftTrail[0], shiftTrail[1]))
		out = append(out, Step{Kind: StepKey, Name: "Shift", T: t})
	}
	return out
}

// Wheel scrolls dy px down, then dx px right.
func (a *Actions) Wheel(ctx context.Context, dx, dy float64) error {
	return a.Play(ctx, wheelSteps(dx, dy, a.rng, a.os))
}
