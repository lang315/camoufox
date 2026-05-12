package config

import (
	"encoding/json"
	"fmt"
	"runtime"
)

// Chunk size limits mirror pythonlib/camoufox/utils.py:get_env_vars:
//
//	chunk_size = 2047 if OS_NAME == 'win' else 32767
//
// The Windows limit is the historical environment-block per-variable
// cap; Unix-like systems use a larger 32 KiB chunk.
const (
	chunkSizeWindows = 2047
	chunkSizeUnix    = 32767
)

// HostOS reports the runtime OS in the same vocabulary the rest of
// this package uses: "windows", "macos", "linux", or "other".
func HostOS() string {
	switch runtime.GOOS {
	case "windows":
		return "windows"
	case "darwin":
		return "macos"
	case "linux":
		return "linux"
	default:
		return runtime.GOOS
	}
}

// ChunkSizeFor returns the byte-budget for a single CAMOU_CONFIG_N
// variable on the given target host OS ("windows" gets the smaller
// limit; everything else gets the Unix limit).
func ChunkSizeFor(hostOS string) int {
	if hostOS == "windows" {
		return chunkSizeWindows
	}
	return chunkSizeUnix
}

// Marshal serializes the Config (merging Extra) into a single JSON
// blob — the exact same shape orjson.dumps produces in the Python
// reference (utils.py:get_env_vars).
func (c *Config) Marshal() ([]byte, error) {
	if c == nil {
		return []byte("{}"), nil
	}
	// Round-trip through a generic map so caller-supplied Extra keys
	// are merged with the named fields. Named-field keys win on
	// collision because Extra is applied after.
	named, err := json.Marshal(structCopy(c))
	if err != nil {
		return nil, fmt.Errorf("config: marshal named: %w", err)
	}
	if len(c.Extra) == 0 {
		return named, nil
	}
	var merged map[string]json.RawMessage
	if err := json.Unmarshal(named, &merged); err != nil {
		return nil, fmt.Errorf("config: re-decode: %w", err)
	}
	for k, v := range c.Extra {
		if _, exists := merged[k]; exists {
			continue
		}
		raw, err := json.Marshal(v)
		if err != nil {
			return nil, fmt.Errorf("config: marshal extra %q: %w", k, err)
		}
		merged[k] = raw
	}
	return json.Marshal(merged)
}

// EnvVars returns the CAMOU_CONFIG_N entries to inject into the
// browser's environment. hostOS controls the chunk-size cap and
// should match the OS the binary is launched on (NOT the spoofed
// navigator OS); pass an empty string to detect from runtime.GOOS.
//
// Each returned string is in "KEY=VALUE" form, ready to append to
// (*exec.Cmd).Env.
func (c *Config) EnvVars(hostOS string) ([]string, error) {
	if hostOS == "" {
		hostOS = HostOS()
	}
	blob, err := c.Marshal()
	if err != nil {
		return nil, err
	}
	chunk := ChunkSizeFor(hostOS)
	var out []string
	for i := 0; i < len(blob); i += chunk {
		end := min(i+chunk, len(blob))
		out = append(out, fmt.Sprintf("CAMOU_CONFIG_%d=%s", (i/chunk)+1, blob[i:end]))
	}
	if len(out) == 0 {
		// Always emit at least one chunk so the parser sees an empty
		// object instead of an unset variable.
		out = append(out, "CAMOU_CONFIG_1="+string(blob))
	}
	return out, nil
}

// structCopy returns a shallow copy of c with Extra cleared so json
// encoding only walks the tagged fields.
func structCopy(c *Config) *Config {
	cp := *c
	cp.Extra = nil
	return &cp
}
