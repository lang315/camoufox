import os
import signal
import select
import subprocess  # nosec
import time
from shutil import which
from typing import Optional

from camoufox.exceptions import (
    CannotExecuteXvfb,
    CannotFindXvfb,
    VirtualDisplayNotSupported,
)
from camoufox.pkgman import OS_NAME

# Safe timeout for Xvfb writing display num, prevents infinite hang.
DISPLAYFD_READ_TIMEOUT_S = 10.0

# Xvfb screen geometry for headless="virtual".
#
# 1x1x24 is Camoufox's long-standing default and stays the default. The root
# window size is not observable as a fingerprint: screen.* comes from the
# generated fingerprint, applied per context in the browser, and
# clamp_screen_to_display() is skipped entirely for virtual displays (see the
# `not virtual_display` guard in utils.py), so a 1x1 root never clamps a
# generated screen down to 1x1.
#
# Override with CAMOUFOX_VIRTUAL_DISPLAY_SIZE="<width>x<height>x<depth>", e.g.
# "1920x1080x24", for the cases that do want a real framebuffer to draw into.
# Depth may be omitted.
DEFAULT_SCREEN = "1x1x24"
SCREEN_ENV_VAR = "CAMOUFOX_VIRTUAL_DISPLAY_SIZE"

# The Composite extension, ENABLED by default (Xvfb's `+extension COMPOSITE`).
#
# It was briefly disabled by default on the theory that #93 (no video under
# headless="virtual") had been a juggler bug since fixed, making Composite
# "no longer good for anything". Measured on a beta.29 linux build, that is
# wrong -- Composite is still required for video capture:
#
#   headless=True, no Xvfb            -> 60007 byte .webm   (works)
#   headless="virtual", Composite off ->   110 byte .webm   (empty container)
#   headless="virtual", Composite ON  -> 54494 byte .webm   (works)
#
# The headless baseline is what makes this conclusive: record_video itself is
# fine, so the empty file is specific to a virtual display without Composite.
# Screen size is NOT a factor -- CAMOUFOX_VIRTUAL_DISPLAY_SIZE=1920x1080x24
# produced the same 110 bytes as the 1x1 default, so #458's stated mechanism
# (a 1x1 root clamping the window) is not what breaks it.
#
# The old SIGSEGV that motivated disabling Composite is gone: the ON case above
# records cleanly. Default it back on, and keep the escape hatch:
# CAMOUFOX_VIRTUAL_DISPLAY_COMPOSITE=0 disables it.
COMPOSITE_ENV_VAR = "CAMOUFOX_VIRTUAL_DISPLAY_COMPOSITE"


def _resolve_screen() -> str:
    """Screen geometry for Xvfb's -screen argument."""
    value = os.environ.get(SCREEN_ENV_VAR, "").strip()
    if not value:
        return DEFAULT_SCREEN
    parts = value.lower().split("x")
    if len(parts) not in (2, 3) or not all(p.isdigit() and int(p) > 0 for p in parts):
        raise VirtualDisplayNotSupported(
            f"{SCREEN_ENV_VAR} must look like '1920x1080' or '1920x1080x24', got {value!r}"
        )
    if len(parts) == 2:
        parts.append("24")
    return "x".join(parts)


class VirtualDisplay:
    """A minimal virtual display implementation for Linux."""

    def __init__(
        self,
        debug: bool = False,
        screen: Optional[str] = None,
        composite: Optional[bool] = None,
    ) -> None:
        self.debug = debug
        self.screen = screen or _resolve_screen()
        if composite is None:
            composite = os.environ.get(COMPOSITE_ENV_VAR, "1").strip() not in ("0", "false")
        self.composite = composite
        self.proc: Optional[subprocess.Popen] = None
        self._display: Optional[int] = None

    @property
    def xvfb_args(self) -> tuple:
        return (
            # fmt: off
            "-screen", "0", self.screen,
            "-ac",
            "-nolisten", "tcp",
            "-extension", "RENDER",
            "+extension", "GLX",
            "+extension" if self.composite else "-extension", "COMPOSITE",
            "-extension", "XVideo",
            "-extension", "XVideo-MotionCompensation",
            "-extension", "XINERAMA",
            "-fp", "built-ins",
            "-nocursor",
            "-br",
            # fmt: on
        )

    @property
    def xvfb_path(self) -> str:
        path = which("Xvfb")
        if not path:
            raise CannotFindXvfb("Please install Xvfb to use headless mode.")
        if not os.access(path, os.X_OK):
            raise CannotExecuteXvfb(f"I do not have permission to execute Xvfb: {path}")
        return path

    def get(self) -> str:
        self._assert_linux()

        if self.proc is None:
            # Launch Xvfb with -displayfd so Xvfb itself picks a free display
            # number atomically and reports it back. Avoids userspace races.
            # subprocess.Popen's pass_fds keeps an fd at its parent number in
            # the child (unlike Node's `stdio: [..., 'pipe']` which renumbers
            # to 3), so we tell Xvfb that exact number.
            read_fd, write_fd = os.pipe()
            cmd = [self.xvfb_path, "-displayfd", str(write_fd), *self.xvfb_args]
            if self.debug:
                print("Starting virtual display:", " ".join(cmd))
            self.proc = subprocess.Popen(  # nosec
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=None if self.debug else subprocess.DEVNULL,
                stderr=None if self.debug else subprocess.DEVNULL,
                start_new_session=True,
                pass_fds=(write_fd,),
                env={
                    **os.environ,
                    # Force Mesa software GLX; we don't use the GPU anyway.
                    "__GLX_VENDOR_LIBRARY_NAME": "mesa",
                    "LIBGL_ALWAYS_SOFTWARE": "1",
                },
            )
            os.close(write_fd)  # so the read end EOFs when Xvfb closes its end

            buf = b""
            deadline = time.monotonic() + DISPLAYFD_READ_TIMEOUT_S
            try:
                while b"\n" not in buf:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not select.select([read_fd], [], [], remaining)[0]:
                        self.kill()
                        raise CannotExecuteXvfb(
                            f"Xvfb did not report a display within "
                            f"{int(DISPLAYFD_READ_TIMEOUT_S * 1000)}ms"
                        )
                    chunk = os.read(read_fd, 64)
                    if not chunk:
                        self.kill()
                        raise CannotExecuteXvfb(
                            f"Xvfb did not report a display "
                            f"(got {buf!r}, exit={self.proc.poll()})"
                        )
                    buf += chunk
            finally:
                os.close(read_fd)

            try:
                self._display = int(buf.strip())
            except ValueError:
                self.kill()
                raise CannotExecuteXvfb(f"Xvfb wrote non-integer display: {buf!r}")
        elif self.debug:
            print(f"Using virtual display: {self._display}")

        return f":{self._display}"

    def kill(self) -> None:
        if self.proc and self.proc.poll() is None:
            if self.debug:
                print("Terminating virtual display:", self._display)
            try:
                self.proc.send_signal(signal.SIGKILL)
                self.proc.wait(timeout=5)
            except Exception:
                pass
            try:
                os.remove(f"/tmp/.X{self._display}-lock")
            except FileNotFoundError:
                pass
            try:
                os.remove(f"/tmp/.X11-unix/X{self._display}")
            except FileNotFoundError:
                pass
            self.proc = None

    @staticmethod
    def _assert_linux() -> None:
        if OS_NAME != "lin":
            raise VirtualDisplayNotSupported("Virtual display is only supported on Linux.")
