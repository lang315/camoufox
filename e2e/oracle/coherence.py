"""Oracle C: coherence rules.

Each rule compares two sources that a real browser keeps in agreement, so it
needs no absolute truth. A rule is only trusted once it has been seen red: each
one carries a mutation that creates exactly the disagreement it looks for, and
`evaluate` checks the rule fails on it. A rule that cannot go red is VACUOUS.

`fp` is what /fp published; `req` is the server's record of the /fp request.
"""

from __future__ import annotations

import copy
from typing import Callable, List, Optional, Tuple

UA_OS = {"windows": "Windows NT", "macos": "Macintosh", "linux": "Linux"}
PLATFORM_OS = {"windows": "Win", "macos": "Mac", "linux": "Linux"}
WEBGL_MARKERS = {"windows": ("Direct3D", "D3D11"), "macos": ("Apple",), "linux": ("Mesa",)}
WORKER_KEYS = ("ua", "platform", "language", "cores", "tz")

Result = Tuple[Optional[bool], str]


def _header(req, name):
    return next((v for k, v in req["headers"] if k.lower() == name.lower()), None)


def _ua_os(ua: str) -> Optional[str]:
    return next((k for k, v in UA_OS.items() if v in ua), None)


def _platform_os(platform: str) -> Optional[str]:
    return next((k for k, v in PLATFORM_OS.items() if platform.startswith(v)), None)


def ua_matches_header(fp, req, os_name) -> Result:
    js, wire = fp["main"]["ua"], _header(req, "User-Agent")
    return js == wire, f"js={js!r} header={wire!r}"


def platform_matches_ua(fp, req, os_name) -> Result:
    ua_os, plat_os = _ua_os(fp["main"]["ua"]), _platform_os(fp["main"]["platform"])
    return ua_os is not None and ua_os == plat_os, f"ua->{ua_os} platform={fp['main']['platform']!r}->{plat_os}"


def os_is_requested(fp, req, os_name) -> Result:
    if os_name is None:
        return None, "no os requested"
    got = (_ua_os(fp["main"]["ua"]), _platform_os(fp["main"]["platform"]))
    return got == (os_name, os_name), f"requested {os_name}, ua/platform say {got}"


def language_matches_header(fp, req, os_name) -> Result:
    first = (_header(req, "Accept-Language") or "").split(",")[0].split(";")[0].strip()
    return fp["main"]["language"] == first, f"navigator.language={fp['main']['language']!r} accept-language[0]={first!r}"


def languages_lead_with_language(fp, req, os_name) -> Result:
    langs = fp["main"]["languages"]
    return bool(langs) and langs[0] == fp["main"]["language"], f"languages={langs!r}"


def intl_locale_matches_language(fp, req, os_name) -> Result:
    intl, lang = fp["intl"], fp["main"]["language"]
    return intl.split("-")[0] == lang.split("-")[0], f"Intl locale={intl!r} navigator.language={lang!r}"


def timezone_offset_agrees(fp, req, os_name) -> Result:
    tz = fp["tz"]
    return tz["offset"] == tz["derived"], f"getTimezoneOffset={tz['offset']} Intl({tz['tz']})->{tz['derived']}"


def screen_contains_viewport(fp, req, os_name) -> Result:
    s = fp["screen"]
    ok = s["w"] >= s["iw"] and s["h"] >= s["ih"] and s["aw"] <= s["w"] and s["ah"] <= s["h"] and s["ow"] >= s["iw"]
    return ok, f"screen {s['w']}x{s['h']} avail {s['aw']}x{s['ah']} outer {s['ow']}x{s['oh']} inner {s['iw']}x{s['ih']}"


def dpr_plausible(fp, req, os_name) -> Result:
    return 0.5 <= fp["screen"]["dpr"] <= 4, f"devicePixelRatio={fp['screen']['dpr']}"


def webdriver_false(fp, req, os_name) -> Result:
    return fp["webdriver"] is False, f"navigator.webdriver={fp['webdriver']!r}"


def workers_agree(fp, req, os_name) -> Result:
    # Only flags disagreement: a worker agreeing with the main thread is not proof
    # either is right (cross-thread reference, CLAUDE.md lesson 4).
    kinds = [k for k in ("dedicated", "shared", "service") if isinstance(fp.get(k), dict)]
    if not kinds:
        return None, "no worker answered"
    bad = [f"{k}.{key}" for k in kinds for key in WORKER_KEYS if fp[k].get(key) != fp["main"].get(key)]
    return not bad, f"compared {kinds}; mismatched {bad}"


def fonts_measurable(fp, req, os_name) -> Result:
    f = fp["fonts"]["floors"]
    return fp["fonts"]["valid"], f"fallback floors monospace={f['mono']} serif={f['serif']} (equal floors = INVALID)"


def monospace_is_monospace(fp, req, os_name) -> Result:
    # Intrinsic: a monospace face gives "iiiiiiiiii" and "mmmmmmmmmm" one width.
    # In-page control: sans-serif must tell them apart, or the measurement cannot.
    mono, sans = fp["fonts"]["mono"], fp["fonts"]["sans"]
    if sans["i"] == sans["m"]:
        return None, f"sans-serif i/m widths equal ({sans}); the measurement cannot discriminate"
    return mono["i"] == mono["m"], f"monospace i={mono['i']} m={mono['m']}; sans-serif i={sans['i']} m={sans['m']}"


def fonts_own_os(fp, req, os_name) -> Result:
    if os_name is None or not fp["fonts"]["valid"]:
        return None, "no os requested or floors INVALID"
    got = fp["fonts"]["rendered"][os_name]
    return bool(got), f"{os_name} marker families rendered: {got}"


def fonts_no_foreign_os(fp, req, os_name) -> Result:
    if os_name is None or not fp["fonts"]["valid"]:
        return None, "no os requested or floors INVALID"
    foreign = {k: v for k, v in fp["fonts"]["rendered"].items() if k != os_name and v}
    return not foreign, f"other-OS marker families rendered: {foreign}"


def webgl_no_foreign_os(fp, req, os_name) -> Result:
    if os_name is None or not fp.get("webgl"):
        return None, "no os requested or no WebGL"
    text = f"{fp['webgl']['vendor']} {fp['webgl']['renderer']}"
    foreign = [m for k, ms in WEBGL_MARKERS.items() if k != os_name for m in ms if m in text]
    return not foreign, f"{text!r}; other-OS markers {foreign}"


def voices_no_foreign_os(fp, req, os_name) -> Result:
    if os_name is None or fp.get("voices") is None:
        return None, "no os requested or no speechSynthesis"
    apple = [v["name"] for v in fp["voices"] if v["uri"].startswith("com.apple")]
    microsoft = [v["name"] for v in fp["voices"] if v["name"].startswith("Microsoft ")]
    foreign = {"windows": apple, "macos": microsoft, "linux": apple + microsoft}[os_name]
    return not foreign, f"{len(fp['voices'])} voices; other-OS voices {foreign[:5]}"


def _other(os_name):
    return next(k for k in UA_OS if k != (os_name or "windows"))


def _set_header(req, name, value):
    req["headers"] = [(k, v) for k, v in req["headers"] if k.lower() != name.lower()] + [(name, value)]


def _m_ua(fp, req, o):
    _set_header(req, "User-Agent", "X")


def _m_platform(fp, req, o):
    fp["main"]["platform"] = "MacIntel" if _ua_os(fp["main"]["ua"]) != "macos" else "Win32"


def _m_language(fp, req, o):
    fp["main"]["language"] = "zz-ZZ"


def _m_languages(fp, req, o):
    fp["main"]["languages"] = ["zz"]


def _m_intl(fp, req, o):
    fp["intl"] = "zz-ZZ"


def _m_tz(fp, req, o):
    fp["tz"]["derived"] = fp["tz"]["offset"] + 60


def _m_screen(fp, req, o):
    fp["screen"]["iw"] = fp["screen"]["w"] + 1


def _m_dpr(fp, req, o):
    fp["screen"]["dpr"] = 9


def _m_webdriver(fp, req, o):
    fp["webdriver"] = True


def _m_workers(fp, req, o):
    fp["dedicated"] = dict(fp["main"], ua="X")


def _m_floors(fp, req, o):
    fp["fonts"]["valid"] = False


def _m_mono(fp, req, o):
    fp["fonts"]["mono"]["m"] = fp["fonts"]["mono"]["i"] + 10


def _m_own_fonts(fp, req, o):
    fp["fonts"]["rendered"][o] = []


def _m_foreign_fonts(fp, req, o):
    fp["fonts"]["rendered"][_other(o)] = ["X"]


def _m_webgl(fp, req, o):
    fp["webgl"]["renderer"] += " " + WEBGL_MARKERS[_other(o)][0]


def _m_voices(fp, req, o):
    fp["voices"] = fp["voices"] + [{"name": "Microsoft X", "uri": "com.apple.x"}]


# (rule, mutation that must make it fail, optional os override for the control)
RULES: List[Tuple[Callable, Callable]] = [
    (ua_matches_header, _m_ua),
    (platform_matches_ua, _m_platform),
    (os_is_requested, None),  # control: ask about a different OS, below
    (language_matches_header, _m_language),
    (languages_lead_with_language, _m_languages),
    (intl_locale_matches_language, _m_intl),
    (timezone_offset_agrees, _m_tz),
    (screen_contains_viewport, _m_screen),
    (dpr_plausible, _m_dpr),
    (webdriver_false, _m_webdriver),
    (workers_agree, _m_workers),
    (fonts_measurable, _m_floors),
    (monospace_is_monospace, _m_mono),
    (fonts_own_os, _m_own_fonts),
    (fonts_no_foreign_os, _m_foreign_fonts),
    (webgl_no_foreign_os, _m_webgl),
    (voices_no_foreign_os, _m_voices),
]


def evaluate(fp: dict, req: dict, os_name: Optional[str]):
    out = []
    for rule, mutate in RULES:
        ok, detail = rule(fp, req, os_name)
        red = None
        if ok is not None:
            f2, r2 = copy.deepcopy(fp), copy.deepcopy(req)
            if mutate is None:
                red = rule(f2, r2, _other(os_name))[0] is False
            else:
                mutate(f2, r2, os_name)
                red = rule(f2, r2, os_name)[0] is False
        out.append((rule.__name__, ok, detail, red))
    return out
