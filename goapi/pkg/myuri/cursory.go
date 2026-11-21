package myuri

import (
	"bytes"
	"compress/gzip"
	_ "embed"
	"encoding/json"
	"fmt"
	"math"
	"sort"
	"sync"
)

// cursory-js 2.1.0 (a port of cursory): human-like mouse trajectories cut from
// recordings. Float products that feed a sum are wrapped in float64() so that
// no platform fuses them (see numpy.go).

//go:embed trajectories.json.gz
var trajectoriesGz []byte

type recording struct {
	Points [][2]float64 `json:"points"`
	Timing []float64    `json:"timing"`
	Length float64      `json:"length"`
}

// corpus is the recordings and what cursory derives from them once.
type corpus struct {
	recs                    []recording
	dx, dy, displacement    []float64
	normDx, normDy, lengths []float64
	sortedEfficiency        []float64
}

var (
	corpusOnce sync.Once
	corpusData *corpus
	corpusErr  error
)

func endpointDelta(r *recording, axis int) float64 {
	return r.Points[len(r.Points)-1][axis] - r.Points[0][axis]
}

func loadCorpus() (*corpus, error) {
	corpusOnce.Do(func() {
		zr, err := gzip.NewReader(bytes.NewReader(trajectoriesGz))
		if err != nil {
			corpusErr = fmt.Errorf("myuri: trajectories: %w", err)
			return
		}
		c := &corpus{}
		if err := json.NewDecoder(zr).Decode(&c.recs); err != nil {
			corpusErr = fmt.Errorf("myuri: trajectories: %w", err)
			return
		}
		n := len(c.recs)
		c.dx, c.dy, c.displacement = make([]float64, n), make([]float64, n), make([]float64, n)
		c.normDx, c.normDy, c.lengths = make([]float64, n), make([]float64, n), make([]float64, n)
		eff := make([]float64, n)
		for i := range c.recs {
			r := &c.recs[i]
			c.dx[i], c.dy[i] = endpointDelta(r, 0), endpointDelta(r, 1)
			c.displacement[i] = pyHypot(c.dx[i], c.dy[i])
			if c.displacement[i] != 0 {
				c.normDx[i], c.normDy[i] = c.dx[i]/c.displacement[i], c.dy[i]/c.displacement[i]
			}
			c.lengths[i] = r.Length
			eff[i] = 1
			if r.Length > 0 {
				eff[i] = c.displacement[i] / r.Length
			}
		}
		sort.Float64s(eff)
		c.sortedEfficiency = eff
		corpusData = c
	})
	return corpusData, corpusErr
}

// nearest is findNearestTrajectory: the topN recordings closest to the target in
// direction and in length.
func (c *corpus) nearest(start, end [2]float64, topN int) []*recording {
	const directionWeight, lengthWeight = 0.8, 0.2
	dx, dy := end[0]-start[0], end[1]-start[1]
	length := pyHypot(dx, dy)
	pick := func(idx []int) []*recording {
		out := make([]*recording, len(idx))
		for i, j := range idx {
			out[i] = &c.recs[j]
		}
		return out
	}
	if length == 0 {
		return pick(argSortTopN(c.lengths, topN))
	}
	nx, ny := dx/length, dy/length
	scores := make([]float64, len(c.recs))
	for i := range scores {
		directionDistance := 1 - (float64(c.normDx[i]*nx) + float64(c.normDy[i]*ny))
		lengthRatio := math.Abs(c.displacement[i]-length) / math.Max(length, 1)
		scores[i] = float64(directionWeight*directionDistance) + float64(lengthWeight*lengthRatio)
	}
	return pick(argSortTopN(scores, topN))
}

// closest is findClosestTrajectory: the pool is widened by re-querying around
// jittered endpoints, then one candidate is drawn with a soft preference for the
// requested directness.
func (c *corpus) closest(start, end [2]float64, g *generator, directness float64) (rec *recording, dx, dy, length float64) {
	const numNearest, iterations = 5, 20
	dx, dy = end[0]-start[0], end[1]-start[1]
	length = pyHypot(dx, dy)
	candidates := c.nearest(start, end, numNearest)
	jitter := length * 0.1
	for i := 0; i < iterations; i++ {
		perturbed := [2]float64{end[0] + g.uniform(-jitter, jitter), 0}
		perturbed[1] = end[1] + g.uniform(-jitter, jitter)
		candidates = append(candidates, c.nearest(start, perturbed, numNearest)...)
	}
	preferred := 0.2 + float64(0.75*directness)
	weights := make([]float64, len(candidates))
	for i, cand := range candidates {
		displacement := pyHypot(endpointDelta(cand, 0), endpointDelta(cand, 1))
		efficiency := 1.0
		if cand.Length > 0 {
			efficiency = displacement / cand.Length
		}
		rank := float64(searchSortedRight(c.sortedEfficiency, efficiency)) / float64(len(c.recs))
		offset := (rank - preferred) / 0.2
		core := math.Exp(-0.5 * float64(offset*offset))
		centered := 2*rank - 1
		tailFloor := 0.05 * (1 + float64(0.1*math.Pow(math.Abs(centered), 3)))
		weights[i] = core + tailFloor
	}
	total := npSum(weights)
	for i := range weights {
		weights[i] /= total
	}
	return candidates[g.choice(weights)], dx, dy, length
}

// morph scales, rotates and translates a path onto the requested endpoints.
func morph(points [][2]float64, start, end [2]float64, dxTarget, dyTarget, lengthTarget float64) [][2]float64 {
	first, last := points[0], points[len(points)-1]
	dxO, dyO := last[0]-first[0], last[1]-first[1]
	lengthO := math.Sqrt(float64(dxO*dxO) + float64(dyO*dyO))
	scale := 1.0
	if lengthO != 0 {
		scale = lengthTarget / lengthO
	}
	rotation := math.Atan2(dyTarget, dxTarget) - math.Atan2(dyO, dxO)
	cos, sin := math.Cos(rotation), math.Sin(rotation)
	out := make([][2]float64, len(points))
	for i, p := range points {
		x, y := float64((p[0]-first[0])*scale), float64((p[1]-first[1])*scale)
		out[i] = [2]float64{float64(x*cos) - float64(y*sin) + start[0], float64(x*sin) + float64(y*cos) + start[1]}
	}
	out[0] = start
	out[len(out)-1] = end
	return out
}

// endpointWeights: how much added displacement each point may take, zero with
// zero slope at both ends of the path and one halfway along it.
func endpointWeights(points [][2]float64) []float64 {
	n := len(points)
	progress := make([]float64, n)
	for i := 1; i < n; i++ {
		dx, dy := points[i][0]-points[i-1][0], points[i][1]-points[i-1][1]
		progress[i] = progress[i-1] + math.Sqrt(float64(dx*dx)+float64(dy*dy))
	}
	weights := make([]float64, n)
	total := 0.0
	if n > 0 {
		total = progress[n-1]
	}
	if total == 0 {
		return weights
	}
	for i := range weights {
		f := progress[i] / total
		w := 4 * f * (1 - f)
		weights[i] = float64(w * w)
	}
	return weights
}

// jitter nudges each point sideways by a drifting, correlated amount.
func jitter(points [][2]float64, trajectoryLength float64, g *generator) [][2]float64 {
	const scale, correlation = 0.01, 0.75
	n := len(points)
	lengthScale := math.Min(1, trajectoryLength/400)
	gaps := make([]float64, max(n-1, 0))
	for i := range gaps {
		dx, dy := points[i+1][0]-points[i][0], points[i+1][1]-points[i][1]
		gaps[i] = math.Sqrt(float64(dx*dx) + float64(dy*dy))
	}
	weights := endpointWeights(points)
	adaptive := make([]float64, n)
	for i := range adaptive {
		var before, after float64
		if i > 0 {
			before = gaps[i-1]
		}
		if i < n-1 {
			after = gaps[i]
		}
		avg := (before + after) / 2
		adaptive[i] = float64(float64(scale*(avg/math.Max(avg, 1)))*lengthScale) * weights[i]
	}
	normalX, normalY := make([]float64, n), make([]float64, n)
	for i := range points {
		ahead, behind := points[min(i+1, n-1)], points[max(i-1, 0)]
		tx, ty := ahead[0]-behind[0], ahead[1]-behind[1]
		if tl := math.Sqrt(float64(tx*tx) + float64(ty*ty)); tl > epsilon {
			normalX[i], normalY[i] = -ty/tl, tx/tl
		}
	}
	innovations := make([]float64, n)
	for i := range innovations {
		innovations[i] = g.standardNormal()
	}
	innovationScale := math.Sqrt(1 - correlation*correlation)
	out := make([][2]float64, n)
	lateral := 0.0
	for i, p := range points {
		if i == 0 {
			lateral = innovations[0]
		} else {
			lateral = float64(correlation*lateral) + float64(innovationScale*innovations[i])
		}
		d := float64(lateral * adaptive[i])
		out[i] = [2]float64{p[0] + float64(normalX[i]*d), p[1] + float64(normalY[i]*d)}
	}
	return out
}

// middleBiasedPoint is a random point in the rectangle two corners span, pulled
// to the middle by a Gaussian.
func middleBiasedPoint(x1, y1, x2, y2 float64, g *generator) [2]float64 {
	const bias = 2.0
	minX, maxX := math.Min(x1, x2), math.Max(x1, x2)
	minY, maxY := math.Min(y1, y2), math.Max(y1, y2)
	ox := g.normal(0, (maxX-minX)/(2*bias))
	oy := g.normal(0, (maxY-minY)/(2*bias))
	return [2]float64{
		math.Max(minX, math.Min(maxX, (minX+maxX)/2+ox)),
		math.Max(minY, math.Min(maxY, (minY+maxY)/2+oy)),
	}
}

// knot bends the path towards a few random points, as if the hand had drifted.
func knot(points [][2]float64, start, end [2]float64, g *generator) [][2]float64 {
	const numKnots, strength = 5, 0.15
	n := len(points)
	offX, offY := make([]float64, n), make([]float64, n)
	toX, toY, dist := make([]float64, n), make([]float64, n), make([]float64, n)
	for k := 0; k < numKnots; k++ {
		kn := middleBiasedPoint(start[0], start[1], end[0], end[1], g)
		maxDist := math.Inf(-1)
		for i, p := range points {
			toX[i], toY[i] = kn[0]-p[0], kn[1]-p[1]
			dist[i] = math.Sqrt(float64(toX[i]*toX[i]) + float64(toY[i]*toY[i]))
			if dist[i] > maxDist {
				maxDist = dist[i]
			}
		}
		if maxDist < 1e-6 {
			continue
		}
		for i := range points {
			scaling := float64((1.0 - dist[i]/maxDist) * strength)
			offX[i] += float64(toX[i] * scaling)
			offY[i] += float64(toY[i] * scaling)
		}
	}
	weights := endpointWeights(points)
	out := make([][2]float64, n)
	for i, p := range points {
		out[i] = [2]float64{p[0] + float64(signedSqrt(offX[i])*weights[i]), p[1] + float64(signedSqrt(offY[i])*weights[i])}
	}
	return out
}

func signedSqrt(v float64) float64 { return math.Copysign(math.Sqrt(math.Abs(v)), v) }

// findTrajectory selects a recording, morphs it onto the endpoints, then jitters
// and knots it there.
func (c *corpus) findTrajectory(start, end [2]float64, g *generator, directness float64) ([][2]float64, []float64) {
	rec, dx, dy, length := c.closest(start, end, g, directness)
	timings := append([]float64(nil), rec.Timing...)
	// A recording replayed over a shorter distance should not take as long.
	if length > 0 && length < rec.Length {
		timeScale := math.Sqrt(length / rec.Length)
		t0 := timings[0]
		for i, t := range timings {
			timings[i] = t0 + float64((t-t0)*timeScale)
		}
	}
	morphed := morph(rec.Points, start, end, dx, dy, length)
	return knot(jitter(morphed, length, g), start, end, g), timings
}

// sampleTimings resamples a recording's timing pattern to the requested rate.
func sampleTimings(timings []float64, frequency, randomizer float64, g *generator) []float64 {
	total := float64(max(1, rint(timings[len(timings)-1]-timings[0])))
	count := max(1, rint(total*frequency/1000))
	var recorded []float64
	for i := 1; i < len(timings); i++ {
		if iv := timings[i] - timings[i-1]; iv > 0 {
			recorded = append(recorded, iv)
		}
	}
	if len(recorded) == 0 {
		recorded = []float64{1}
	}
	roll := g.integers(len(recorded))
	sampled := make([]float64, count)
	for i := range sampled {
		src := int(math.Floor(float64((float64(i)+0.5)*float64(len(recorded))) / float64(count)))
		sampled[i] = recorded[(src+roll)%len(recorded)]
	}
	rescale := func() {
		factor := total / npSum(sampled)
		for i := range sampled {
			sampled[i] *= factor
		}
	}
	rescale()
	if randomizer != 0 {
		noise := make([]float64, count)
		for i := range noise {
			noise[i] = g.uniform(-randomizer, randomizer)
		}
		for i := range sampled {
			sampled[i] = math.Max(sampled[i]+noise[i], epsilon)
		}
		rescale()
	}
	out := make([]float64, 0, count+1)
	out = append(out, 0)
	elapsed := 0.0
	for _, iv := range sampled {
		elapsed += iv
		out = append(out, float64(rint(elapsed)))
	}
	out[len(out)-1] = total
	return out
}

// generateTrajectory is cursory's generateTrajectory(start, end, {frequency,
// frequencyRandomizer, seed}): the positions to move through and the millisecond
// offset of each.
func generateTrajectory(start, end [2]float64, frequency, randomizer float64, seed uint32) ([][2]float64, []float64, error) {
	if start == end {
		return [][2]float64{start}, []float64{0}, nil
	}
	c, err := loadCorpus()
	if err != nil {
		return nil, nil, err
	}
	const directness = 0.65
	g := defaultGenerator(seed)
	recPoints, recTimings := c.findTrajectory(start, end, g, directness)
	t0 := recTimings[0]
	timings := make([]float64, len(recTimings))
	for i, t := range recTimings {
		timings[i] = t - t0
	}
	sampledTimings := sampleTimings(timings, frequency, randomizer, g)
	sampled := make([][2]float64, len(sampledTimings))
	for i, st := range sampledTimings {
		prev := 0
		for j, t := range timings {
			if t <= st {
				prev = j
			}
		}
		next := min(prev+1, len(timings)-1)
		p, n := recPoints[prev], recPoints[next]
		var alpha float64
		if timings[next] != timings[prev] {
			alpha = (st - timings[prev]) / (timings[next] - timings[prev])
		}
		sampled[i] = [2]float64{p[0] + float64(alpha*(n[0]-p[0])), p[1] + float64(alpha*(n[1]-p[1]))}
	}
	dx, dy := end[0]-start[0], end[1]-start[1]
	length := math.Sqrt(float64(dx*dx) + float64(dy*dy))
	jittered := jitter(knot(sampled, start, end, g), length, g)
	return morph(jittered, start, end, dx, dy, pyHypot(dx, dy)), sampledTimings, nil
}
