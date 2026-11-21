package myuri

import (
	"errors"
	"math"
	"strings"
	"unicode/utf16"
)

// What a typist presses on the way to the text (typing/markov.ts, keyboard.ts,
// language.ts, config.ts), from HumanTyping (https://github.com/Lax3n/HumanTyping):
// neighbour-key slips, swaps, and backspace corrections. It has no notion of
// time; typing_timing.go schedules the keys.

const (
	defaultWPM            = 80
	wpmSD                 = 10 // session-to-session spread of a typist's speed
	probError             = 0.04
	probSwapError         = 0.015
	probNoticeError       = 0.85
	driftCorrectionProb   = 0.8
	complexWordErrorMult  = 1.5
	commonWordErrorMult   = 0.5
	composedAccentErrMult = 2.0
	// wordBoundaryChars trigger a strict correction check.
	wordBoundaryChars = " \n\t.,;!?:()[]{}<>\"'"
)

// jsLen is a string's JS .length: UTF-16 code units.
func jsLen(s string) int { return len(utf16.Encode([]rune(s))) }

// ---- keyboard layout ----

var keyGrid = [][]string{
	strings.Split("`1234567890-=", ""),
	strings.Split("qwertyuiop[]\\", ""),
	strings.Split("asdfghjkl;'", ""),
	strings.Split("zxcvbnm,./", ""),
}

var keyPos = func() map[string][2]int {
	m := map[string][2]int{}
	for r, row := range keyGrid {
		for c, k := range row {
			m[k] = [2]int{r, c}
		}
	}
	return m
}()

// composedAccents are the accented letters typed as their base key (NFD minus the marks).
var composedAccents = map[string]string{
	"â": "a", "ê": "e", "î": "i", "ô": "o", "û": "u", "ä": "a", "ë": "e", "ï": "i",
	"ö": "o", "ü": "u", "é": "e", "è": "e", "à": "a", "ù": "u", "ç": "c",
}

// jsLower is String.toLowerCase for one character; Go maps İ (U+0130) to a plain i.
func jsLower(c string) string {
	if c == "İ" {
		return "i̇"
	}
	return strings.ToLower(c)
}

func normalizeChar(c string) string {
	c = jsLower(c)
	if base, ok := composedAccents[c]; ok {
		return base
	}
	return c
}

func hasKey(c string) bool {
	_, ok := keyPos[normalizeChar(c)]
	return ok
}

func neighborKeys(c string) []string {
	pos, ok := keyPos[normalizeChar(c)]
	if !ok {
		return nil
	}
	var out []string
	for _, d := range [8][2]int{{-1, -1}, {-1, 0}, {-1, 1}, {0, -1}, {0, 1}, {1, -1}, {1, 0}, {1, 1}} {
		nr, nc := pos[0]+d[0], pos[1]+d[1]
		if nr >= 0 && nr < len(keyGrid) && nc >= 0 && nc < len(keyGrid[nr]) {
			out = append(out, keyGrid[nr][nc])
		}
	}
	return out
}

func randomNeighbor(c string, rng RNG) string {
	wasUpper := c == strings.ToUpper(c) && c != jsLower(c)
	var result string
	if neighbors := neighborKeys(c); len(neighbors) == 0 {
		var flat []string
		for _, row := range keyGrid {
			flat = append(flat, row...)
		}
		result = flat[int(math.Floor(rng()*float64(len(flat))))]
	} else {
		result = neighbors[int(math.Floor(rng()*float64(len(neighbors))))]
	}
	if wasUpper {
		return strings.ToUpper(result)
	}
	return result
}

func isComposedAccent(c string) bool {
	_, ok := composedAccents[jsLower(c)]
	return ok
}

// ---- word difficulty ----

var commonWords = func() map[string]bool {
	m := map[string]bool{}
	for _, w := range strings.Fields(
		"the be to of and a in that have it for not on with he as you do at this but his by from " +
			"they we say her she or an will my one all would there their what so up out if about who " +
			"get which go me when make can like time no just him know take people into year your good " +
			"some could them see other than then now look only come its over think also back after use " +
			"two how our work first well way even new want because any these give day most us great " +
			"been has had was were are did find here thing many much long too same right old big little " +
			"world school still try last ask need hand high keep place start far turn away off left " +
			"while might again does man call house point being end help show why home kind read life " +
			"run move live play open let put set late three four five small large part made men few " +
			"next found name word close city side along under went got near real money both head white " +
			"line state night sure began once change water face door since used best until more where " +
			"going really done enough yet another upon saw around always together often those own very " +
			"down such each every before must through between should may tell never stop mean hard hold " +
			"full seem light hear second room body young group without leave table number story above " +
			"below care class early feel girl boy love food book form able idea free less case eye game " +
			"air ago half power plan week today true") {
		m[w] = true
	}
	return m
}()

func stripPunctuation(word string) string {
	const punct = ".,!?;:'\"-()[]{}/"
	return strings.TrimFunc(word, func(r rune) bool { return strings.ContainsRune(punct, r) })
}

// wordDifficulty drives how often a word is mistyped.
func wordDifficulty(word string) string {
	w := stripPunctuation(strings.ToLower(word))
	if commonWords[w] {
		return "common"
	}
	if jsLen(w) > 8 || strings.ContainsAny(w, "zxqj") {
		return "complex"
	}
	return "normal"
}

// ---- the typist ----

type typeEvent struct{ kind, chars string }

type markov struct {
	target   []rune // by code point, so an emoji is one unit and never split
	mistakes float64
	rng      RNG

	current      []rune
	history      []typeEvent
	lastKind     string
	mentalCursor int
}

func newMarkov(text string, mistakeMultiplier float64, rng RNG) (*markov, error) {
	if text == "" {
		return nil, errors.New("myuri: targetText must be a non-empty string")
	}
	return &markov{target: []rune(text), mistakes: mistakeMultiplier, rng: rng}, nil
}

func (m *markov) complete() bool {
	if len(m.current) != len(m.target) {
		return false
	}
	for i, r := range m.current {
		if r != m.target[i] {
			return false
		}
	}
	return true
}

// wordContext is the space-delimited word around the mental cursor.
func (m *markov) wordContext() (string, bool) {
	idx := m.mentalCursor
	if idx >= len(m.target) {
		return "", false
	}
	start, end := idx, idx
	for start > 0 && m.target[start-1] != ' ' {
		start--
	}
	for end < len(m.target) && m.target[end] != ' ' {
		end++
	}
	return string(m.target[start:end]), true
}

func (m *markov) advance(r rune) {
	m.current = append(m.current, r)
	m.mentalCursor++
}

func (m *markov) emit(r rune, kind string) *typeEvent {
	m.advance(r)
	return m.record(string(r), kind)
}

func (m *markov) record(chars, kind string) *typeEvent {
	m.history = append(m.history, typeEvent{kind, chars})
	m.lastKind = kind
	return &m.history[len(m.history)-1]
}

// step is one keystroke, or nil once the text is complete.
func (m *markov) step() *typeEvent {
	if m.complete() {
		return nil
	}
	n := len(m.current)
	// Monitoring and correction: where does what is typed first differ from the target?
	firstError := len(m.target)
	for i := 0; i < min(n, len(m.target)); i++ {
		if m.current[i] != m.target[i] {
			firstError = i
			break
		}
	}
	if firstError < n {
		shouldCorrect := false
		switch {
		case m.lastKind == "backspace": // continued backspacing
			shouldCorrect = true
		case m.mentalCursor >= len(m.target): // end of text: always correct
			shouldCorrect = true
		case n > 0:
			last := m.current[n-1]
			distance := n - firstError
			switch {
			case strings.ContainsRune(wordBoundaryChars, last): // strict at word boundaries
				shouldCorrect = true
			case distance >= 2: // don't let errors linger
				shouldCorrect = m.rng() < driftCorrectionProb
			case distance == 1: // immediate reaction
				shouldCorrect = m.rng() < probNoticeError
			}
		}
		if shouldCorrect {
			m.current = m.current[:n-1]
			ev := m.record("", "backspace")
			m.mentalCursor = len(m.current)
			return ev
		}
	}
	// Typing.
	if m.mentalCursor > len(m.current) {
		m.mentalCursor = len(m.current)
	}
	if m.mentalCursor >= len(m.target) {
		return nil
	}
	intended := m.target[m.mentalCursor]
	// A character not on the keyboard is typed literally, with no error modelling.
	if !hasKey(string(intended)) && intended != ' ' {
		return m.emit(intended, "type")
	}
	// Swap error (anticipation): "the" -> "hte".
	if len(m.target) > m.mentalCursor+1 {
		after := m.target[m.mentalCursor+1]
		if after != ' ' && after != intended {
			if m.rng() < math.Min(1, probSwapError*m.mistakes) {
				m.advance(after)
				m.advance(intended)
				return m.record(string(after)+string(intended), "swap")
			}
		}
	}
	// Normal typing, success or slip.
	p := probError * m.mistakes
	word, _ := m.wordContext()
	switch wordDifficulty(word) {
	case "complex":
		p *= complexWordErrorMult
	case "common":
		p *= commonWordErrorMult
	}
	if isComposedAccent(string(intended)) {
		p *= composedAccentErrMult
	}
	p = math.Min(1, p)
	if m.rng() < p {
		return m.emit([]rune(randomNeighbor(string(intended), m.rng))[0], "error")
	}
	return m.emit(intended, "type")
}

func (m *markov) runSteps(budget int) {
	for steps := 0; m.step() != nil; {
		steps++
		if steps > budget {
			break
		}
	}
}

// run types the text. If the step cap leaves it wrong, the budget is extended
// once, then the diverged run is discarded for a pass that types the target
// exactly, so the history never reconstructs to the wrong text.
func (m *markov) run() []typeEvent {
	budget := len(m.target) * 10
	m.runSteps(budget)
	if !m.complete() {
		m.runSteps(budget)
	}
	if !m.complete() {
		m.current, m.history, m.lastKind, m.mentalCursor = nil, nil, "", 0
		for _, r := range m.target {
			m.emit(r, "correct")
		}
	}
	return m.history
}
