package camoufox

import "os"

func init() { defaultOS = os.Getenv("CAMOUFOX_TEST_OS") }

// SetDefaultOS pins the identity OS for Launch calls that pass no WithOS and returns the undo.
func SetDefaultOS(name string) func() {
	old := defaultOS
	defaultOS = name
	return func() { defaultOS = old }
}
