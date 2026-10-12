import textwrap
from pathlib import Path

import rewrite_sha_refs as r

OLD = "a9f1682" + "0" * 33
NEW = "c6e0ae9" + "1" * 33
UPSTREAM = "e25a16b" + "2" * 33  # unchanged by the rewrite: not in the map


def write_map(tmp_path: Path) -> Path:
    p = tmp_path / "commit-map"
    p.write_text(textwrap.dedent(f"""\
        old                                      new
        {OLD} {NEW}
        {UPSTREAM} {UPSTREAM}
        {"b" * 40} {"0" * 40}
        """))
    return p


def test_a_short_sha_is_rewritten_at_its_own_length(tmp_path):
    m = r.load_map(write_map(tmp_path))
    assert r.rewrite_text("fixed in a9f1682, see a9f16820", m) == f"fixed in {NEW[:7]}, see {NEW[:8]}"


def test_unchanged_deleted_and_non_sha_tokens_are_left_alone(tmp_path):
    m = r.load_map(write_map(tmp_path))
    text = f"upstream {UPSTREAM[:7]}, pruned {'b' * 7}, width 1234567, hash deadbeef00"
    assert r.rewrite_text(text, m) == text


def test_dump_map_lists_only_changed_commits(tmp_path):
    out = tmp_path / "map.md"
    r.dump_map(write_map(tmp_path), out)
    body = out.read_text()
    assert f"| `{OLD}` | `{NEW}` |" in body
    assert UPSTREAM not in body and "b" * 40 not in body
