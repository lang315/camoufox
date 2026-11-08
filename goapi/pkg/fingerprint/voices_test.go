package fingerprint

import (
	"math/rand/v2"
	"slices"
	"testing"

	"github.com/lang315/camoufox/goapi/pkg/config"
)

// The values pythonlib's _voice_uri returns for the same inputs.
func TestVoiceURIMatchesPythonlib(t *testing.T) {
	for _, c := range []struct{ key, name, lang, want string }{
		{"lin", "Bishnupriya Manipuri", "bpy", "urn:moz-tts:speechd:Bishnupriya%20Manipuri?bpy"},
		{"lin", "Chinese (Mandarin, latin as English)", "cmn", "urn:moz-tts:speechd:Chinese%20(Mandarin,%20latin%20as%20English)?cmn"},
		{"lin", "Ünï Vóice", "de", "urn:moz-tts:speechd:%C3%9Cn%C3%AF%20V%C3%B3ice?de"},
		{"win", "Microsoft David - English (United States)", "en-US", "urn:moz-tts:sapi:Microsoft David - English (United States)?en-US"},
		{"mac", "Samantha", "en-US", "urn:moz-tts:osx:com.apple.voice.compact.en-US.Samantha"},
		{"mac", "Alex", "en-US", "urn:moz-tts:osx:com.apple.speech.synthesis.voice.Alex"},
		{"mac", "Agnes", "en-US", "urn:moz-tts:osx:com.apple.speech.synthesis.voice.Agnes"},
		{"mac", "Eddy", "de-DE", "urn:moz-tts:osx:com.apple.eloquence.de-DE.Eddy"},
		{"mac", "Zzz Test", "fr-FR", "urn:moz-tts:osx:com.apple.voice.compact.fr-FR.ZzzTest"},
	} {
		if got := voiceURI(c.key, c.name, c.lang); got != c.want {
			t.Errorf("voiceURI(%s, %q, %s) = %q, want %q", c.key, c.name, c.lang, got, c.want)
		}
	}
}

// pythonlib NFKD-folds a mac name outside the catalogue; voiceURI only drops
// non-ASCII letters, which is the same while every such name is ASCII.
func TestMacVoicesOutsideTheCatalogueAreASCII(t *testing.T) {
	m := voiceManifests["mac"]
	entries := slices.Clone(m.Base)
	for _, a := range m.Additions {
		entries = append(entries, a.Voices...)
	}
	for _, e := range entries {
		name, lang, _ := splitVoiceEntry(e)
		if _, ok := voiceURIs["mac"][name+"|"+lang]; ok {
			continue
		}
		for _, r := range name {
			if r > 0x7f {
				t.Errorf("mac voice %q is outside voice-uris.json and not ASCII: port the NFKD fold", name)
			}
		}
	}
}

// Every draw holds the OS's base; only the manifest's system voice is the
// default (macOS marks Samantha, Windows and Linux none); Windows follows the
// display locale's pack (#185).
func TestVoicesFollowTheManifest(t *testing.T) {
	rng := rand.New(rand.NewPCG(21, 22))
	for _, c := range []struct{ os, locale, must string }{
		{"windows", "en-US", "Microsoft David - English (United States)"},
		{"windows", "fr-FR", "Microsoft Hortense - French (France)"},
		{"windows", "", "Microsoft Zira - English (United States)"},
		{"macos", "en-US", "Samantha"},
		{"linux", "en-US", "Bishnupriya Manipuri"},
	} {
		base := voiceManifests[osKey(c.os)].Base
		for i := range 100 {
			voices, err := RandomVoices(c.os, c.locale, rng)
			if err != nil {
				t.Fatal(err)
			}
			names := map[string]bool{}
			system := voiceManifests[osKey(c.os)].SystemVoice.Default
			defaults := 0
			for _, v := range voices {
				if v.IsDefault {
					defaults++
					if v.Name != system {
						t.Fatalf("%s draw %d: %q is marked default; only %q may be", c.os, i, v.Name, system)
					}
				}
				if names[v.Name+"|"+v.Lang] {
					t.Fatalf("%s draw %d: %q twice", c.os, i, v.Name)
				}
				names[v.Name+"|"+v.Lang] = true
			}
			if want := map[bool]int{true: 1, false: 0}[system != ""]; defaults != want {
				t.Fatalf("%s draw %d: %d default voices, want %d", c.os, i, defaults, want)
			}
			for _, e := range base {
				name, lang, _ := splitVoiceEntry(e)
				if !names[name+"|"+lang] {
					t.Fatalf("%s draw %d: base voice %q missing", c.os, i, name)
				}
			}
			if !names[c.must+"|"+langOf(t, c.os, c.must)] {
				t.Fatalf("%s %q draw %d: %q missing", c.os, c.locale, i, c.must)
			}
		}
	}
}

func langOf(t *testing.T, os, name string) string {
	m := voiceManifests[osKey(os)]
	all := slices.Clone(m.Base)
	for _, p := range m.LangPacks {
		all = append(all, p.OneCore...)
	}
	for _, r := range m.Releases {
		for _, l := range r.Speechd.Languages {
			if l[0] == name {
				return l[1]
			}
		}
	}
	for _, e := range all {
		if n, l, _ := splitVoiceEntry(e); n == name {
			return l
		}
	}
	t.Fatalf("%q is in no %s base or pack", name, os)
	return ""
}

// A Linux identity's voices are its release's grid, from the release its fonts
// were drawn from: the language alone, then with every variant.
func TestLinuxVoicesAreTheReleasesSpeechdGrid(t *testing.T) {
	for id, r := range voiceManifests["lin"].Releases {
		voices := ExpandSpeechdGrid(r.Speechd)
		if want := len(r.Speechd.Languages) * (1 + len(r.Speechd.Variants)); len(voices) != want {
			t.Errorf("%s: %d voices, want %d", id, len(voices), want)
		}
		if voices[0].Name != r.Speechd.Languages[0][0] || voices[1].Name != r.Speechd.Languages[0][0]+"+"+r.Speechd.Variants[0] {
			t.Errorf("%s: voices are not in speech-dispatcher's order: %q, %q", id, voices[0].Name, voices[1].Name)
		}
	}
	rng := rand.New(rand.NewPCG(3, 4))
	for range 50 {
		var cfg config.Config
		if err := Generate(&cfg, Options{OS: "linux", Rand: rng, HostOS: "linux"}); err != nil {
			t.Fatal(err)
		}
		if cfg.VoicesSpeechd == nil || len(cfg.Voices) != 0 {
			t.Fatalf("a Linux identity carries the speechd grid and no voice list: %+v", cfg.VoicesSpeechd == nil)
		}
	}
}
