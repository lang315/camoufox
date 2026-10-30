"""#345 probe: run system-font-alias-stall.py --runs times against a build zip and print each guard's exit code and time.

    python3 e2e/probes/alias_stall_repeat.py --zip ZIP [--runs 8]    (from the repo root)
"""

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from other_names_stall import unpack  # noqa: E402


def main() -> int:
    a = argparse.ArgumentParser()
    a.add_argument("--zip", required=True)
    a.add_argument("--runs", type=int, default=8)
    args = a.parse_args()
    results = []
    with tempfile.TemporaryDirectory(prefix="alias-stall-") as tmp:
        binary = unpack(args.zip, Path(tmp))
        for i in range(args.runs):
            t0 = time.time()
            rc = subprocess.run([sys.executable, "-m", "ci.run_patch_guards", "--binary", str(binary), "--only", "system-font-alias-stall",
                                 "--evidence-dir", str(Path(os.environ.get("E2E_MOZ_LOG") or ".ci-work/mozlog") / f"alias-{i}")],
                                env={**os.environ, "PYTHONUTF8": "1"}).returncode
            results.append(rc)
            print(f"ALIAS run {i}: exit={rc} secs={time.time() - t0:.0f}", flush=True)
    print(f"ALIAS exits: {results}", flush=True)
    return int(any(results))


if __name__ == "__main__":
    raise SystemExit(main())
