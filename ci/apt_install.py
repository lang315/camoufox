"""Install apt packages on a CI runner, failing fast and loudly (#275).

    python3 ci/apt_install.py PACKAGE...

An apt command that gets no answer from the runner's mirror waits for as long
as the job lets it: `apt-get update -qq` once printed nothing for the hour the
job had. Each command here is bounded, and the one that ran out of time is
named. It is not retried: a stall is an environmental fault to see, not to hide.
"""

import os
import subprocess
import sys

# Over 899 healthy runs the slowest step took 165 s; docs/bug-fixes.md (#275)
# has the distribution this was set from.
LIMIT = int(os.environ.get("APT_TIMEOUT", "600"))


def apt(*args: str) -> int:
    try:
        return subprocess.run(["sudo", "apt-get", *args], timeout=LIMIT).returncode
    except subprocess.TimeoutExpired:
        print(f"::error::apt-get {args[0]} did not finish in {LIMIT}s", flush=True)
        return 124


def main(packages: list[str]) -> int:
    for args in (["update"], ["install", "-y", "--no-install-recommends", *packages]):
        code = apt(*args)
        if code:
            return code
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
