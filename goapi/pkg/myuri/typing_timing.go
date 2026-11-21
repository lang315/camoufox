package myuri

import (
	"context"
	"encoding/base64"
	"math"
	"sort"
	"strings"
)

// Keystroke timing (typing/timing.ts, typer.ts, plan.ts): when every keydown and
// keyup happens. The model was fitted on recorded human typing and English bigram
// counts; it works in log space on the keydown-to-keydown interval, then scales
// every gap so the mean matches the requested WPM. Draw order matches myuri's.

// Fitted constants (log-space coefficients on the gap in ms).
const (
	gapBase     = 4.618
	gapBigram   = -0.338 // per decade of bigram frequency
	sameFinger  = 0.289
	repeatKey   = 0.178
	rowJump     = 0.04
	shiftedGap  = 0.976 // the Shift press is inside this gap
	noiseSD     = 0.48
	pauseProb   = 0.08
	pauseMean   = 1.2
	pauseSD     = 0.5
	driftRho    = 0.97 // slow speed drift: AR(1) on log speed
	driftStepSD = 0.03
	minGapMS    = 10
	maxGapMS    = 5000
	minHoldMS   = 25
	maxHoldMS   = 400
	// People differ in how long they hold keys: per-session factor sd (log).
	sessionHoldSD = 0.12
	// Holds shrink with speed, but much less than gaps (hold ~ speed^0.3).
	holdSpeedExponent = 0.3
	// Shift goes down `lead` ms before its key and up a little before that key's keyup.
	shiftLeadMedian  = 115
	shiftLeadSD      = 0.6
	shiftLeadMin     = 30
	shiftTrailMean   = -15
	shiftTrailSD     = 35
	shiftMinAfterKey = 20 // Shift stays down at least this long after its key goes down
	shiftClear       = 8  // Shift is released this long before the next unshifted keydown
	sameKeyClear     = 8  // a key cannot go down again until this long after it came up
	referenceText    = "The quick check took about 20 minutes, so we moved on. Please send the " +
		"report to the team before Friday; they need it for the meeting at 3pm. " +
		"I think it looks good, but there are a few things we should fix first. " +
		"Thanks again for your help with this! Let me know if anything changes."
)

var gapContext = map[string]float64{
	"inWord": 0, "wordStart": 0.788, "toSpace": 0.071,
	"toEnter": 1.2, // only two Enter presses were recorded
	"toDigit": 1.848, "digitRun": 0.301, "toPunct": 1.045, "fromPunct": 1.316,
	"bsNotice": 1.378, "bsRepeat": 0.449, "afterBs": 0.657,
}

// holdParams is [median ms, sigma] of a hold (keydown -> keyup) by key class.
var holdParams = map[string][2]float64{
	"key": {100, 0.28}, "space": {80, 0.22}, "backspace": {85, 0.45}, "enter": {95, 0.25},
}

// ---- keyboard geometry (US QWERTY touch typing) ----

var (
	unshift = func() map[string]string {
		shifted, plain := []rune("~!@#$%^&*()_+{}|:\"<>?"), []rune("`1234567890-=[]\\;',./")
		m := map[string]string{}
		for i, s := range shifted {
			m[string(s)] = string(plain[i])
		}
		return m
	}()
	finger, keyRow = func() (map[string]int, map[string]int) {
		f, r := map[string]int{}, map[string]int{}
		for _, row := range []string{"`12345", "qwert", "asdfg", "zxcvb"} {
			fingers := []int{0, 1, 2, 3, 3}
			if row[0] == '`' {
				fingers = []int{0, 0, 1, 2, 3, 3}
			}
			for i, c := range row {
				f[string(c)] = fingers[i]
			}
		}
		for _, row := range []string{"67890-=", "yuiop[]\\", "hjkl;'", "nm,./"} {
			for i, c := range row {
				f[string(c)] = []int{4, 4, 5, 6, 7, 7, 7, 7}[i]
			}
		}
		for i, row := range []string{"`1234567890-=", "qwertyuiop[]\\", "asdfghjkl;'", "zxcvbnm,./"} {
			for _, c := range row {
				r[string(c)] = i
			}
		}
		return f, r
	}()
	// bigramLog10[a*26+b] is log10 of the share of bigram ab.
	bigramLog10 = func() [676]float64 {
		bin, err := base64.StdEncoding.DecodeString(bigramTableB64)
		if err != nil || len(bin) != 676 {
			panic("myuri: bigram table is not 676 bytes of base64")
		}
		var out [676]float64
		for i, b := range bin {
			out[i] = -float64(b) / 20
		}
		return out
	}()
)

// stroke is one key press: key is a Playwright key name, or with insert a
// character with no key of its own, which the host inserts as text.
type stroke struct {
	key    string
	insert bool
}

func charToStroke(r rune) stroke {
	switch {
	case r == '\n':
		return stroke{key: "Enter"}
	case r == '\t':
		return stroke{key: "Tab"}
	case r >= 0x20 && r <= 0x7e:
		return stroke{key: string(r)}
	}
	return stroke{key: string(r), insert: true}
}

// physical is the key a character is on (lowercase, unshifted), or the key name.
func physical(key string) string {
	if jsLen(key) != 1 {
		return key
	}
	lower := jsLower(key)
	if u, ok := unshift[lower]; ok {
		return u
	}
	return lower
}

// needsShift is whether typing key on US QWERTY needs Shift held.
func needsShift(key string) bool {
	if len(key) != 1 {
		return false
	}
	if key[0] >= 'A' && key[0] <= 'Z' {
		return true
	}
	_, ok := unshift[key]
	return ok
}

func isLetter(c string) bool { return len(c) == 1 && c[0] >= 'a' && c[0] <= 'z' }
func isDigit(c string) bool  { return len(c) == 1 && c[0] >= '0' && c[0] <= '9' }
func isAlnum(c string) bool  { return isDigit(c) || isLetter(strings.ToLower(c)) }

// gapContextOf is the context class of the gap that ends at cur.
func gapContextOf(prev, cur stroke) string {
	p, c := prev.key, cur.key
	switch {
	case c == "Backspace" && p == "Backspace":
		return "bsRepeat"
	case c == "Backspace":
		return "bsNotice"
	case p == "Backspace":
		return "afterBs"
	case c == " ":
		return "toSpace"
	case c == "Enter" || c == "Tab":
		return "toEnter"
	case p == " " || p == "Enter" || p == "Tab":
		return "wordStart"
	case cur.insert:
		return "toPunct"
	case isDigit(c) && isDigit(p):
		return "digitRun"
	case isDigit(c):
		return "toDigit"
	case len(c) == 1 && !isAlnum(c):
		return "toPunct"
	case prev.insert || (len(p) == 1 && !isAlnum(p)) || isDigit(p):
		return "fromPunct"
	}
	return "inWord"
}

// logGapMean is the deterministic part of log(gap) for the pair prev -> cur.
func logGapMean(prev, cur stroke) float64 {
	mu := gapBase + gapContext[gapContextOf(prev, cur)]
	if cur.insert || prev.insert {
		return mu
	}
	a, b := physical(prev.key), physical(cur.key)
	if isLetter(a) && isLetter(b) {
		share := bigramLog10[int(a[0]-'a')*26+int(b[0]-'a')]
		mu += float64(gapBigram * (share - bigramMeanLog10))
	}
	fa, okA := finger[a]
	if fb, okB := finger[b]; okA && okB && fa == fb && a != b {
		mu += sameFinger
	}
	if a == b && jsLen(a) == 1 {
		mu += repeatKey
	}
	if ra, ok := keyRow[a]; ok {
		if rb, ok := keyRow[b]; ok {
			mu += float64(rowJump * math.Abs(float64(ra-rb)))
		}
	}
	if needsShift(cur.key) && !needsShift(prev.key) {
		mu += shiftedGap
	}
	return mu
}

func holdClass(key string) string {
	switch key {
	case " ":
		return "space"
	case "Backspace":
		return "backspace"
	case "Enter", "Tab":
		return "enter"
	}
	return "key"
}

// referenceMeanGapMS is the model's mean gap over a few sentences at scale 1, so
// a given WPM means the same speed whatever the coefficients are. The factor is
// E[exp(noise + drift)], analytic. These are vars: a constant expression would
// round once where JS rounds at every step.
var referenceMeanGapMS = func() float64 {
	var (
		sd, ps, ds = float64(noiseSD), float64(pauseSD), float64(driftStepSD)
		pp, pm, dr = float64(pauseProb), float64(pauseMean), float64(driftRho)
	)
	factor := math.Exp(float64(sd*sd)/2) *
		(1 - pp + float64(pp*math.Exp(pm+float64(ps*ps)/2))) *
		math.Exp(float64(ds*ds)/(1-float64(dr*dr))/2)
	var strokes []stroke
	for _, r := range referenceText {
		strokes = append(strokes, charToStroke(r))
	}
	sum := 0.0
	for i := 1; i < len(strokes); i++ {
		sum += math.Exp(logGapMean(strokes[i-1], strokes[i]))
	}
	return float64(sum/float64(len(strokes)-1)) * factor
}()

type keyAction struct {
	at     float64
	typ    string // "down", "up" or "insert"
	key    string
	stroke int // the stroke it belongs to, or -1
	seq    int
}

// timing is the keystroke timing of one typing session.
type timing struct {
	rng        RNG
	scale      float64
	holdFactor float64
	drift      float64
}

func newTiming(wpm float64, rng RNG) *timing {
	return &timing{rng: rng, scale: (12000 / wpm) / referenceMeanGapMS, holdFactor: math.Exp(gaussian(rng, 0, sessionHoldSD))}
}

// newSession draws a session's speed around wpm and starts its timing.
func newSession(rng RNG, wpm float64) *timing {
	return newTiming(math.Max(10, gaussian(rng, wpm, wpmSD)), rng)
}

// gap is one sampled keydown-to-keydown gap, ms.
func (t *timing) gap(prev, cur stroke) float64 {
	t.drift = float64(driftRho*t.drift) + gaussian(t.rng, 0, driftStepSD)
	noise := gaussian(t.rng, 0, noiseSD)
	if t.rng() < pauseProb {
		noise += math.Max(0, gaussian(t.rng, pauseMean, pauseSD))
	}
	ms := t.scale * math.Exp(logGapMean(prev, cur)+noise+t.drift)
	return math.Min(maxGapMS, math.Max(minGapMS, ms))
}

// hold is one sampled hold (keydown to keyup), ms.
func (t *timing) hold(key string) float64 {
	p := holdParams[holdClass(key)]
	ms := p[0] * t.holdFactor * math.Pow(t.scale, holdSpeedExponent) * math.Exp(gaussian(t.rng, 0, p[1]))
	return math.Min(maxHoldMS, math.Max(minHoldMS, ms))
}

func (t *timing) shiftLead() float64 {
	return math.Max(shiftLeadMin, shiftLeadMedian*math.Exp(gaussian(t.rng, 0, shiftLeadSD)))
}

// plan is strokes as an absolute timeline starting at 0, sorted by time: the
// first key goes down at 0 (or after its Shift lead).
func (t *timing) plan(strokes []stroke) []keyAction {
	var actions []keyAction
	push := func(at float64, typ, key string, s int) {
		actions = append(actions, keyAction{at, typ, key, s, len(actions)})
	}
	var downAt []float64
	type press struct {
		down float64
		up   int
	}
	lastPress := map[string]press{}
	shiftHeld := false
	var lastShiftedDown, lastShiftedUp float64
	releaseShift := func(notAfter float64) {
		at := lastShiftedUp + gaussian(t.rng, shiftTrailMean, shiftTrailSD)
		at = math.Max(at, lastShiftedDown+shiftMinAfterKey)
		at = math.Min(at, notAfter)
		push(at, "up", "Shift", -1)
		shiftHeld = false
	}
	for i, s := range strokes {
		cold := i == 0 // the very first key of a session has no gap before it
		tm := 0.0
		if i > 0 {
			tm = downAt[i-1] + t.gap(strokes[i-1], s)
		}
		shifted := !s.insert && needsShift(s.key)
		if !shifted && shiftHeld {
			// Shift must be up before this key goes down.
			tm = math.Max(tm, lastShiftedDown+shiftMinAfterKey+shiftClear)
			releaseShift(tm - shiftClear)
		}
		if shifted && !shiftHeld {
			lead := t.shiftLead()
			floor := 0.0
			if i > 0 {
				floor = downAt[i-1] + 10
			}
			if cold {
				tm = lead
			}
			shiftAt := math.Max(floor, tm-lead)
			tm = math.Max(tm, shiftAt+shiftLeadMin)
			push(shiftAt, "down", "Shift", -1)
			shiftHeld = true
		}
		// A key cannot go down while it is still held from its last press.
		if !s.insert {
			if last, ok := lastPress[physical(s.key)]; ok {
				prevUp := &actions[last.up]
				latestUp := tm - sameKeyClear
				if prevUp.at > latestUp {
					earliestUp := last.down + minHoldMS
					if latestUp >= earliestUp {
						prevUp.at = latestUp
					} else {
						prevUp.at = earliestUp
						tm = earliestUp + sameKeyClear
					}
				}
			}
		}
		downAt = append(downAt, tm)
		if s.insert {
			push(tm, "insert", s.key, i)
			continue
		}
		push(tm, "down", s.key, i)
		up := tm + t.hold(s.key)
		lastPress[physical(s.key)] = press{tm, len(actions)}
		push(up, "up", s.key, i)
		if shifted {
			lastShiftedDown, lastShiftedUp = tm, up
		}
	}
	if shiftHeld {
		releaseShift(math.Inf(1))
	}
	sort.Slice(actions, func(i, j int) bool {
		if actions[i].at != actions[j].at {
			return actions[i].at < actions[j].at
		}
		return actions[i].seq < actions[j].seq
	})
	return actions
}

// planChord is a chord such as Control+a or Meta+Shift+z: each modifier goes down a
// Shift-like lead after the one before, the key after the last, and each modifier
// comes up just after the key does (innermost first).
func (t *timing) planChord(modifiers []string, key string) []keyAction {
	var out []keyAction
	at := 0.0
	for i, m := range modifiers {
		if i > 0 {
			at += t.shiftLead()
		}
		out = append(out, keyAction{at: at, typ: "down", key: m, stroke: -1})
	}
	keyDown := 0.0
	if len(modifiers) > 0 {
		keyDown = at + t.shiftLead()
	}
	keyUp := keyDown + t.hold(key)
	out = append(out, keyAction{at: keyDown, typ: "down", key: key, stroke: -1}, keyAction{at: keyUp, typ: "up", key: key, stroke: -1})
	for i := len(modifiers) - 1; i >= 0; i-- {
		up := math.Max(keyDown+shiftMinAfterKey, keyUp+gaussian(t.rng, shiftTrailMean, shiftTrailSD))
		out = append(out, keyAction{at: up, typ: "up", key: modifiers[i], stroke: -1})
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].at < out[j].at })
	return out
}

// keySteps turns planned actions into timeline steps.
func keySteps(actions []keyAction) []Step {
	steps := make([]Step, len(actions))
	for i, a := range actions {
		if a.typ == "insert" {
			steps[i] = Step{Kind: StepText, Name: a.key, T: a.at}
		} else {
			steps[i] = Step{Kind: StepKey, Name: a.key, Down: a.typ == "down", T: a.at}
		}
	}
	return steps
}

// Type types text with a typist's typos and corrections at wpm words a minute
// (0: the wpm the actions were made with, else myuri's 80). Each call draws its
// own session speed and hold style from the stream.
func (a *Actions) Type(ctx context.Context, text string, wpm float64) error {
	if wpm <= 0 {
		wpm = a.wpm
	}
	session := newSession(a.rng, wpm)
	m, err := newMarkov(text, 1, a.rng)
	if err != nil {
		return err
	}
	var strokes []stroke
	for _, ev := range m.run() {
		if ev.kind == "backspace" {
			strokes = append(strokes, stroke{key: "Backspace"})
			continue
		}
		for _, r := range ev.chars {
			strokes = append(strokes, charToStroke(r))
		}
	}
	return a.Play(ctx, keySteps(session.plan(strokes)))
}

// Key presses a key or chord in Playwright's notation ('Enter', 'Control+a',
// 'Meta+Shift+z', 'A'). A key that needs Shift gets it.
func (a *Actions) Key(ctx context.Context, key string) error {
	session := newSession(a.rng, a.wpm)
	parts := strings.Split(key, "+")
	var main string
	var modifiers []string
	if strings.HasSuffix(key, "+") {
		// A trailing '+' is the '+' key ('Control++').
		main, modifiers = "+", parts[:len(parts)-2]
	} else {
		main, modifiers = parts[len(parts)-1], parts[:len(parts)-1]
	}
	if needsShift(main) {
		hasShift := false
		for _, m := range modifiers {
			hasShift = hasShift || m == "Shift"
		}
		if !hasShift {
			modifiers = append(modifiers[:len(modifiers):len(modifiers)], "Shift")
		}
	}
	return a.Play(ctx, keySteps(session.planChord(modifiers, main)))
}
