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
#
# 30 s, not 10 s (#157). The first Xvfb on a fresh machine is slow and its
# time varies widely. Six fresh ubuntu-24.04 runners measured 603, 983, 2620,
# 4603, 5150 and 8434 ms for their first launch, then 25-39 ms for every
# launch after it. One CI run missed the old 10 s bound outright. A hung Xvfb
# still fails, just later.
DISPLAYFD_READ_TIMEOUT_S = 30.0

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
# Juggler has two video paths, and which one runs depends on the Playwright
# version, not on the browser:
#
#   Playwright <=1.57: record_video_dir -> Browser.setVideoRecordingOptions ->
#     PageTarget._startVideoRecording (additions/juggler/TargetRegistry.js) ->
#     the native screencast recorder, with no headless check. Under Xvfb that is
#     libwebrtc's X11 window capturer, which delivers no frames without
#     Composite.
#   Playwright >=1.58: record_video_dir -> Page.startScreencast, which takes
#     compositor snapshots whenever the browser is not headless. Composite is
#     irrelevant there.
#
# pythonlib allows both (`playwright<1.63`), so Composite has to be on. Measured
# on ONE binary (build 35586323562, 152.0.4-beta.31; probe run 35622975837, #136),
# smoke.yml's guard page, bytes of the recorded .webm:
#
#                                         Playwright 1.55.0   Playwright 1.62.0
#   headless=True, no Xvfb (control)             48680              58375
#   headless="virtual", Composite off              110 (0 frames)   59716
#   headless="virtual", Composite on             54370              60326
#
# A 4 Hz black/white page confirmed each non-empty cell holds real frames (mean
# luma swinging ~16-235), and Composite on crashed in neither version.
#
# History, so the next reader does not flip this again: efb0a09 turned it on for
# exactly this failure; e25a16b turned it off after a probe that ran Playwright
# 1.62 -- the path that never needed it -- and read the result as a browser fix.
# Escape hatch: CAMOUFOX_VIRTUAL_DISPLAY_COMPOSITE=0 disables it.
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
        """Stop Xvfb if it is running, and remove its lock and socket either way.

        The cleanup deliberately does NOT depend on whether we did the killing.
        It used to: the whole body sat behind `self.proc.poll() is None`, so a
        display whose Xvfb had already died -- crashed, OOM-killed, or reaped
        with the browser's process group -- was never cleaned up at all.

        That is backwards. A SIGKILLed Xvfb never gets to remove its own socket,
        so the crash path is precisely the one where /tmp/.X11-unix/X<n> is left
        behind. Those accumulate, and because -displayfd scans upward for a free
        number, every stranded socket pushes the next display higher until a
        long-running host stops being able to allocate one.
        """
        if not self.proc:
            return

        if self.proc.poll() is None:
            if self.debug:
                print("Terminating virtual display:", self._display)
            try:
                self.proc.send_signal(signal.SIGKILL)
                self.proc.wait(timeout=5)
            except Exception:
                pass
        elif self.debug:
            print("Virtual display already exited:", self._display)

        for path in (
            f"/tmp/.X{self._display}-lock",
            f"/tmp/.X11-unix/X{self._display}",
        ):
            try:
                os.remove(path)
            except OSError:
                # Missing is the normal case; anything else (a permission error
                # from a number another user has since claimed) must not take
                # down a teardown path.
                pass

        self.proc = None

    @staticmethod
    def _assert_linux() -> None:
        if OS_NAME != "lin":
            raise VirtualDisplayNotSupported("Virtual display is only supported on Linux.")
