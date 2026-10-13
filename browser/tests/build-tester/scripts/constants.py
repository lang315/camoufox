"""
Shared constants, ANSI color codes, and simple formatting helpers.
"""

import re

# ─── Test Configuration ───────────────────────────────────────────────────────

TEST_TIMEZONES = [
    "America/New_York",
    "America/Chicago",
    "America/Los_Angeles",
    "Europe/London",
    "Europe/Berlin",
    "Asia/Tokyo",
    "America/Denver",
    "Australia/Sydney",
]

WEBRTC_TEST_IP = "203.0.113.1"
WEBRTC_TEST_LOCAL_IP = "10.11.12.13"
# Init snippet that flags to checkCanvasPerturbation that a canvas:seed was configured.
CANVAS_SEED_INIT_SCRIPT = "try { window.__canvasSeedSet__ = true; } catch (e) {}"

FIREFOX_WEBGL_PREFS = {
    "webgl.force-enabled": True,
    "webgl.enable-webgl2": True,
    "media.peerconnection.ice.obfuscate_host_addresses": False,
}

CATEGORY_LABELS = {
    "automation": "Automation Detection",
    "jsEngine": "JS Engine",
    "lieDetection": "Lie Detection",
    "firefoxAPIs": "Firefox APIs",
    "crossSignal": "Cross-Signal",
    "cssFingerprint": "CSS Fingerprint",
    "mathEngine": "Math Engine",
    "permissionsAPI": "Permissions",
    "speechVoices": "Speech Voices",
    "performanceAPI": "Performance",
    "intlConsistency": "Intl Consistency",
    "emojiFingerprint": "Emoji",
    "canvasNoiseDetection": "Canvas Noise",
    "webglRenderHash": "WebGL Render",
    "fontPlatformConsistency": "Font Platform",
    "audioIntegrity": "Audio Integrity",
    "iframeTesting": "Iframe Testing",
    "workerConsistency": "Workers",
    "headlessDetection": "Headless Detection",
    "trashDetection": "Trash Detection",
    "fontEnvironment": "Font Environment",
}

# ─── ANSI Colors ──────────────────────────────────────────────────────────────

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def strip_ansi(s: str) -> str:
    return ANSI_ESCAPE_RE.sub("", s)


def grade_color(g: str) -> str:
    if g == "A":
        return GREEN
    if g in ("B", "C"):
        return YELLOW
    return RED
