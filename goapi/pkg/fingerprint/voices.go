package fingerprint

import (
	"bytes"
	_ "embed"
	"encoding/json"
	"fmt"
	"math/rand/v2"
	"slices"
	"strings"

	"github.com/lang315/camoufox/goapi/pkg/config"
)

// Copies of pythonlib's voice model, kept byte-identical by data_drift_test.go.
var (
	//go:embed data/voice-manifests.json
	rawVoiceManifests []byte
	//go:embed data/voice-uris.json
	rawVoiceURIs []byte
)

type voicePack struct {
	OneCore     []string `json:"oneCore"`
	Desktop     []string `json:"desktop"`
	DesktopProb float64  `json:"desktopProb"`
	Weight      float64  `json:"weight"`
}

type voiceAddition struct {
	Kind           string   `json:"kind"`
	Prob           float64  `json:"prob"`
	Deferred       bool     `json:"deferred"`
	RequiresLocale string   `json:"requiresLocale"`
	Voices         []string `json:"voices"`
	Groups         []string `json:"groups"`
	Sizes          []struct {
		N int     `json:"n"`
		W float64 `json:"w"`
	} `json:"sizes"`
}

type voiceManifest struct {
	Base           []string             `json:"base"`
	LangPacks      map[string]voicePack `json:"langPacks"`
	FallbackLocale string               `json:"fallbackLocale"`
	Additions      []voiceAddition      `json:"additions"`
	packOrder      []string             // langPacks keys in file order
}

var (
	voiceManifests = loadVoiceManifests()
	voiceURIs      = mustParse[map[string]map[string]string](rawVoiceURIs)
)

func loadVoiceManifests() map[string]voiceManifest {
	ms := mustParse[map[string]voiceManifest](rawVoiceManifests)
	// pythonlib falls back to the first language pack in file order, which a Go
	// map does not keep.
	raw := mustParse[map[string]struct {
		LangPacks json.RawMessage `json:"langPacks"`
	}](rawVoiceManifests)
	for k, m := range ms {
		m.packOrder = objectKeys(raw[k].LangPacks)
		ms[k] = m
	}
	return ms
}

// objectKeys returns a JSON object's keys in file order.
func objectKeys(raw json.RawMessage) []string {
	if len(raw) == 0 {
		return nil
	}
	dec := json.NewDecoder(bytes.NewReader(raw))
	var keys []string
	if _, err := dec.Token(); err != nil {
		panic("fingerprint: embedded data: " + err.Error())
	}
	for dec.More() {
		tok, err := dec.Token()
		if err != nil {
			panic("fingerprint: embedded data: " + err.Error())
		}
		keys = append(keys, tok.(string))
		var skip json.RawMessage
		if err := dec.Decode(&skip); err != nil {
			panic("fingerprint: embedded data: " + err.Error())
		}
	}
	return keys
}

// RandomVoices mirrors _generate_random_voice_subset
// (python/src/camoufox/fingerprints.py): the speech voices a stock machine of
// the OS exposes (voice-manifests.json). Windows: the display locale's OneCore
// pack, sometimes its legacy Desktop voices and extra packs; macOS: the
// compact and Eloquence base plus rare downloads; Linux: speech-dispatcher's
// espeak-ng list. No voice is the default: stock Firefox marks none.
func RandomVoices(targetOS, locale string, rng *rand.Rand) ([]config.Voice, error) {
	key := osKey(targetOS)
	m, ok := voiceManifests[key]
	if !ok {
		return nil, fmt.Errorf("fingerprint: no voice manifest for %q", key)
	}
	var out, legacy []string
	seen := map[string]bool{}
	add := func(entries []string) {
		for _, e := range entries {
			if !seen[e] {
				seen[e] = true
				out = append(out, e)
			}
		}
	}
	takePack := func(p voicePack) {
		add(p.OneCore)
		if len(p.Desktop) > 0 && rngFloat(rng) < p.DesktopProb {
			for _, e := range p.Desktop {
				if !slices.Contains(legacy, e) {
					legacy = append(legacy, e)
				}
			}
		}
	}

	add(m.Base)
	chosen := map[string]bool{}
	if len(m.LangPacks) > 0 {
		k := displayPack(m, locale)
		chosen[k] = true
		takePack(m.LangPacks[k])
	}
	for _, a := range m.Additions {
		if a.Deferred {
			continue
		}
		if a.RequiresLocale != "" && !strings.HasPrefix(strings.ToLower(locale), strings.ToLower(a.RequiresLocale)) {
			continue
		}
		if rngFloat(rng) >= a.Prob {
			continue
		}
		switch a.Kind {
		case "bundle":
			add(a.Voices)
		case "alacarte":
			n := 1
			if len(a.Sizes) > 0 {
				n = a.Sizes[weightedIndex(rng, len(a.Sizes), func(i int) float64 { return a.Sizes[i].W })].N
			}
			for _, e := range weightedSample(rng, a.Voices, n, func(string) float64 { return 1 }) {
				if seen[e] {
					continue
				}
				seen[e] = true
				// A downloaded voice sits in its alphabetical place.
				idx := slices.IndexFunc(out, func(v string) bool { return strings.ToLower(v) > strings.ToLower(e) })
				if idx < 0 {
					idx = len(out)
				}
				out = slices.Insert(out, idx, e)
			}
		case "groups":
			if len(m.LangPacks) == 0 {
				continue
			}
			var eligible []string
			for _, g := range a.Groups {
				if _, ok := m.LangPacks[g]; ok && !chosen[g] {
					eligible = append(eligible, g)
				}
			}
			if len(eligible) == 0 {
				continue
			}
			n := len(eligible)
			if len(a.Sizes) > 0 {
				n = a.Sizes[weightedIndex(rng, len(a.Sizes), func(i int) float64 { return a.Sizes[i].W })].N
			}
			weight := func(g string) float64 {
				if w := m.LangPacks[g].Weight; w != 0 {
					return w
				}
				return 0.01
			}
			for _, g := range weightedSample(rng, eligible, n, weight) {
				chosen[g] = true
				takePack(m.LangPacks[g])
			}
		}
	}

	voices := make([]config.Voice, 0, len(out)+len(legacy))
	for _, e := range append(out, legacy...) {
		name, lang, vtype := splitVoiceEntry(e)
		voices = append(voices, config.Voice{
			VoiceURI:       voiceURI(key, name, lang),
			Name:           name,
			Lang:           lang,
			IsLocalService: vtype == "local",
		})
	}
	return voices, nil
}

// displayPack is _resolve_display_pack: the locale's own pack, else the first
// pack of its language, else the manifest's fallback.
func displayPack(m voiceManifest, locale string) string {
	if locale != "" {
		if _, ok := m.LangPacks[locale]; ok {
			return locale
		}
		lang := strings.ToLower(strings.SplitN(locale, "-", 2)[0])
		for _, k := range m.packOrder {
			if strings.ToLower(strings.SplitN(k, "-", 2)[0]) == lang {
				return k
			}
		}
	}
	fallback := m.FallbackLocale
	if fallback == "" {
		fallback = "en-US"
	}
	if _, ok := m.LangPacks[fallback]; ok {
		return fallback
	}
	return m.packOrder[0]
}

// weightedIndex is _weighted_pick over n items.
func weightedIndex(rng *rand.Rand, n int, w func(int) float64) int {
	total := 0.0
	for i := range n {
		total += w(i)
	}
	r := rngFloat(rng) * total
	for i := range n {
		r -= w(i)
		if r <= 0 {
			return i
		}
	}
	return n - 1
}

// weightedSample is _weighted_sample: k items without replacement.
func weightedSample(rng *rand.Rand, items []string, k int, w func(string) float64) []string {
	pool := slices.Clone(items)
	var out []string
	for len(pool) > 0 && len(out) < k {
		i := weightedIndex(rng, len(pool), func(i int) float64 { return w(pool[i]) })
		out = append(out, pool[i])
		pool = slices.Delete(pool, i, i+1)
	}
	return out
}

// splitVoiceEntry splits a "Name:lang:type" entry from the right.
func splitVoiceEntry(e string) (name, lang, vtype string) {
	parts := strings.Split(e, ":")
	n := len(parts)
	return strings.Join(parts[:n-2], ":"), parts[n-2], parts[n-1]
}

// voiceURI is _voice_uri: the voiceURI real Firefox emits for the OS backend.
func voiceURI(key, name, lang string) string {
	switch key {
	case "lin":
		// SpeechDispatcherService.cpp: NS_EscapeURL(name, OnlyNonASCII|Spaces).
		var b strings.Builder
		for _, c := range []byte(name) {
			switch {
			case c == ' ':
				b.WriteString("%20")
			case c > 0x7f:
				fmt.Fprintf(&b, "%%%02X", c)
			default:
				b.WriteByte(c)
			}
		}
		return "urn:moz-tts:speechd:" + b.String() + "?" + lang
	case "win":
		// SapiService.cpp: the name verbatim.
		return "urn:moz-tts:sapi:" + name + "?" + lang
	}
	if uri, ok := voiceURIs["mac"][name+"|"+lang]; ok {
		return uri
	}
	// Outside the captured catalogue the identifier follows Apple's families.
	// pythonlib NFKD-folds the name first; every such name is ASCII
	// (TestMacVoicesOutsideTheCatalogueAreASCII), so dropping the rest matches.
	ascii := strings.Map(func(r rune) rune {
		if r < 0x80 && (r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9') {
			return r
		}
		return -1
	}, name)
	switch {
	case slices.Contains(launcher.MacNoveltyVoices, name):
		return "urn:moz-tts:osx:com.apple.speech.synthesis.voice." + ascii
	case slices.Contains(launcher.MacEloquenceVoices, name):
		return "urn:moz-tts:osx:com.apple.eloquence." + lang + "." + ascii
	}
	return "urn:moz-tts:osx:com.apple.voice.compact." + lang + "." + ascii
}
