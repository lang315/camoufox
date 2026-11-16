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


def loop(binary: Path, label: str) -> None:
    """Run the guard RUNS times on `binary` and print what each run saw."""
    # DEBUG=pw:browser surfaces Juggler's "was not delivered" warnings on stderr.
    env = {**os.environ, "CAMOUFOX_EXECUTABLE_PATH": str(binary), "DEBUG": "pw:browser",
           "PYTHONPATH": os.pathsep.join(filter(None, [str(ROOT / "python" / "src"), os.environ.get("PYTHONPATH", "")]))}
    late = {}
    undelivered = y0 = completed = 0
    for run in range(1, RUNS + 1):
        out = subprocess.run([sys.executable, str(GUARD)], cwd=ROOT, env=env,
                             capture_output=True, text=True, timeout=900)
        text = out.stdout + out.stderr
        arm = section = None
        for line in text.splitlines():
            if line.startswith("=== "):
                section = line.strip("= ")
                m = ARM.search(line)
                arm = m.group(1) if m else None
                if arm:
                    late.setdefault(arm, 0)
            if "exits unlike stock's" in line:
                late[arm] += 1
                y0 += bool(re.search(r"\(-?\d+, 0\), \d", line.split("in ", 1)[-1]))
            if "was not delivered" in line:
                undelivered += 1
            if section and line.lstrip().startswith(("PASS:", "FAIL:")):
                print(f"{label} run {run} [{section}] {line.strip()}", flush=True)
        # The guard's last section: a run that reaches it launched the browser five times.
        completed += "PASS: humanized click landed on the target" in text
        print(f"{label} run {run}: rc={out.returncode}", flush=True)
    print(f"RESULT {label}: runs={RUNS} completed={completed} late-exit runs per arm={late} "
          f"y0-exit lines={y0} undelivered={undelivered}", flush=True)


def main() -> int:
    a = argparse.ArgumentParser()
    a.add_argument("--zip", required=True)
    a.add_argument("--runs", type=int, default=0)
    args = a.parse_args()
    with tempfile.TemporaryDirectory(prefix="humanize-loop-") as tmp:
        loop(unpack(args.zip, Path(tmp)), "build")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
