"""Diag for #472, never merged: humanize-mouse-trajectory.py ten times on a build.

    python e2e/probes/humanize_loop.py --zip ZIP [--runs N]

e2e.yml passes --runs 8 to every probe; this one runs the guard RUNS times.
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from other_names_stall import unpack  # noqa: E402

RUNS = 10
GUARD = ROOT / "browser/tests/playwright/patches/humanize-mouse-trajectory.py"
ARM = re.compile(r"=== curves leaving the viewport, prefs (.*) ===")


def main() -> int:
    a = argparse.ArgumentParser()
    a.add_argument("--zip", required=True)
    a.add_argument("--runs", type=int, default=0)
    args = a.parse_args()
    with tempfile.TemporaryDirectory(prefix="humanize-loop-") as tmp:
        binary = unpack(args.zip, Path(tmp))
        # DEBUG=pw:browser surfaces Juggler's "was not delivered" warnings on stderr.
        env = {**os.environ, "CAMOUFOX_EXECUTABLE_PATH": str(binary), "DEBUG": "pw:browser",
               "PYTHONPATH": os.pathsep.join(filter(None, [str(ROOT / "python" / "src"), os.environ.get("PYTHONPATH", "")]))}
        late = {}
        undelivered = y0 = 0
        for run in range(1, RUNS + 1):
            out = subprocess.run([sys.executable, str(GUARD)], cwd=ROOT, env=env,
                                 capture_output=True, text=True, timeout=900)
            text = out.stdout + out.stderr
            arm = None
            for line in text.splitlines():
                if line.startswith("=== "):
                    m = ARM.search(line)
                    arm = m.group(1) if m else None
                    if arm:
                        late.setdefault(arm, 0)
                if "exits unlike stock's" in line:
                    late[arm] += 1
                    y0 += bool(re.search(r"\(-?\d+, 0\), \d", line.split("in ", 1)[-1]))
                if "was not delivered" in line:
                    undelivered += 1
                if arm and line.lstrip().startswith(("PASS:", "FAIL:")):
                    print(f"run {run} [{arm}] {line.strip()}", flush=True)
            print(f"run {run}: rc={out.returncode}", flush=True)
        print(f"RESULT runs={RUNS} late-exit runs per arm={late} y0-exit lines={y0} undelivered={undelivered}",
              flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
