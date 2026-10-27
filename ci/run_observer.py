#!/usr/bin/env python3
"""Observer gate: the tracking observer's scripts against the browser under test.

Each `test_*.py` in `browser/tests/build-tester/observer/` runs as its own
process and its exit code is the verdict. A missing browser or a missing
`marionette_driver` fails the gate; a suite that did not run has not passed.

Run:
    python3 -m ci.run_observer --binary path/to/camoufox-bin
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import List, Optional

from . import results as evidence
from ._pytest import built_binary
from ._util import BROWSER_ROOT, EVIDENCE_DIR, run

OBSERVER = BROWSER_ROOT / "tests" / "build-tester" / "observer"


def has_marionette() -> bool:
    return importlib.util.find_spec("marionette_driver") is not None


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--evidence-dir", type=Path, default=EVIDENCE_DIR)
    parser.add_argument("--timeout", type=int, default=600, help="seconds per test script")
    args = parser.parse_args(argv)

    result = evidence.GateResult(gate="observer")
    binary = (args.binary or built_binary()).resolve()
    scripts = sorted(OBSERVER.glob("test_*.py"))
    for problem in (
        None if binary.exists() else f"no browser at {binary}",
        None if has_marionette() else "marionette_driver is not installed (browser/tests/build-tester/requirements.txt)",
        None if scripts else f"no test_*.py in {OBSERVER}",
    ):
        if problem:
            result.note(f"{problem}; a suite that did not run has not passed")
            result.finish(evidence.ERROR).save(args.evidence_dir)
            return 1
    result.metrics["binary"] = str(binary)

    for script in scripts:
        proc = run([sys.executable, script.name], cwd=OBSERVER, env={"CFX_BIN": str(binary)}, timeout=args.timeout)
        print(proc.combined(), flush=True)
        result.record(script.name, evidence.PASS if proc.ok else evidence.FAIL)

    tally = result.tally()
    result.note(f"{tally.get('pass', 0)} passed, {tally.get('fail', 0)} failed ({tally['total']} collected)")
    status = evidence.PASS if tally.get("fail", 0) == 0 else evidence.FAIL
    result.finish(status).save(args.evidence_dir)
    return 0 if status == evidence.PASS else 1


if __name__ == "__main__":
    sys.exit(main())
