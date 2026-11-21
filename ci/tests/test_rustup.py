"""install-deps.sh installs rustup, not only a distro rustc and cargo.

issue #1059: install-deps.sh skipped rustup whenever rustc and cargo were
present, so a distro Rust without rustup stayed broken. Only this half of
daijro/camoufox#1098 applies in the fork: patch.py runs the rustup on PATH
(#335) and keeps #886's pinned Rust reverted, so it has no find_rustup.
"""

import shutil
import subprocess

from ci._util import BROWSER_ROOT


def _executable(path, body=""):
    path.write_text(body)
    path.chmod(0o755)


def test_install_deps_installs_rustup_beside_a_distro_rust(tmp_path):
    """rustc and cargo on PATH without rustup still get rustup installed."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("sh", "cat", "mkdir", "chmod"):
        (bin_dir / tool).symlink_to(shutil.which(tool))
    for tool in ("rustc", "cargo"):
        _executable(bin_dir / tool, "#!/bin/sh\necho 1.0\n")
    # Stands in for sh.rustup.rs: the installer it prints adds ~/.cargo/bin/rustup.
    _executable(bin_dir / "curl", """#!/bin/sh
cat <<'INSTALLER'
mkdir -p "$HOME/.cargo/bin"
printf '#!/bin/sh\\necho rustup 1.0\\n' > "$HOME/.cargo/bin/rustup"
chmod +x "$HOME/.cargo/bin/rustup"
echo 'PATH="$HOME/.cargo/bin:$PATH"' > "$HOME/.cargo/env"
INSTALLER
""")
    # Define the script's functions without running main, which installs packages.
    script = (BROWSER_ROOT / "scripts" / "install-deps.sh").read_text()
    assert script.endswith('\nmain "$@"\n')
    script = script.removesuffix('main "$@"\n')
    subprocess.run(
        [shutil.which("bash"), "-c", script + "\ninstall_rust\n"],
        env={"HOME": str(tmp_path), "PATH": str(bin_dir)},
        check=True,
    )
    assert (tmp_path / ".cargo" / "bin" / "rustup").is_file()
