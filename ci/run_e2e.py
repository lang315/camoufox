#!/usr/bin/env python3
"""End-to-end user journeys (e2e/): the browser driven the way users drive it.

Run:
    python3 -m ci.run_e2e --binary path/to/camoufox-bin [-- extra pytest args]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from . import results
from ._pytest import built_binary, parse_junit, run_pytest
from ._util import REPO_ROOT, RESULTS_DIR, WORK_DIR


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    extra = argv[argv.index("--") + 1:] if "--" in argv else []
    argv = argv[: argv.index("--")] if "--" in argv else argv
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument("--timeout", type=int, default=5400)
    args = parser.parse_args(argv)

    result = results.GateResult(gate="e2e")
    binary = (args.binary or built_binary()).resolve()
    if not binary.exists():
        result.note(f"no browser at {binary}; a suite that did not run has not passed")
        result.finish(results.ERROR).save(args.results_dir)
        return 1
    result.metrics["binary"] = str(binary)

    junit = WORK_DIR / "junit-e2e.xml"
    proc = run_pytest(
        cwd=REPO_ROOT / "e2e",
        python=Path(sys.executable),
        args=[f"--binary={binary}", *extra],
        junit=junit,
        timeout=args.timeout,
        per_test_timeout=900,
    )
    outcomes = parse_junit(junit)
    if not outcomes:
        result.note(f"pytest exited {proc.code} with no junit output; the suite did not run")
        result.finish(results.ERROR).save(args.results_dir)
        return 1
    for tid, outcome in outcomes.items():
        result.record(tid, outcome)
    tally = result.tally()
    result.artifacts.append(junit.name)
    result.metrics["exit_code"] = proc.code
    result.note(f"{tally.get('pass', 0)} passed, {tally.get('fail', 0)} failed, {tally.get('error', 0)} errored, "
                f"{tally.get('skip', 0)} skipped ({tally.get('total', 0)} collected)")
    status = results.PASS if tally.get("fail", 0) + tally.get("error", 0) == 0 else results.FAIL
    result.finish(status).save(args.results_dir)
    return 0 if status == results.PASS else 1


if __name__ == "__main__":
    sys.exit(main())
