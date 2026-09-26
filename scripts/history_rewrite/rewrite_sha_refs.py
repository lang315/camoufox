#!/usr/bin/env python3
"""Rewrite commit-sha references in tracked files after `git filter-repo` (W0).

filter-repo writes .git/filter-repo/commit-map ("old new" per line, header first,
all-zero new = pruned). Every 7-40 hex token in a tracked text file that is a
unique prefix of a CHANGED commit is replaced by the new sha at the same length.
Tokens of unchanged commits (upstream history) and non-sha hex are left alone.
*.patch files are skipped: their `index` lines are blob hashes, not commits.

    python3 rewrite_sha_refs.py <commit-map>
    python3 rewrite_sha_refs.py --dump-map <commit-map> <out.md>
"""

import re
import subprocess
import sys
from pathlib import Path
from typing import Dict

HEX = re.compile(r"\b[0-9a-f]{7,40}\b")


def load_map(path) -> Dict[str, str]:
    changed = {}
    for line in Path(path).read_text().splitlines()[1:]:
        old, new = line.split()
        if old != new and set(new) != {"0"}:
            changed[old] = new
    return changed


def rewrite_text(text: str, changed: Dict[str, str]) -> str:
    by_prefix: Dict[str, list] = {}
    for old in changed:
        by_prefix.setdefault(old[:7], []).append(old)

    def sub(mo):
        token = mo.group(0)
        if token.isdigit():
            return token
        hits = [o for o in by_prefix.get(token[:7], []) if o.startswith(token)]
        return changed[hits[0]][: len(token)] if len(hits) == 1 else token

    return HEX.sub(sub, text)


def dump_map(map_path, out_path) -> None:
    rows = sorted(load_map(map_path).items())
    lines = [
        "# History rewrite, 2026-09",
        "",
        "W0 of `docs/superpowers/specs/2026-09-26-open-e2e-findings-design.md` rewrote the",
        "fork's author and committer identities. Issue and PR bodies and Actions runs still",
        "name the OLD shas; this table resolves them. Commits not listed kept their sha.",
        "",
        "| old | new |",
        "|---|---|",
        *(f"| `{o}` | `{n}` |" for o, n in rows),
        "",
    ]
    Path(out_path).write_text("\n".join(lines))


def main(argv) -> int:
    if argv[:1] == ["--dump-map"]:
        dump_map(argv[1], argv[2])
        return 0
    changed = load_map(argv[0])
    files = subprocess.run(["git", "ls-files", "-z"], capture_output=True, text=True, check=True).stdout
    n = 0
    for name in filter(None, files.split("\0")):
        path = Path(name)
        if path.suffix == ".patch" or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        new = rewrite_text(text, changed)
        if new != text:
            path.write_text(new, encoding="utf-8")
            print(name)
            n += 1
    print(f"{n} files rewritten", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
