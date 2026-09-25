"""One small interface over the three ways users drive Camoufox."""

from pathlib import Path


def make(name: str, binary: Path):
    if name == "pkg":
        from .playwright_drivers import PkgDriver
        return PkgDriver(binary)
    if name == "pw":
        from .playwright_drivers import PwDriver
        return PwDriver(binary)
    if name == "go":
        from .go import GoDriver
        return GoDriver(binary)
    raise ValueError(f"unknown driver {name!r}")
