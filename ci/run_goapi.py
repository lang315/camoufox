#!/usr/bin/env python3
"""goapi gate: the Go launcher's tests that drive a real browser.

`goapi.yml` runs the package without a browser, where these tests skip by
design. Here CAMOUFOX_BIN is set and CI=true, so a test that cannot find the
browser fails instead of skipping (goapi/browser_test.go).

Run:
    python3 -m ci.run_goapi --binary path/to/camoufox-bin
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

from . import results as evidence
from ._pytest import built_binary
from ._util import EVIDENCE_DIR, REPO_ROOT, run

GOAPI = REPO_ROOT / "goapi"
_VERDICTS = {"PASS": evidence.PASS, "FAIL": evidence.FAIL, "SKIP": evidence.SKIP}
_LINE = re.compile(r"^\s*--- (PASS|FAIL|SKIP): (\S+)", re.MULTILINE)


def parse_go_test(output: str) -> Dict[str, str]:
    """`go test -v` output -> {test_id: pass|fail|skip}, subtests included."""
    return {name: _VERDICTS[verdict] for verdict, name in _LINE.findall(output)}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--evidence-dir", type=Path, default=EVIDENCE_DIR)
    parser.add_argument("--timeout", type=int, default=2400)
    args = parser.parse_args(argv)

    result = evidence.GateResult(gate="goapi_browser")
    binary = (args.binary or built_binary()).resolve()
    if not binary.exists():
        result.note(f"no browser at {binary}; a suite that did not run has not passed")
        result.finish(evidence.ERROR).save(args.evidence_dir)
        return 1
    result.metrics["binary"] = str(binary)

    proc = run(
        ["go", "test", "-v", "-count=1", "-timeout", f"{args.timeout - 60}s", "./..."],
        cwd=GOAPI, env={"CAMOUFOX_BIN": str(binary), "CI": "true"}, timeout=args.timeout,
    )
    print(proc.stdout + proc.stderr, flush=True)
    outcomes = parse_go_test(proc.stdout)
    if not outcomes:
        result.note(f"go test exited {proc.code} with no test results; the suite did not run")
        result.finish(evidence.ERROR).save(args.evidence_dir)
        return 1
    for tid, outcome in outcomes.items():
        result.record(tid, outcome)

    tally = result.tally()
    result.metrics["exit_code"] = proc.code
    result.note(
        f"{tally.get('pass', 0)} passed, {tally.get('fail', 0)} failed, "
        f"{tally.get('skip', 0)} skipped ({tally.get('total', 0)} collected)"
    )
    # A non-zero exit with no failed test is a build or package failure.
    failing = tally.get("fail", 0) + tally.get("error", 0) + (0 if proc.ok else 1)
    status = evidence.PASS if failing == 0 else evidence.FAIL
    result.finish(status).save(args.evidence_dir)
    return 0 if status == evidence.PASS else 1


if __name__ == "__main__":
    sys.exit(main())
