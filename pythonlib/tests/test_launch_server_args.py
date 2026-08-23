"""#161: launch_server() must reject persistent_context / user_data_dir with a
clear error (Playwright's launchServer has no persistent-context mode) instead
of silently dropping them or crashing with a cryptic TypeError.

The guard runs before any launch_options()/node spawn, so these tests never
start a browser."""

import pytest

from camoufox.server import launch_server


def test_launch_server_rejects_persistent_context():
    with pytest.raises(ValueError, match="persistent_context"):
        launch_server(persistent_context=True)


def test_launch_server_rejects_user_data_dir():
    with pytest.raises(ValueError, match="user_data_dir"):
        launch_server(user_data_dir="/tmp/session")


def test_launch_server_rejects_both_together():
    # Rejection is per-option, so passing both reports the first one hit.
    with pytest.raises(ValueError, match="cannot serve a persistent context"):
        launch_server(persistent_context=True, user_data_dir="/tmp/session")
