import atexit
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, NoReturn, Tuple, Union

import base64
import orjson
from playwright._impl._driver import compute_driver_executable

from camoufox.pkgman import LOCAL_DATA
from camoufox.utils import launch_options

LAUNCH_SCRIPT: Path = LOCAL_DATA / "launchServer.js"


def camel_case(snake_str: str) -> str:
    """
    Convert a string to camelCase
    """
    if len(snake_str) < 2:
        return snake_str
    camel_case_str = ''.join(x.capitalize() for x in snake_str.lower().split('_'))
    return camel_case_str[0].lower() + camel_case_str[1:]


def to_camel_case_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert a dictionary to camelCase
    """
    return {camel_case(key): value for key, value in data.items()}


def get_nodejs() -> str:
    """
    Get the bundled Node.js executable
    """
    # Note: Older versions of Playwright return a string rather than a tuple.
    _nodejs: Union[str, Tuple[str, ...]] = compute_driver_executable()[0]
    if isinstance(_nodejs, tuple):
        return _nodejs[0]
    return _nodejs


def _terminate(process: subprocess.Popen) -> None:
    """
    Terminate a subprocess, escalating to kill() if it doesn't exit promptly.
    """
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def launch_server(**kwargs) -> NoReturn:
    """
    Launch a Playwright server. Takes the same arguments as `Camoufox()`.
    Prints the websocket endpoint to the console.
    """
    # Playwright's launchServer has no persistent-context mode, so these two
    # options cannot be honored in server mode. Fail loudly with guidance
    # instead of crashing later with a cryptic "unexpected keyword argument"
    # from launch_options() (#161).
    if kwargs.get('persistent_context') or kwargs.get('user_data_dir'):
        raise ValueError(
            "launch_server() does not support persistent_context / user_data_dir: "
            "Playwright's launchServer has no persistent-context mode. Use "
            "Camoufox(persistent_context=True, user_data_dir=...) for a persistent "
            "instance, or drop these arguments to launch an ephemeral server."
        )

    config = launch_options(**kwargs)
    nodejs = get_nodejs()

    data = orjson.dumps(to_camel_case_dict(config))

    process = subprocess.Popen(  # nosec
        [
            nodejs,
            str(LAUNCH_SCRIPT),
        ],
        cwd=Path(nodejs).parent / "package",
        stdin=subprocess.PIPE,
        text=True,
    )

    # Ensure the Node child is never orphaned: terminate it whenever this
    # process exits, including via SIGINT (KeyboardInterrupt, handled by
    # atexit during normal interpreter shutdown) and SIGTERM (which Python
    # does not translate into an exception by default, so it's handled
    # explicitly below).
    atexit.register(_terminate, process)
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(0))

    # Write data to stdin and close the stream
    if process.stdin:
        process.stdin.write(base64.b64encode(data).decode())
        process.stdin.close()

    # Wait forever
    process.wait()

    # Add an explicit return statement to satisfy the NoReturn type hint
    raise RuntimeError("Server process terminated unexpectedly")
