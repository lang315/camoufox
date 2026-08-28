
from _constants import CATEGORY_LABELS


def compute_grade(pass_count: int, total_checks: int) -> str:
    fail_count = total_checks - pass_count
    if fail_count == 0:
        return "A"
    if fail_count <= 2:
        return "B"
    if fail_count <= 5:
        return "C"
    if fail_count <= 10:
        return "D"
    return "F"


def count_checks(categories: dict) -> tuple:
    passed = total = 0
    for cat in categories.values():
        if not isinstance(cat, dict):
            continue
        for check in cat.values():
            if check and isinstance(check.get("passed"), bool):
                total += 1
                if check["passed"]:
                    passed += 1
    return passed, total


def count_all_checks(results: dict) -> tuple:
    pass_count = total_checks = 0

    for category_name in ("core", "extended", "workers"):
        p, t = count_checks(results.get(category_name, {}))
        pass_count += p
        total_checks += t

    # WebRTC
    total_checks += 1
    if results.get("webrtc", {}).get("passed"):
        pass_count += 1

    # Stability
    total_checks += 1
    if results.get("stability", {}).get("stable"):
        pass_count += 1

    # Self-destruct (per-context mode)
    if results.get("selfDestruct"):
        for check in results["selfDestruct"].values():
            if check and isinstance(check.get("passed"), bool):
                total_checks += 1
                if check["passed"]:
                    pass_count += 1

    return pass_count, total_checks


def adjust_cross_os_font_checks(os_type: str, results: dict) -> None:
    """Deliberately does nothing. Kept so the call site reads as an explicit decision.

    This used to force-pass osDetection and noWrongOSFonts whenever a profile's
    OS differed from the host's, on the assumption that a Linux host simply
    cannot show Apple fonts. That assumption is wrong: Camoufox ships bundled
    font sets for every OS, and a bare launch on a Linux runner detects all
    three Apple marker fonts (Helvetica Neue, PingFang HK, Geneva).

    So the failures it was hiding were real -- the launch-level font whitelist
    deleting families a per-context setFontList() could never restore (#44/#45)
    -- and every cross-OS profile was marked "[Cross-OS: expected]" while being
    broken in exactly the way the same-OS profiles were failing loudly.

    run_tests.py now launches one browser per OS, so the fonts are right and
    these checks must stand on their own. macOSVersionDepth was never in the
    masked list anyway, and failed either way.
    """
