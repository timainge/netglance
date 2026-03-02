"""macOS launchd integration for netglance daemon.

Generates, installs, and manages a LaunchAgent plist so that netglance can run
as a persistent background service on macOS.
"""

from __future__ import annotations

import plistlib
import shutil
import sys
from pathlib import Path
from typing import Callable

PLIST_LABEL = "com.netglance.daemon"
PLIST_DIR = Path.home() / "Library" / "LaunchAgents"
PLIST_PATH = PLIST_DIR / f"{PLIST_LABEL}.plist"

LOG_DIR = Path.home() / ".config" / "netglance"
LOG_PATH = LOG_DIR / "daemon.log"


def _resolve_netglance_path() -> str:
    """Find the ``netglance`` executable on the current PATH."""
    found = shutil.which("netglance")
    if found:
        return found
    # Fallback: use the Python interpreter running this process
    return f"{sys.executable} -m netglance.cli"


def generate_plist(
    netglance_path: str | None = None,
    config_path: str | None = None,
) -> dict:
    """Build the launchd plist as a Python dict.

    Parameters
    ----------
    netglance_path:
        Absolute path to the ``netglance`` binary.  Auto-detected when ``None``.
    config_path:
        Optional path to a config YAML.  When given, ``--config <path>`` is
        appended to ProgramArguments.
    """
    exe = netglance_path or _resolve_netglance_path()
    args = [exe, "daemon", "start"]
    if config_path:
        args.extend(["--config", config_path])

    plist: dict = {
        "Label": PLIST_LABEL,
        "ProgramArguments": args,
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(LOG_PATH),
        "StandardErrorPath": str(LOG_PATH),
        "WorkingDirectory": str(Path.home()),
    }
    return plist


def install_plist(
    netglance_path: str | None = None,
    config_path: str | None = None,
    *,
    _plist_dir: Path | None = None,
    _log_dir: Path | None = None,
) -> Path:
    """Write the plist to ``~/Library/LaunchAgents/`` and return its path.

    The ``_plist_dir`` and ``_log_dir`` parameters exist for testability
    (avoids writing to real system directories in tests).
    """
    plist = generate_plist(netglance_path=netglance_path, config_path=config_path)

    target_dir = _plist_dir if _plist_dir is not None else PLIST_DIR
    log_dir = _log_dir if _log_dir is not None else LOG_DIR

    target_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    target_path = target_dir / f"{PLIST_LABEL}.plist"
    with open(target_path, "wb") as fp:
        plistlib.dump(plist, fp)

    return target_path


def uninstall_plist(
    *,
    _plist_dir: Path | None = None,
) -> bool:
    """Remove the plist file.  Returns ``True`` if it existed."""
    target_dir = _plist_dir if _plist_dir is not None else PLIST_DIR
    target_path = target_dir / f"{PLIST_LABEL}.plist"

    if target_path.exists():
        target_path.unlink()
        return True
    return False


def is_installed(
    *,
    _plist_dir: Path | None = None,
) -> bool:
    """Check whether the plist file is currently installed."""
    target_dir = _plist_dir if _plist_dir is not None else PLIST_DIR
    target_path = target_dir / f"{PLIST_LABEL}.plist"
    return target_path.exists()


def get_plist_path() -> Path:
    """Return the expected plist file path."""
    return PLIST_PATH
