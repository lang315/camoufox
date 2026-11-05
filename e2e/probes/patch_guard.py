"""Run every patch-guard group on a build's own binary, on the OS this job runs on.

    python e2e/probes/patch_guard.py --zip ZIP [--runs N]

Unpacks the build and runs each group of ci.run_patch_guards (spoofing, automation,
parity). e2e.yml passes --runs 8 to every probe, so it is accepted and ignored.
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from other_names_stall import unpack  # noqa: E402


def main() -> int:
    a = argparse.ArgumentParser()
    a.add_argument("--zip", required=True)
    a.add_argument("--runs", type=int, default=0)
    args = a.parse_args()
    with tempfile.TemporaryDirectory(prefix="patch-guard-") as tmp:
        binary = unpack(args.zip, Path(tmp))
        rc = 0
        for group in ("spoofing", "automation", "parity"):
            print(f"=== group {group} ===", flush=True)
            rc |= subprocess.run([sys.executable, "-m", "ci.run_patch_guards", "--group", group,
                                  "--binary", str(binary)], cwd=ROOT).returncode
        return rc


if __name__ == "__main__":
    raise SystemExit(main())
