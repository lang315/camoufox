package camoufox

import (
	"context"
	"fmt"
	"time"

	"github.com/lang315/camoufox/goapi/pkg/juggler"
)

// Keyboard provides low-level key event dispatch. Obtain via Page.Keyboard().
type Keyboard struct {
	page     *Page
	shiftHeld bool // tracks whether Shift is currently down
}

// Keyboard returns the Keyboard helper for this page.
func (p *Page) Keyboard() *Keyboard { return &Keyboard{page: p} }

// TypeOption configures Keyboard.Type.
type TypeOption func(*typeOpts)

type typeOpts struct {
	delay time.Duration
}

// WithDelay adds an inter-character delay for Keyboard.Type.
// When set, the slow path (per-char dispatchKeyEvent) is used.
func WithDelay(d time.Duration) TypeOption {
	return func(o *typeOpts) { o.delay = d }
}

// Down sends a keydown event for the named key.
// key may be a single character (e.g. "a") or a named key (e.g. "Shift", "Enter").
// Tracks Shift state so subsequent Down/Press calls compose the correct shifted character.
func (k *Keyboard) Down(ctx context.Context, key string) error {
	if key == "Shift" {
		k.shiftHeld = true
	}
	info := resolveKey(key)
	// Send text only for printable chars; shift-held state shifts the inserted character.
	text := info.text
	if k.shiftHeld && len(text) == 1 {
		text = shiftChar(text)
	}
	params := juggler.PageDispatchKeyEventParams{
		Type:    "keydown",
		Key:     info.key,
		Code:    info.code,
		KeyCode: info.keyCode,
		Text:    text,
	}
	if err := k.page.session.Call(ctx, "Page.dispatchKeyEvent", params, nil); err != nil {
		return fmt.Errorf("camoufox: key Down %q: %w", key, err)
	}
	return nil
}

// Up sends a keyup event for the named key.
func (k *Keyboard) Up(ctx context.Context, key string) error {
	if key == "Shift" {
		k.shiftHeld = false
	}
	info := resolveKey(key)
	params := juggler.PageDispatchKeyEventParams{
		Type:    "keyup",
		Key:     info.key,
		Code:    info.code,
		KeyCode: info.keyCode,
	}
	if err := k.page.session.Call(ctx, "Page.dispatchKeyEvent", params, nil); err != nil {
		return fmt.Errorf("camoufox: key Up %q: %w", key, err)
	}
	return nil
}

// Press sends keydown then keyup for the named key.
func (k *Keyboard) Press(ctx context.Context, key string) error {
	if err := k.Down(ctx, key); err != nil {
		return err
	}
	return k.Up(ctx, key)
}

// Type inserts text. Fast path uses Page.insertText (one round-trip).
// If Delay option is set, falls back to per-character dispatchKeyEvent.
func (k *Keyboard) Type(ctx context.Context, text string, opts ...TypeOption) error {
	o := typeOpts{}
	for _, fn := range opts {
		fn(&o)
	}
	if o.delay == 0 {
		return k.page.session.Call(ctx, "Page.insertText", map[string]any{"text": text}, nil)
	}
	for _, ch := range text {
		if err := k.Press(ctx, string(ch)); err != nil {
			return err
		}
		select {
		case <-time.After(o.delay):
		case <-ctx.Done():
			return ctx.Err()
		}
	}
	return nil
}

// keyInfo holds the protocol fields for a single key.
type keyInfo struct {
	key     string
	code    string
	keyCode int
	text    string
}

// namedKeys maps user-visible names → protocol fields.
// Modifier keys and common named keys. Single chars are handled by charKeys.
var namedKeys = map[string]keyInfo{
	"Backspace":   {"Backspace", "Backspace", 8, ""},
	"Tab":         {"Tab", "Tab", 9, ""},
	"Enter":       {"Enter", "Enter", 13, "\r"},
	"Escape":      {"Escape", "Escape", 27, ""},
	"Space":       {" ", "Space", 32, " "},
	"Delete":      {"Delete", "Delete", 46, ""},
	"Insert":      {"Insert", "Insert", 45, ""},
	"Home":        {"Home", "Home", 36, ""},
	"End":         {"End", "End", 35, ""},
	"PageUp":      {"PageUp", "PageUp", 33, ""},
	"PageDown":    {"PageDown", "PageDown", 34, ""},
	"ArrowUp":     {"ArrowUp", "ArrowUp", 38, ""},
	"ArrowDown":   {"ArrowDown", "ArrowDown", 40, ""},
	"ArrowLeft":   {"ArrowLeft", "ArrowLeft", 37, ""},
	"ArrowRight":  {"ArrowRight", "ArrowRight", 39, ""},
	"Shift":       {"Shift", "ShiftLeft", 16, ""},
	"Control":     {"Control", "ControlLeft", 17, ""},
	"Alt":         {"Alt", "AltLeft", 18, ""},
	"Meta":        {"Meta", "MetaLeft", 91, ""},
	"CapsLock":    {"CapsLock", "CapsLock", 20, ""},
	"F1":          {"F1", "F1", 112, ""},
	"F2":          {"F2", "F2", 113, ""},
	"F3":          {"F3", "F3", 114, ""},
	"F4":          {"F4", "F4", 115, ""},
	"F5":          {"F5", "F5", 116, ""},
	"F6":          {"F6", "F6", 117, ""},
	"F7":          {"F7", "F7", 118, ""},
	"F8":          {"F8", "F8", 119, ""},
	"F9":          {"F9", "F9", 120, ""},
	"F10":         {"F10", "F10", 121, ""},
	"F11":         {"F11", "F11", 122, ""},
	"F12":         {"F12", "F12", 123, ""},
	"KeyA":        {"a", "KeyA", 65, "a"},
	"KeyB":        {"b", "KeyB", 66, "b"},
	"KeyC":        {"c", "KeyC", 67, "c"},
	"KeyD":        {"d", "KeyD", 68, "d"},
	"KeyE":        {"e", "KeyE", 69, "e"},
	"KeyF":        {"f", "KeyF", 70, "f"},
	"KeyG":        {"g", "KeyG", 71, "g"},
	"KeyH":        {"h", "KeyH", 72, "h"},
	"KeyI":        {"i", "KeyI", 73, "i"},
	"KeyJ":        {"j", "KeyJ", 74, "j"},
	"KeyK":        {"k", "KeyK", 75, "k"},
	"KeyL":        {"l", "KeyL", 76, "l"},
	"KeyM":        {"m", "KeyM", 77, "m"},
	"KeyN":        {"n", "KeyN", 78, "n"},
	"KeyO":        {"o", "KeyO", 79, "o"},
	"KeyP":        {"p", "KeyP", 80, "p"},
	"KeyQ":        {"q", "KeyQ", 81, "q"},
	"KeyR":        {"r", "KeyR", 82, "r"},
	"KeyS":        {"s", "KeyS", 83, "s"},
	"KeyT":        {"t", "KeyT", 84, "t"},
	"KeyU":        {"u", "KeyU", 85, "u"},
	"KeyV":        {"v", "KeyV", 86, "v"},
	"KeyW":        {"w", "KeyW", 87, "w"},
	"KeyX":        {"x", "KeyX", 88, "x"},
	"KeyY":        {"y", "KeyY", 89, "y"},
	"KeyZ":        {"z", "KeyZ", 90, "z"},
	"Digit0":      {"0", "Digit0", 48, "0"},
	"Digit1":      {"1", "Digit1", 49, "1"},
	"Digit2":      {"2", "Digit2", 50, "2"},
	"Digit3":      {"3", "Digit3", 51, "3"},
	"Digit4":      {"4", "Digit4", 52, "4"},
	"Digit5":      {"5", "Digit5", 53, "5"},
	"Digit6":      {"6", "Digit6", 54, "6"},
	"Digit7":      {"7", "Digit7", 55, "7"},
	"Digit8":      {"8", "Digit8", 56, "8"},
	"Digit9":      {"9", "Digit9", 57, "9"},
}

// charKeyCode maps printable runes to keyCode (Windows virtual key code).
var charKeyCode = map[rune]int{
	' ': 32, '0': 48, '1': 49, '2': 50, '3': 51, '4': 52, '5': 53,
	'6': 54, '7': 55, '8': 56, '9': 57,
	'a': 65, 'b': 66, 'c': 67, 'd': 68, 'e': 69, 'f': 70, 'g': 71,
	'h': 72, 'i': 73, 'j': 74, 'k': 75, 'l': 76, 'm': 77, 'n': 78,
	'o': 79, 'p': 80, 'q': 81, 'r': 82, 's': 83, 't': 84, 'u': 85,
	'v': 86, 'w': 87, 'x': 88, 'y': 89, 'z': 90,
	'A': 65, 'B': 66, 'C': 67, 'D': 68, 'E': 69, 'F': 70, 'G': 71,
	'H': 72, 'I': 73, 'J': 74, 'K': 75, 'L': 76, 'M': 77, 'N': 78,
	'O': 79, 'P': 80, 'Q': 81, 'R': 82, 'S': 83, 'T': 84, 'U': 85,
	'V': 86, 'W': 87, 'X': 88, 'Y': 89, 'Z': 90,
	'\r': 13, '\t': 9, '\b': 8,
}

// resolveKey converts a user-visible key name or single character to keyInfo.
func resolveKey(key string) keyInfo {
	if info, ok := namedKeys[key]; ok {
		return info
	}
	runes := []rune(key)
	if len(runes) == 1 {
		r := runes[0]
		kc := charKeyCode[r]
		return keyInfo{key: string(r), code: codeForRune(r), keyCode: kc, text: string(r)}
	}
	return keyInfo{key: key, code: key, keyCode: 0}
}

// shiftChar returns the Shift-modified version of a single-character string.
func shiftChar(s string) string {
	if len(s) != 1 {
		return s
	}
	r := rune(s[0])
	if r >= 'a' && r <= 'z' {
		return string(r - 32)
	}
	shifted := map[rune]rune{
		'1': '!', '2': '@', '3': '#', '4': '$', '5': '%',
		'6': '^', '7': '&', '8': '*', '9': '(', '0': ')',
		'-': '_', '=': '+', '[': '{', ']': '}', '\\': '|',
		';': ':', '\'': '"', ',': '<', '.': '>', '/': '?',
		'`': '~',
	}
	if v, ok := shifted[r]; ok {
		return string(v)
	}
	return s
}

// codeForRune returns a best-effort code string for a printable rune.
func codeForRune(r rune) string {
	if r >= 'a' && r <= 'z' {
		return "Key" + string(r-32)
	}
	if r >= 'A' && r <= 'Z' {
		return "Key" + string(r)
	}
	if r >= '0' && r <= '9' {
		return "Digit" + string(r)
	}
	if r == ' ' {
		return "Space"
	}
	return "Unidentified"
}
