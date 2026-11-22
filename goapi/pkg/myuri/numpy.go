package myuri

import (
	"math"
	"math/bits"
)

// The slice of numpy that cursory draws from, as cursory-js 2.1.0 reimplements it
// (dist/random/*.js, dist/numeric.js): each routine consumes the stream and
// evaluates in numpy's order, because the trajectory a seed produces depends on it.
// float64(a*b) is used wherever a product feeds a sum: it stops the compiler fusing
// them (arm64 does), which would round differently from numpy and JS.

// ---- SeedSequence ----

const (
	seedInitA    = 0x43b0d7e5
	seedMultA    = 0x931e8875
	seedInitB    = 0x8b51f9dd
	seedMultB    = 0x58f38ded
	seedMixL     = 0xca01f9dd
	seedMixR     = 0x4973f715
	seedXShift   = 16
	seedPoolSize = 4
)

type hasher struct{ constant uint32 }

func (h *hasher) mix(value uint32) uint32 {
	mixed := value ^ h.constant
	h.constant *= seedMultA
	mixed *= h.constant
	return mixed ^ mixed>>seedXShift
}

func seedMix(x, y uint32) uint32 {
	r := seedMixL*x - seedMixR*y
	return r ^ r>>seedXShift
}

// seedState is SeedSequence([seed]).generate_state(4, uint64): a seed below 2^32
// is a single entropy word, which is all myuri ever hands cursory.
func seedState(seed uint32) [4]uint64 {
	var pool [seedPoolSize]uint32
	h := hasher{seedInitA}
	for i := range pool {
		var word uint32
		if i == 0 {
			word = seed
		}
		pool[i] = h.mix(word)
	}
	for src := 0; src < seedPoolSize; src++ {
		for dst := 0; dst < seedPoolSize; dst++ {
			if src != dst {
				pool[dst] = seedMix(pool[dst], h.mix(pool[src]))
			}
		}
	}
	var words [8]uint32
	constant := uint32(seedInitB)
	for i := range words {
		v := pool[i%seedPoolSize] ^ constant
		constant *= seedMultB
		v *= constant
		words[i] = v ^ v>>seedXShift
	}
	var out [4]uint64
	for i := range out {
		out[i] = uint64(words[2*i]) | uint64(words[2*i+1])<<32
	}
	return out
}

// ---- PCG64 (XSL-RR 128/64) ----

const (
	pcgMulHi = 2549297995355413924
	pcgMulLo = 4865540595714422341
)

type pcg64 struct {
	hi, lo       uint64 // the 128-bit state
	incHi, incLo uint64
	spare        uint32
	hasSpare     bool
}

func newPCG64(seed uint32) *pcg64 {
	s := seedState(seed)
	p := &pcg64{incHi: s[2]<<1 | s[3]>>63, incLo: s[3]<<1 | 1}
	p.step()
	var carry uint64
	p.lo, carry = bits.Add64(p.lo, s[1], 0)
	p.hi, _ = bits.Add64(p.hi, s[0], carry)
	p.step()
	return p
}

func (p *pcg64) step() {
	hi, lo := bits.Mul64(p.lo, pcgMulLo)
	hi += p.hi*pcgMulLo + p.lo*pcgMulHi
	var carry uint64
	p.lo, carry = bits.Add64(lo, p.incLo, 0)
	p.hi, _ = bits.Add64(hi, p.incHi, carry)
}

func (p *pcg64) nextUint64() uint64 {
	p.step()
	return bits.RotateLeft64(p.hi^p.lo, -int(p.hi>>58))
}

func (p *pcg64) nextUint32() uint32 {
	if p.hasSpare {
		p.hasSpare = false
		return p.spare
	}
	n := p.nextUint64()
	p.hasSpare, p.spare = true, uint32(n>>32)
	return uint32(n)
}

func (p *pcg64) nextDouble() float64 {
	return float64(p.nextUint64()>>11) * (1.0 / 9007199254740992.0)
}

// ---- numpy.random.Generator ----

type generator struct{ bits *pcg64 }

// defaultGenerator is np.random.default_rng(seed).
func defaultGenerator(seed uint32) *generator { return &generator{newPCG64(seed)} }

func (g *generator) uniform(low, high float64) float64 {
	return low + float64((high-low)*g.bits.nextDouble())
}

func (g *generator) normal(loc, scale float64) float64 {
	return loc + float64(scale*g.standardNormal())
}

// standardNormal is random_standard_normal's 256-layer ziggurat. Its rejection
// paths draw extra doubles, which must be reproduced to keep the stream aligned.
func (g *generator) standardNormal() float64 {
	for {
		draw := g.bits.nextUint64()
		idx := draw & 0xff
		draw >>= 8
		neg := draw&1 == 1
		mag := (draw >> 1) & 0x000fffffffffffff
		x := float64(mag) * wiDouble[idx]
		if neg {
			x = -x
		}
		if mag < kiDouble[idx] {
			return x
		}
		if idx == 0 {
			for {
				xx := -zigguratNorInvR * math.Log1p(-g.bits.nextDouble())
				yy := -math.Log1p(-g.bits.nextDouble())
				if yy+yy > float64(xx*xx) {
					if (mag>>8)&1 == 1 {
						return -(zigguratNorR + xx)
					}
					return zigguratNorR + xx
				}
			}
		}
		wedge := float64((fiDouble[idx-1]-fiDouble[idx])*g.bits.nextDouble()) + fiDouble[idx]
		if wedge < math.Exp(-0.5*float64(x*x)) {
			return x
		}
	}
}

// integers is Generator.integers(high) for high-1 below 2^32 (Lemire's method),
// the only range cursory asks for.
func (g *generator) integers(high int) int {
	rng := uint64(high - 1)
	if rng == 0 {
		return 0
	}
	excl := rng + 1
	scaled := uint64(g.bits.nextUint32()) * excl
	left := scaled & 0xffffffff
	if left < excl {
		threshold := (math.MaxUint32 - rng) % excl
		for left < threshold {
			scaled = uint64(g.bits.nextUint32()) * excl
			left = scaled & 0xffffffff
		}
	}
	return int(scaled >> 32)
}

// choice is Generator.choice(len(weights), p=weights).
func (g *generator) choice(weights []float64) int {
	cum := make([]float64, len(weights))
	running := 0.0
	for i, w := range weights {
		running += w
		cum[i] = running
	}
	total := cum[len(cum)-1]
	for i := range cum {
		cum[i] /= total
	}
	return searchSortedRight(cum, g.bits.nextDouble())
}

// ---- numeric primitives ----

const epsilon = 2.220446049250313e-16 // np.finfo(float).eps

// pyHypot is math.hypot as CPython's vector_norm computes it. math.Hypot differs
// from it in the last bits, and the distance between endpoints feeds every later
// step. Inputs are finite pixel distances, so NaN, Inf and subnormals are not handled.
func pyHypot(x, y float64) float64 {
	first, second := math.Abs(x), math.Abs(y)
	max := math.Max(first, second)
	if max == 0 {
		return 0
	}
	_, exp := math.Frexp(max)
	scale := math.Ldexp(1, -exp)
	compensated, productResidue, sumResidue := 1.0, 0.0, 0.0
	for _, c := range [2]float64{first, second} {
		scaled := c * scale
		square := float64(scaled * scaled)
		squareLow := math.FMA(scaled, scaled, -square)
		sum := compensated + square
		sumResidue += compensated - sum + square
		compensated = sum
		productResidue += squareLow
	}
	root := math.Sqrt(compensated - 1.0 + (productResidue + sumResidue))
	square := float64(-root * root)
	squareLow := math.FMA(-root, root, -square)
	sum := compensated + square
	sumResidue += compensated - sum + square
	compensated = sum
	productResidue += squareLow
	root += (compensated - 1.0 + (productResidue + sumResidue)) / (2.0 * root)
	return root / scale
}

// npSum is np.sum over float64s: numpy's pairwise summation, which rounds
// differently from a running total.
func npSum(v []float64) float64 {
	n := len(v)
	switch {
	case n == 0:
		return 0
	case n < 8:
		total := math.Copysign(0, -1)
		for _, x := range v {
			total += x
		}
		return total
	case n <= 128:
		var r [8]float64
		copy(r[:], v[:8])
		i := 8
		for ; i < n-(n%8); i += 8 {
			for lane := 0; lane < 8; lane++ {
				r[lane] += v[i+lane]
			}
		}
		total := r[0] + r[1] + (r[2] + r[3]) + (r[4] + r[5] + (r[6] + r[7]))
		for ; i < n; i++ {
			total += v[i]
		}
		return total
	}
	half := n / 2
	half -= half % 8
	return npSum(v[:half]) + npSum(v[half:])
}

// searchSortedRight is np.searchsorted(sorted, value, side='right').
func searchSortedRight(sorted []float64, value float64) int {
	low, high := 0, len(sorted)
	for low < high {
		mid := (low + high) >> 1
		if value < sorted[mid] {
			high = mid
		} else {
			low = mid + 1
		}
	}
	return low
}

// argSortTopN is the first count indices of np.argsort(values); ties keep the
// earliest index first, as cursory-js does.
func argSortTopN(values []float64, count int) []int {
	best := make([]int, 0, count+1)
	for i, v := range values {
		if len(best) == count && !(v < values[best[count-1]]) {
			continue
		}
		pos := len(best)
		for pos > 0 && v < values[best[pos-1]] {
			pos--
		}
		best = append(best, 0)
		copy(best[pos+1:], best[pos:])
		best[pos] = i
		if len(best) > count {
			best = best[:count]
		}
	}
	return best
}

// rint is np.rint(v).astype(int): halves go to even, unlike Math.round.
func rint(v float64) int { return int(math.RoundToEven(v)) }
