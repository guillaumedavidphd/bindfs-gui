"""Backend: run bindfs/fusermount and discover currently active bindfs mounts.

Never invokes sudo or pkexec, and never passes -o allow_other -- bindfs adds
that itself unless told not to, so every mount call passes --no-allow-other
explicitly.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess

from .models import ActiveMount

_MOUNTINFO_ESCAPE = re.compile(r"\\([0-7]{3})")
_SUBPROCESS_TIMEOUT_S = 20


class ValidationError(Exception):
    """A pre-flight check failed before any subprocess ran."""


class MountError(Exception):
    """bindfs exited with a non-zero status. Carries its stderr."""


class UnmountError(Exception):
    """fusermount exited with a non-zero status. Carries its stderr."""

    def __init__(self, message: str, busy: bool):
        super().__init__(message)
        self.busy = busy


def _unescape_mountinfo_field(field: str) -> str:
    return _MOUNTINFO_ESCAPE.sub(lambda m: chr(int(m.group(1), 8)), field)


def _find_on_path(*names: str) -> str | None:
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    for name in names:
        if os.path.exists(f"/usr/bin/{name}"):
            return f"/usr/bin/{name}"
    return None


def find_bindfs() -> str | None:
    return _find_on_path("bindfs")


def find_fusermount() -> str | None:
    """fusermount3 is preferred; fusermount is the fallback for older FUSE."""
    return _find_on_path("fusermount3", "fusermount")


def _read_mountinfo_by_target() -> dict[str, str]:
    """Map each live mount's target path to its raw superblock options."""
    targets: dict[str, str] = {}
    with open("/proc/self/mountinfo", "r") as handle:
        for line in handle:
            fields = line.split(" ")
            try:
                dash = fields.index("-")
            except ValueError:
                continue
            mount_point = _unescape_mountinfo_field(fields[4])
            super_options = fields[dash + 3].strip()
            targets[os.path.normpath(mount_point)] = super_options
    return targets


def _bindfs_processes() -> list[tuple[int, list[str]]]:
    """(pid, argv) for every currently running bindfs process."""
    processes = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        pid = int(name)
        try:
            with open(f"/proc/{pid}/comm", "r") as handle:
                comm = handle.read().strip()
            if comm != "bindfs":
                continue
            with open(f"/proc/{pid}/cmdline", "rb") as handle:
                raw = handle.read()
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        argv = [part.decode("utf-8", "surrogateescape") for part in raw.split(b"\0") if part]
        processes.append((pid, argv))
    return processes


def list_active_mounts() -> list[ActiveMount]:
    """Every bindfs mount live right now, ours or made outside the app."""
    mountinfo = _read_mountinfo_by_target()
    active = []
    for pid, argv in _bindfs_processes():
        if len(argv) < 3:
            continue
        source, target = argv[-2], argv[-1]
        options = mountinfo.get(os.path.normpath(target))
        if options is None:
            continue
        active.append(ActiveMount(
            source=source,
            target=target,
            read_only="ro" in options.split(","),
            options=options,
            pid=pid,
        ))
    return active


def _parse_advanced_flags(advanced_flags: str) -> list[str]:
    if "allow_other" in advanced_flags.lower():
        raise ValidationError(
            "Advanced flags may not include allow_other -- this app never "
            "enables it, since that would require editing /etc/fuse.conf."
        )
    try:
        return shlex.split(advanced_flags)
    except ValueError as exc:
        raise ValidationError(f"Could not parse advanced flags: {exc}") from exc


def build_mount_argv(source: str, target: str, read_only: bool, advanced_flags: str) -> list[str]:
    """The bindfs argv for this source/target/options. Used both to mount
    directly and to build a persistent (mount-at-login) unit's ExecStart."""
    bindfs_bin = find_bindfs()
    if not bindfs_bin:
        raise MountError("bindfs is not installed (checked PATH and /usr/bin).")

    argv = [bindfs_bin, "--no-allow-other"]
    if read_only:
        argv += ["-o", "ro"]
    argv += _parse_advanced_flags(advanced_flags)
    argv += [source, target]
    return argv


def do_mount(source: str, target: str, read_only: bool, advanced_flags: str) -> None:
    if not os.path.isdir(source):
        raise ValidationError(f"Source is not a directory: {source}")
    if not os.path.isdir(target):
        raise ValidationError(f"Target is not a directory: {target}")
    if os.path.ismount(target):
        raise ValidationError(f"Target is already a mount point: {target}")

    argv = build_mount_argv(source, target, read_only, advanced_flags)
    result = subprocess.run(argv, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT_S)
    if result.returncode != 0:
        raise MountError(result.stderr.strip() or result.stdout.strip() or
                          f"bindfs exited with status {result.returncode}")


def do_unmount(target: str) -> None:
    fusermount_bin = find_fusermount()
    if not fusermount_bin:
        raise UnmountError("Neither fusermount3 nor fusermount was found.", busy=False)

    result = subprocess.run([fusermount_bin, "-u", target], capture_output=True, text=True,
                             timeout=_SUBPROCESS_TIMEOUT_S)
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip() or \
            f"{os.path.basename(fusermount_bin)} exited with status {result.returncode}"
        raise UnmountError(stderr, busy="busy" in stderr.lower())
