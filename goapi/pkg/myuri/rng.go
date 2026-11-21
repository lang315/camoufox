package myuri

import "math"

// RNG is the random stream every draw comes from: a number in [0, 1).
type RNG func() float64

// MakeRNG is myuri's makeRng: Mulberry32 on the seed taken mod 2^32, so a seed
// draws the same stream as the TypeScript and Python libraries.
func MakeRNG(seed uint64) RNG {
	state := uint32(seed)
	return func() float64 {
		state += 0x6d2b79f5
		t := state
		t = (t ^ t>>15) * (t | 1)
		t ^= t + (t^t>>7)*(t|61)
		return float64(t^t>>14) / 4294967296
	}
}

// gaussian is a Box-Muller sample; u1 is nudged off 0 so log(0) never happens.
func gaussian(rng RNG, mean, std float64) float64 {
	u1 := rng()
	if u1 == 0 {
		u1 = math.SmallestNonzeroFloat64
	}
	u2 := rng()
	z := math.Sqrt(-2*math.Log(u1)) * math.Cos(2*math.Pi*u2)
	return mean + float64(z*std) // float64(): no fused multiply-add, so every platform rounds as JS does
}
