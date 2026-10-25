package camoufox_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
)

func TestKeyboardShiftA(t *testing.T) {
	if os.Getenv("CAMOUFOX_BIN") == "" {
		t.Skip("set CAMOUFOX_BIN to run")
	}

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte(`<html><body><input id="inp" type="text"></body></html>`))
	}))
	defer srv.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	b, err := camoufox.Launch(ctx, camoufox.WithExecutablePath(os.Getenv("CAMOUFOX_BIN")), camoufox.WithHeadless(true))
	if err != nil {
		t.Fatalf("launch: %v", err)
	}
	defer b.Close()

	bc, err := b.NewContext(ctx)
	if err != nil {
		t.Fatalf("context: %v", err)
	}
	p, err := bc.NewPage(ctx)
	if err != nil {
		t.Fatalf("page: %v", err)
	}
	defer p.Close(ctx)

	if err := p.Goto(ctx, srv.URL); err != nil {
		t.Fatalf("goto: %v", err)
	}

	if err := p.Focus(ctx, "#inp"); err != nil {
		t.Fatalf("focus: %v", err)
	}

	kb := p.Keyboard()
	if err := kb.Down(ctx, "Shift"); err != nil {
		t.Fatalf("shift down: %v", err)
	}
	if err := kb.Press(ctx, "KeyA"); err != nil {
		t.Fatalf("press KeyA: %v", err)
	}
	if err := kb.Up(ctx, "Shift"); err != nil {
		t.Fatalf("shift up: %v", err)
	}

	val, err := p.Evaluate(ctx, "document.getElementById('inp').value")
	if err != nil {
		t.Fatalf("evaluate: %v", err)
	}
	if s, _ := val.(string); s != "A" {
		t.Errorf("expected input.value == %q, got %q", "A", s)
	}
}

// keyLogPage logs every keyboard event as type:key:code:keyCode and counts form submits.
const keyLogPage = `<html><body>
<form onsubmit="document.body.dataset.submitted=+(document.body.dataset.submitted||0)+1;return false">
<input id="a" autofocus><button>Go</button></form>
<script>
const log = [];
for (const t of ['keydown', 'keypress', 'keyup'])
  addEventListener(t, e => { log.push(t + ':' + e.key + ':' + e.code + ':' + e.keyCode); document.body.dataset.keys = log.join(' '); }, true);
</script></body></html>`

// keyLogKeyboard opens keyLogPage with #a focused and returns the page and its keyboard.
func keyLogKeyboard(t *testing.T) (*camoufox.Page, *camoufox.Keyboard, context.Context) {
	t.Helper()
	if os.Getenv("CAMOUFOX_BIN") == "" {
		t.Skip("set CAMOUFOX_BIN to run")
	}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte(keyLogPage))
	}))
	t.Cleanup(srv.Close)
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	t.Cleanup(cancel)
	b, err := camoufox.Launch(ctx, camoufox.WithExecutablePath(os.Getenv("CAMOUFOX_BIN")), camoufox.WithHeadless(true))
	if err != nil {
		t.Fatalf("launch: %v", err)
	}
	t.Cleanup(func() { _ = b.Close() })
	bc, err := b.NewContext(ctx)
	if err != nil {
		t.Fatalf("context: %v", err)
	}
	p, err := bc.NewPage(ctx)
	if err != nil {
		t.Fatalf("page: %v", err)
	}
	if err := p.Goto(ctx, srv.URL); err != nil {
		t.Fatalf("goto: %v", err)
	}
	if err := p.Focus(ctx, "#a"); err != nil {
		t.Fatalf("focus: %v", err)
	}
	return p, p.Keyboard(), ctx
}

func keyLogEval(t *testing.T, ctx context.Context, p *camoufox.Page, js string) string {
	t.Helper()
	v, err := p.Evaluate(ctx, js)
	if err != nil {
		t.Fatalf("evaluate %q: %v", js, err)
	}
	s, _ := v.(string)
	return s
}

// #297: a character the old table did not know dropped the rest of the text.
func TestKeyboardTypeWithDelayPunctuation(t *testing.T) {
	p, kb, ctx := keyLogKeyboard(t)
	for _, want := range []string{`a{b}c`, `A!@#()_+:"<>?~|`, "a€b\U0001F600c"} {
		keyLogEval(t, ctx, p, "document.getElementById('a').value = ''")
		if err := kb.Type(ctx, want, camoufox.WithDelay(5*time.Millisecond)); err != nil {
			t.Fatalf("Type(%q): %v", want, err)
		}
		if got := keyLogEval(t, ctx, p, "document.getElementById('a').value"); got != want {
			t.Errorf("Type(%q) wrote %q", want, got)
		}
	}
}

// #297: Press("{") reports the physical key, as Playwright's layout does.
func TestKeyboardPressBrace(t *testing.T) {
	p, kb, ctx := keyLogKeyboard(t)
	if err := kb.Press(ctx, "{"); err != nil {
		t.Fatalf("Press: %v", err)
	}
	log := keyLogEval(t, ctx, p, "document.body.dataset.keys")
	const want = "keydown:Shift:ShiftLeft:16 keydown:{:BracketLeft:219 keypress:{:BracketLeft:123 keyup:{:BracketLeft:219 keyup:Shift:ShiftLeft:16"
	if log != want {
		t.Errorf("event log\n got: %s\nwant: %s", log, want)
	}
}

// #298: Enter is a plain key, so the form submits and keyup arrives once.
func TestKeyboardPressEnter(t *testing.T) {
	p, kb, ctx := keyLogKeyboard(t)
	if err := kb.Press(ctx, "Enter"); err != nil {
		t.Fatalf("Press: %v", err)
	}
	// The submit is dispatched by the browser after Press returns: wait for it, with a deadline.
	for deadline := time.Now().Add(10 * time.Second); keyLogEval(t, ctx, p, "String(document.body.dataset.submitted)") != "1" && time.Now().Before(deadline); {
		time.Sleep(50 * time.Millisecond)
	}
	log := keyLogEval(t, ctx, p, "document.body.dataset.keys")
	const want = "keydown:Enter:Enter:13 keypress:Enter:Enter:13 keyup:Enter:Enter:13"
	if log != want {
		t.Errorf("event log\n got: %s\nwant: %s", log, want)
	}
	if got := keyLogEval(t, ctx, p, "String(document.body.dataset.submitted)"); got != "1" {
		t.Errorf("submitted = %s, want 1", got)
	}
}

// Playwright's own Firefox keyboard (playwright 1.58, same binary) logs this for type("a{b}c").
func TestKeyboardTypeLogMatchesPlaywright(t *testing.T) {
	p, kb, ctx := keyLogKeyboard(t)
	if err := kb.Type(ctx, "a{b}c", camoufox.WithDelay(5*time.Millisecond)); err != nil {
		t.Fatalf("Type: %v", err)
	}
	const want = "keydown:a:KeyA:65 keypress:a:KeyA:97 keyup:a:KeyA:65 " +
		"keydown:Shift:ShiftLeft:16 keydown:{:BracketLeft:219 keypress:{:BracketLeft:123 keyup:{:BracketLeft:219 keyup:Shift:ShiftLeft:16 " +
		"keydown:b:KeyB:66 keypress:b:KeyB:98 keyup:b:KeyB:66 " +
		"keydown:Shift:ShiftLeft:16 keydown:}:BracketRight:221 keypress:}:BracketRight:125 keyup:}:BracketRight:221 keyup:Shift:ShiftLeft:16 " +
		"keydown:c:KeyC:67 keypress:c:KeyC:99 keyup:c:KeyC:67"
	if got := keyLogEval(t, ctx, p, "document.body.dataset.keys"); got != want {
		t.Errorf("event log\n got: %s\nwant: %s", got, want)
	}
}

// Playwright sends keyCodeWithoutLocation, so Shift+Numpad7 reports 36, not shiftKeyCode 103.
func TestKeyboardShiftNumpadKeyCode(t *testing.T) {
	p, kb, ctx := keyLogKeyboard(t)
	if err := kb.Down(ctx, "Shift"); err != nil {
		t.Fatalf("Down: %v", err)
	}
	if err := kb.Press(ctx, "Numpad7"); err != nil {
		t.Fatalf("Press: %v", err)
	}
	if err := kb.Up(ctx, "Shift"); err != nil {
		t.Fatalf("Up: %v", err)
	}
	const want = "keydown:Shift:ShiftLeft:16 keydown:7:Numpad7:36 keypress:7:Numpad7:55 keyup:7:Numpad7:36 keyup:Shift:ShiftLeft:16"
	if got := keyLogEval(t, ctx, p, "document.body.dataset.keys"); got != want {
		t.Errorf("event log\n got: %s\nwant: %s", got, want)
	}
}
