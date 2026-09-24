"""Oracle A: expectations taken from public documentation, each with its quote.

`cite` fails if the quote is no longer in the file, so an expectation cannot
outlive the sentence it came from.
"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

CLAIMS = {
    "isolated_eval": ("README.md", 'websites can no longer "see" any JavaScript that Playwright would typically inject'),
    "trusted_input": ("README.md", "meaning they are handled the exact same way as if you were using the browser normally"),
    "webdriver": ("README.md", "Fixes `navigator.webdriver` detection"),
    "os_option": ("pythonlib/camoufox/utils.py", 'Can be "windows", "macos", "linux", or a list to randomly choose from.'),
    "locale": ("pythonlib/camoufox/utils.py", "The first listed locale will be used for the Intl API."),
    "geoip": ("pythonlib/camoufox/utils.py", "Calculate longitude, latitude, timezone, country, & locale based on the IP address."),
    "humanize": ("pythonlib/camoufox/utils.py", "Humanize the cursor movement."),
    "virtual": ("pythonlib/camoufox/utils.py", "passing headless='virtual' to Camoufox & AsyncCamoufox"),
    "webrtc": ("README.md", "WebRTC IP spoofing at the protocol level"),
    "unique_context": ("pythonlib/camoufox/sync_api.py", "Creates a new browser context with a unique fingerprint identity."),
}


def cite(key: str) -> str:
    path, quote = CLAIMS[key]
    text = (REPO / path).read_text(encoding="utf-8")
    assert quote in text, f"oracle A: {path} no longer says {quote!r}; re-derive this expectation"
    return f"{path}: {quote!r}"


def font_markers() -> dict:
    """Families exactly one OS's font universe contains, from the package's own
    shipped per-OS lists (camoufox/fonts.json). A family two OSes share, such as
    Tahoma on Windows and macOS, can never be a marker."""
    import json

    import camoufox

    raw = json.loads((Path(camoufox.__file__).parent / "fonts.json").read_text(encoding="utf-8"))
    lists = {"windows": set(raw["win"]), "macos": set(raw["mac"]), "linux": set(raw["lin"])}
    return {o: sorted(lists[o] - set().union(*(lists[x] for x in lists if x != o))) for o in lists}
