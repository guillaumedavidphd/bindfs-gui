"""Make a mount survive a reboot -- in practice, the next graphical login,
since nothing here uses sudo/pkexec/linger.

Each persisted history entry gets its own systemd --user unit under
~/.config/systemd/user/, WantedBy=default.target -- the same proven,
sudo-free mechanism as a hand-written unit would use. A shared oneshot
template unit fires a desktop notification via each unit's OnFailure=, so a
mount that doesn't come back at login isn't silently missing.
"""

from __future__ import annotations

from pathlib import Path
import shlex
import subprocess

from . import mounts
from .models import HistoryEntry

SYSTEMD_USER_DIR = Path.home() / ".config" / "systemd" / "user"
_UNIT_PREFIX = "bindfs-gui-mount-"
_FAILURE_TEMPLATE_NAME = "bindfs-gui-mount-failed@"
_SYSTEMCTL_TIMEOUT_S = 15


class PersistenceError(Exception):
    """A systemctl call failed. Carries its stderr."""


def unit_name(entry_id: str) -> str:
    return f"{_UNIT_PREFIX}{entry_id}.service"


def _unit_path(entry_id: str) -> Path:
    return SYSTEMD_USER_DIR / unit_name(entry_id)


def is_enabled(entry_id: str) -> bool:
    return _unit_path(entry_id).exists()


def _run_systemctl(*args: str) -> None:
    result = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True,
                             timeout=_SYSTEMCTL_TIMEOUT_S)
    if result.returncode != 0:
        raise PersistenceError(result.stderr.strip() or result.stdout.strip() or
                                f"systemctl {' '.join(args)} exited with status {result.returncode}")


def _quote(argv: list[str]) -> str:
    return " ".join(shlex.quote(arg) for arg in argv)


def _ensure_failure_notifier() -> None:
    path = SYSTEMD_USER_DIR / f"{_FAILURE_TEMPLATE_NAME}.service"
    if path.exists():
        return
    SYSTEMD_USER_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[Unit]\n"
        "Description=Notify that %i failed to mount\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        'ExecStart=/usr/bin/notify-send -u critical "BindFS mount failed" '
        '"%i did not come back. Open BindFS Mounts to check it."\n'
    )
    _run_systemctl("daemon-reload")


def enable(entry: HistoryEntry) -> None:
    """Register entry to mount at the next login. Does not mount it now."""
    fusermount_bin = mounts.find_fusermount()
    if not fusermount_bin:
        raise mounts.UnmountError("Neither fusermount3 nor fusermount was found.", busy=False)
    mount_argv = mounts.build_mount_argv(entry.source, entry.target, entry.read_only, entry.advanced_flags)

    _ensure_failure_notifier()
    SYSTEMD_USER_DIR.mkdir(parents=True, exist_ok=True)
    _unit_path(entry.id).write_text(
        "[Unit]\n"
        f"Description=bindfs mount: {entry.source} -> {entry.target} (bindfs-gui)\n"
        f"OnFailure={_FAILURE_TEMPLATE_NAME}%n.service\n"
        "\n"
        "[Service]\n"
        f"ExecStart={_quote(mount_argv)}\n"
        f"ExecStop={_quote([fusermount_bin, '-u', entry.target])}\n"
        "RemainAfterExit=yes\n"
        "Restart=on-failure\n"
        "StartLimitBurst=2\n"
        "StartLimitIntervalSec=30\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )
    _run_systemctl("daemon-reload")
    _run_systemctl("enable", unit_name(entry.id))


def disable(entry_id: str) -> None:
    """Deregister entry from mounting at login. Does not unmount it now."""
    path = _unit_path(entry_id)
    if not path.exists():
        return
    _run_systemctl("disable", unit_name(entry_id))
    path.unlink(missing_ok=True)
    _run_systemctl("daemon-reload")
