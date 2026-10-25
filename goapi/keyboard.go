package camoufox

import (
	"context"
	"fmt"
	"time"

	"github.com/lang315/camoufox/goapi/pkg/juggler"
)

// Keyboard provides low-level key event dispatch. Obtain via Page.Keyboard().
type Keyboard struct {
	page      *Page
	modifiers map[string]bool // Alt, Control, Meta, Shift currently down
	pressed   map[string]bool // codes currently down, to flag auto-repeat
}

// Keyboard returns the Keyboard helper for this page.
func (p *Page) Keyboard() *Keyboard {
	return &Keyboard{page: p, modifiers: map[string]bool{}, pressed: map[string]bool{}}
}

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

// Down sends a keydown event for the key.
// key is a layout code ("KeyA", "Enter", "ArrowLeft"), a key value ("a", "{", "Shift"), or "\n".
// An unknown key is an error. Shift state is tracked so a later key reports its shifted value.
func (k *Keyboard) Down(ctx context.Context, key string) error {
	d, err := k.describe(key)
	if err != nil {
		return err
	}
	repeat := k.pressed[d.code]
	k.pressed[d.code] = true
	if modifierKeys[d.key] {
		k.modifiers[d.key] = true
	}
	// Firefox derives the Enter keypress itself; text "\r" would route the keydown through
	// IME composition (key "Process", keyCode 229) and skip form submission.
	text := d.text
	if text == "\r" {
		text = ""
	}
	params := juggler.PageDispatchKeyEventParams{
		Type:     "keydown",
		Key:      d.key,
		Code:     d.code,
		KeyCode:  d.keyCode,
		Location: d.location,
		Repeat:   repeat,
		Text:     text,
	}
	if err := k.page.session.Call(ctx, "Page.dispatchKeyEvent", params, nil); err != nil {
		return fmt.Errorf("camoufox: key Down %q: %w", key, err)
	}
	return nil
}

// Up sends a keyup event for the key.
func (k *Keyboard) Up(ctx context.Context, key string) error {
	d, err := k.describe(key)
	if err != nil {
		return err
	}
	if modifierKeys[d.key] {
		delete(k.modifiers, d.key)
	}
	delete(k.pressed, d.code)
	params := juggler.PageDispatchKeyEventParams{
		Type:     "keyup",
		Key:      d.key,
		Code:     d.code,
		KeyCode:  d.keyCode,
		Location: d.location,
	}
	if err := k.page.session.Call(ctx, "Page.dispatchKeyEvent", params, nil); err != nil {
		return fmt.Errorf("camoufox: key Up %q: %w", key, err)
	}
	return nil
}

// Press sends keydown then keyup for the key.
func (k *Keyboard) Press(ctx context.Context, key string) error {
	if err := k.Down(ctx, key); err != nil {
		return err
	}
	return k.Up(ctx, key)
}

// Type inserts text. Fast path uses Page.insertText (one round-trip).
// If Delay option is set, a character in the US layout is pressed as a key and any other
// character (CJK, emoji) is inserted as text, as Playwright's Keyboard.type does.
func (k *Keyboard) Type(ctx context.Context, text string, opts ...TypeOption) error {
	o := typeOpts{}
	for _, fn := range opts {
		fn(&o)
	}
	if o.delay == 0 {
		return k.insertText(ctx, text)
	}
	for _, ch := range text {
		var err error
		if _, ok := layout[string(ch)]; ok {
			err = k.Press(ctx, string(ch))
		} else {
			err = k.insertText(ctx, string(ch))
		}
		if err != nil {
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

func (k *Keyboard) insertText(ctx context.Context, text string) error {
	return k.page.session.Call(ctx, "Page.insertText", map[string]any{"text": text}, nil)
}

var modifierKeys = map[string]bool{"Alt": true, "Control": true, "Meta": true, "Shift": true}

// keyDesc is the protocol description of one key, as built by playwright-core's buildLayoutClosure.
type keyDesc struct {
	key, code string
	keyCode   int // sent to the browser: the layout's keyCodeWithoutLocation when it has one
	location  int
	text      string
	shifted   *keyDesc
}

// layout resolves a code ("KeyA"), a key value ("a", "{") or an alias ("Shift", "\n") to its description.
var layout = buildLayout()

func buildLayout() map[string]keyDesc {
	aliases := map[string][]string{
		"ShiftLeft": {"Shift"}, "ControlLeft": {"Control"}, "AltLeft": {"Alt"}, "MetaLeft": {"Meta"},
		"Enter": {"\n", "\r"},
	}
	m := map[string]keyDesc{}
	for _, def := range usLayout {
		d := keyDesc{key: def.key, code: def.code, keyCode: def.keyCode, location: def.location, text: def.text}
		if def.keyCodeNoLoc != 0 {
			d.keyCode = def.keyCodeNoLoc
		}
		if len([]rune(def.key)) == 1 {
			d.text = def.key
		}
		var shifted *keyDesc
		if def.shiftKey != "" {
			s := d
			s.key, s.text = def.shiftKey, def.shiftKey
			if def.shiftKeyCode != 0 {
				s.keyCode = def.shiftKeyCode
			}
			shifted = &s
		}
		withShift := d
		withShift.shifted = shifted
		m[def.code] = withShift
		for _, a := range aliases[def.code] {
			m[a] = d
		}
		if def.location != 0 {
			continue
		}
		if len([]rune(d.key)) == 1 {
			m[d.key] = d
		}
		if shifted != nil {
			m[shifted.key] = *shifted
		}
	}
	return m
}

// describe returns the description for key under the modifiers held now.
func (k *Keyboard) describe(key string) (keyDesc, error) {
	d, ok := layout[key]
	if !ok {
		return keyDesc{}, fmt.Errorf("camoufox: unknown key %q", key)
	}
	shift := k.modifiers["Shift"]
	if shift && d.shifted != nil {
		d = *d.shifted
	}
	if len(k.modifiers) > 1 || (!shift && len(k.modifiers) == 1) {
		d.text = ""
	}
	return d, nil
}
