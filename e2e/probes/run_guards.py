"""#345 probe: run the font guards and build-tester against one build zip, on this runner's OS.

    python3 e2e/probes/run_guards.py --zip ZIP    (from the repo root; E2E_MOZ_LOG = output dir)
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from other_names_stall import unpack  # noqa: E402

FONT_GUARDS = [
    "context-os-system-font", "context-list-every-process", "context-lists-across-processes",
    "generic-monospace-launch-mask", "local-font-source", "system-font-alias-stall",
    "system-ui-font-spoofing", "fallback-miss-while-cmaps-load",
    "legacy-family-names-first-measure", "locale-explicit-names",
]


def main() -> int:
    a = argparse.ArgumentParser()
    a.add_argument("--zip", required=True)
    a.add_argument("--runs", type=int, default=1)  # the workflow passes it to every probe
    args = a.parse_args()
    out = Path(os.environ.get("E2E_MOZ_LOG") or ".ci-work/mozlog")
    out.mkdir(parents=True, exist_ok=True)
    rcs = {}
    with tempfile.TemporaryDirectory(prefix="guards-probe-") as tmp:
        binary = unpack(args.zip, Path(tmp))
        bt = Path("browser/tests/build-tester")
        subprocess.run([shutil.which("npm") or "npm", "install"], cwd=bt, check=True)
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], cwd=bt, check=True)
        for name, cmd in {
            "font-guards": [sys.executable, "-m", "ci.run_patch_guards", "--binary", str(binary), "--only", *FONT_GUARDS,
                            "--evidence-dir", str(out / "guards-evidence")],
            "build-tester": [sys.executable, "-m", "ci.run_build_tester", "--binary", str(binary),
                             "--evidence-dir", str(out / "build-tester-evidence")],
        }.items():
            print(f"== {name}", flush=True)
            rcs[name] = subprocess.run(cmd, env={**os.environ, "PYTHONUTF8": "1"}).returncode  # build-tester prints box-drawing characters
    print("exit codes:", rcs, flush=True)
    return int(any(rcs.values()))


if __name__ == "__main__":
    raise SystemExit(main())
