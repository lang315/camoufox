"""#345 probe: the alias-stall guard on several builds, interleaved in one job on one runner.

    python3 e2e/probes/alias_stall_ab.py --zip ZIP [--runs 8]    (from the repo root)

ZIP is the build of the dispatched run_id (arm "run"). PROBE_BUILD_IDS (the workflow's `k` input) is
a comma-separated list of other build run ids to download as arms. Each round runs every arm once, the
order rotating by one per round, and the guard's own "longest block" lines are tabulated per arm.
"""

import argparse
import os
import re
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from other_names_stall import unpack  # noqa: E402

BLOCK = re.compile(r"(control|ok \S+|FAIL \S+): longest block (\d+)ms")


def download(run_id: str, dest: Path) -> Path:
    subprocess.run(["gh", "run", "download", run_id, "--repo", os.environ["GITHUB_REPOSITORY"], "-n",
                    "CamoufoxBuilds-windows-x86_64", "-D", str(dest)], check=True)
    return unpack(str(next(dest.glob("*.zip"))), dest / "x")


def main() -> int:
    a = argparse.ArgumentParser()
    a.add_argument("--zip", required=True)
    a.add_argument("--runs", type=int, default=8)
    args = a.parse_args()
    repo = Path(__file__).resolve().parents[2]
    out = Path(os.environ.get("E2E_MOZ_LOG") or ".ci-work/mozlog")
    out.mkdir(parents=True, exist_ok=True)
    series: dict[str, dict[str, list[int]]] = {}
    with tempfile.TemporaryDirectory(prefix="alias-ab-") as tmp:
        tmp = Path(tmp)
        arms = {"run": unpack(args.zip, tmp / "run")}
        for rid in filter(None, os.environ.get("PROBE_BUILD_IDS", "").split(",")):
            arms[rid] = download(rid, tmp / rid)
        names = list(arms)
        print(f"arms: {names}", flush=True)
        for rnd in range(args.runs):
            for arm in names[rnd % len(names):] + names[:rnd % len(names)]:
                env = {**os.environ, "PYTHONUTF8": "1", "CAMOUFOX_EXECUTABLE_PATH": str(arms[arm]),
                       "PYTHONPATH": os.pathsep.join(filter(None, [str(repo / "python" / "src"), os.environ.get("PYTHONPATH", "")]))}
                if rnd < 2:  # a timestamped font-list log of the first two rounds of every arm
                    env.update({"MOZ_LOG": "timestamp,sync,fontlist:4", "MOZ_LOG_FILE": str(out / f"alias-{arm}-r{rnd}")})
                proc = subprocess.run([sys.executable, str(repo / "browser/tests/playwright/patches/system-font-alias-stall.py")], cwd=repo,
                                      env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
                blocks = {m.group(1): int(m.group(2)) for m in BLOCK.finditer(proc.stdout)}
                print(f"ALIASAB round={rnd} arm={arm} exit={proc.returncode} blocks={blocks}", flush=True)
                for k, v in blocks.items():
                    series.setdefault(arm, {}).setdefault(k, []).append(v)
    for arm, rows in series.items():
        print(f"ALIASAB median arm={arm} " + " ".join(f"{k}: min {min(v)} med {int(statistics.median(v))} max {max(v)}" for k, v in rows.items()), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
