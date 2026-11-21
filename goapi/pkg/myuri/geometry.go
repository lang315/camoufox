package myuri

import "math"

// Point is a position in page px.
type Point struct {
	X float64 `json:"x"`
	Y float64 `json:"y"`
}

// Box is a rectangle in page px.
type Box struct {
	X      float64 `json:"x"`
	Y      float64 `json:"y"`
	Width  float64 `json:"width"`
	Height float64 `json:"height"`
}

// jsRound is Math.round: halves go up.
func jsRound(v float64) float64 { return math.Floor(v + 0.5) }

func pointInBox(p Point, b Box) bool {
	return p.X >= b.X && p.X <= b.X+b.Width && p.Y >= b.Y && p.Y <= b.Y+b.Height
}

// viewportPadding keeps the cursor this far from the viewport edges.
const viewportPadding = 10

// randomBoxPoint chooses a natural point inside box, in whole px. Without a
// current position it samples a centre-biased Gaussian; with one it scores
// several candidates by travel distance and centre proximity (getRandomBoxPoint
// with no padding options and nothing to avoid).
func randomBoxPoint(box Box, current *Point, rng RNG) Point {
	small := box.Width < 40 || box.Height < 40
	widthPct := 25.0
	if small {
		widthPct = 50
	}
	const heightPct = 70.0
	left := (box.Width * (widthPct / 2)) / 100
	right := left
	top := (box.Height * (heightPct / 2)) / 100
	bottom := top
	effX, effY := box.X+left, box.Y+top
	effW, effH := math.Max(0, box.Width-left-right), math.Max(0, box.Height-top-bottom)

	sample := func(spread float64) Point {
		x := effX + float64(math.Max(0, math.Min(1, float64(gaussian(rng, 0, 1)*spread)+0.5))*effW)
		y := effY + float64(math.Max(0, math.Min(1, float64(gaussian(rng, 0, 1)*spread)+0.5))*effH)
		return Point{x, y}
	}
	if current == nil {
		p := sample(0.2)
		return Point{jsRound(p.X), jsRound(p.Y)}
	}
	var candidates [10]Point
	for i := range candidates {
		candidates[i] = sample(0.25)
	}
	cx, cy := effX+effW/2, effY+effH/2
	best, bestScore := candidates[0], math.Inf(1)
	for _, c := range candidates {
		dist := math.Hypot(c.X-current.X, c.Y-current.Y)
		centerDist := math.Hypot(c.X-cx, c.Y-cy)
		if score := float64(dist*0.7) + float64(centerDist*0.3); score < bestScore {
			bestScore, best = score, c
		}
	}
	return Point{jsRound(best.X), jsRound(best.Y)}
}

// overshootPoint is a point drawn uniformly from a disc around c.
func overshootPoint(c Point, radius float64, rng RNG) Point {
	angle := rng() * 2 * math.Pi
	rad := radius * math.Sqrt(rng())
	return Point{c.X + float64(rad*math.Cos(angle)), c.Y + float64(rad*math.Sin(angle))}
}

func shouldOvershoot(a, b Point, threshold float64) bool {
	return math.Hypot(b.X-a.X, b.Y-a.Y) > threshold
}

// A mouse reports its position about every 10 ms, whatever the OS (a lognormal
// of median e^2.303 ms, fitted to 3588 recorded pointermoves).
const (
	reportMu  = 2.303
	reportSD  = 0.091
	reportMS  = 10
	smallMove = 100.0
)

// trajPoint is a point of a stroke, t ms from its start.
type trajPoint struct{ X, Y, T float64 }

// trajectory is one human-like stroke from start to end, one point a mouse
// report; the last is exactly end. moveSpeed multiplies the speed (0: normal).
func trajectory(start, end Point, moveSpeed float64, rng RNG) ([]trajPoint, error) {
	distance := math.Hypot(end.X-start.X, end.Y-start.Y)
	speedFactor := 1.0
	if moveSpeed > 0 {
		speedFactor = 1 / moveSpeed
	}
	if distance < smallMove {
		boost := 1.5 + float64(1.5*(1-distance/smallMove))
		speedFactor /= boost
	}
	// cursory draws from its own numpy-compatible generator, so hand it a seed
	// pulled from our stream. Its timings are scaled by speedFactor afterwards.
	seed := uint32(math.Floor(rng() * 0x100000000))
	points, timings, err := generateTrajectory(
		[2]float64{start.X, start.Y}, [2]float64{end.X, end.Y},
		float64((1000.0/reportMS)*speedFactor), 1, seed)
	if err != nil {
		return nil, err
	}
	times := make([]float64, len(timings))
	for i, t := range timings {
		times[i] = float64(t * speedFactor)
	}
	total := times[len(times)-1]
	// Read the path where the pointer is at each report; the first report after it stops is end.
	var out []trajPoint
	report := func() float64 { return math.Exp(gaussian(rng, reportMu, reportSD)) }
	j := 0
	t := report()
	for ; t < total; t += report() {
		for times[j+1] <= t {
			j++
		}
		a := (t - times[j]) / (times[j+1] - times[j])
		x := points[j][0] + float64(a*(points[j+1][0]-points[j][0]))
		y := points[j][1] + float64(a*(points[j+1][1]-points[j][1]))
		out = append(out, trajPoint{math.Max(0, x), math.Max(0, y), t})
	}
	return append(out, trajPoint{end.X, end.Y, t}), nil
}
