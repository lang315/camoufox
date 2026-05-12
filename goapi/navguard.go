package camoufox

import (
	"context"
	"fmt"
	"strings"
	"time"
)

// NavGuardOptions controls NavigateGuarded behaviour.
type NavGuardOptions struct {
	// ExpectedURLs: navigation succeeds if the final URL contains any of these
	// substrings. Empty means any URL is accepted.
	ExpectedURLs []string
	// AllowedRedirects: intermediate redirect URLs that are explicitly permitted
	// even if they don't match ExpectedURLs.
	AllowedRedirects []string
	// MaxAttempts: total navigation attempts before giving up. Default 1.
	MaxAttempts int
	// Backoff: sleep between retry attempts. Default 0.
	Backoff time.Duration
	// BotWallTitles: page titles that indicate a bot-detection interstitial
	// (e.g. "Just a moment...", "Checking your browser"). When matched,
	// NavigateGuarded waits Backoff and rechecks up to MaxAttempts times.
	BotWallTitles []string
}

// NavigateGuarded navigates to url and verifies the final URL and page title
// satisfy the constraints in opts. Retries on mismatch up to MaxAttempts.
func (p *Page) NavigateGuarded(ctx context.Context, url string, opts NavGuardOptions) error {
	if opts.MaxAttempts <= 0 {
		opts.MaxAttempts = 1
	}

	var lastErr error
	for attempt := 0; attempt < opts.MaxAttempts; attempt++ {
		if attempt > 0 && opts.Backoff > 0 {
			select {
			case <-time.After(opts.Backoff):
			case <-ctx.Done():
				return ctx.Err()
			}
		}

		if err := p.Goto(ctx, url); err != nil {
			lastErr = fmt.Errorf("camoufox: NavigateGuarded goto: %w", err)
			continue
		}

		// Read current URL and title.
		currentURL, err := p.evalString(ctx, `location.href`)
		if err != nil {
			lastErr = err
			continue
		}
		title, _ := p.evalString(ctx, `document.title`)

		// Bot-wall check: title matches known interstitial patterns.
		if isBotWall(title, opts.BotWallTitles) {
			lastErr = fmt.Errorf("camoufox: NavigateGuarded: bot wall detected (title=%q)", title)
			continue
		}

		// URL check: if ExpectedURLs is set, at least one must be a substring of the final URL.
		if len(opts.ExpectedURLs) > 0 && !urlMatches(currentURL, opts.ExpectedURLs) && !urlMatches(currentURL, opts.AllowedRedirects) {
			lastErr = fmt.Errorf("camoufox: NavigateGuarded: final URL %q does not match expected", currentURL)
			continue
		}

		return nil
	}
	if lastErr != nil {
		return lastErr
	}
	return fmt.Errorf("camoufox: NavigateGuarded: exhausted %d attempts", opts.MaxAttempts)
}

// evalString is a convenience wrapper that evaluates a JS expression and
// returns the string result.
func (p *Page) evalString(ctx context.Context, expr string) (string, error) {
	v, err := p.Evaluate(ctx, expr)
	if err != nil {
		return "", err
	}
	if s, ok := v.(string); ok {
		return s, nil
	}
	return fmt.Sprintf("%v", v), nil
}

// urlMatches returns true if any pattern in patterns is a substring of url.
func urlMatches(url string, patterns []string) bool {
	for _, p := range patterns {
		if strings.Contains(url, p) {
			return true
		}
	}
	return false
}

// isBotWall returns true if title matches any of the known bot-wall strings
// (case-insensitive substring match).
func isBotWall(title string, botWallTitles []string) bool {
	lower := strings.ToLower(title)
	for _, bw := range botWallTitles {
		if strings.Contains(lower, strings.ToLower(bw)) {
			return true
		}
	}
	return false
}
