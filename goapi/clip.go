package camoufox

import "github.com/lang315/camoufox/goapi/pkg/juggler"

// Clip is a re-export of the Juggler screenshot clip type so callers
// of Page.Screenshot don't need to import the juggler package.
type Clip = juggler.PageScreenshotClip
