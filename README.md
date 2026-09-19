# BindFS Mounts

GTK4 + libadwaita GUI for [bindfs](https://bindfs.org/) on Ubuntu. Mirrors a
folder at another path as your own user — no `sudo`, no `pkexec`, no
`allow_other`.

## Features

- Pick a source and target folder, click Mount.
- One list merges saved history with whatever's actually mounted right now
  (including mounts made outside the app) — a status dot shows live state.
- Read-only toggle (`-o ro`) and a free-form field for extra bindfs flags
  (`--perms`, `--map`, ...). Flags containing `allow_other` are rejected.
- Re-mount, unmount, or delete any history entry with one click.
- "Mount at login" toggle per entry, so it survives a reboot.
- Refresh button re-scans the system for active bindfs mounts.

## Requirements

- `bindfs` and FUSE3 (`sudo apt install bindfs` if `which bindfs` comes up
  empty — the app never installs anything itself).
- `python3-gi`, `gir1.2-gtk-4.0`, `gir1.2-adw-1` for the system Python
  (`/usr/bin/python3`). These ship with Ubuntu desktop; check with:
  ```
  /usr/bin/python3 -c "import gi; gi.require_version('Gtk','4.0'); gi.require_version('Adw','1'); from gi.repository import Gtk, Adw"
  ```

## Running

```
./bindfs-gui
```

The launcher's shebang points at `/usr/bin/python3` directly, so it works
even if `python3` on your `PATH` resolves elsewhere (e.g. Homebrew) and
lacks PyGObject.

To get it in your app launcher:

```
./install.sh
```

This symlinks `bindfs-gui` into `~/.local/bin` and copies `bindfs-gui.desktop`
into `~/.local/share/applications/`. The `.desktop` file's `Exec=` is just
`bindfs-gui` (resolved via `PATH`, already includes `~/.local/bin` on
Ubuntu) — it carries no machine-specific path, so it works from any clone
without editing. Re-run `install.sh` if you move this checkout.

## How it works

| Module | Responsibility |
|---|---|
| `bindfs_gui/mounts.py` | Runs `bindfs`/`fusermount3` (falls back to `fusermount`), validates paths before mounting, and lists active mounts. |
| `bindfs_gui/history.py` | Atomic read/write of `~/.local/share/bindfs-gui/history.json`. |
| `bindfs_gui/window.py` | The window: new-mount form + merged mount list. |
| `bindfs_gui/app.py` | `Adw.Application` bootstrap. |
| `bindfs_gui/models.py` | `HistoryEntry` / `ActiveMount` dataclasses. |
| `bindfs_gui/persistence.py` | Generates/enables/disables the systemd `--user` unit behind "Mount at login". |

**Active-mount detection**: `findmnt -t fuse.bindfs` doesn't work on every
system — some bindfs builds mount as plain `fuse` with no distinguishing
subtype, so type-filtering finds nothing even for a live bindfs mount.
Instead, `list_active_mounts()` cross-references running `bindfs` processes
(scanned from `/proc`, cmdline parsed for source/target) against
`/proc/self/mountinfo` (for live target and read-only/read-write state).
This also means mounts made outside the app show up automatically.

**Never `allow_other`**: bindfs adds `-o allow_other` itself unless told
not to, which would require `user_allow_other` in `/etc/fuse.conf`. Every
mount call passes `--no-allow-other` explicitly so this app never depends
on that system file, on any machine.

**Mount at login**: there's no sudo-free way to mount before you log in
(that needs `/etc/fstab` or a system-level systemd unit). Flipping the
toggle on a history entry instead writes a `systemd --user` unit —
`~/.config/systemd/user/bindfs-gui-mount-<entry-id>.service`, `WantedBy=
default.target` — the same mechanism a hand-written user unit would use,
so it starts the next time you log into a graphical session. It runs
`bindfs --no-allow-other` directly as `ExecStart`, and `fusermount3 -u` as
`ExecStop`, with `RemainAfterExit=yes` (bindfs daemonizes, so the direct
child exiting 0 isn't a failure) and `Restart=on-failure` (capped at 2
tries per 30s). Every such unit's `OnFailure=` points at a shared oneshot
template, `bindfs-gui-mount-failed@.service`, which fires a `notify-send`
desktop notification — so a source that's missing or not ready yet at
login surfaces instead of silently not being there. Flipping the toggle
only registers or deregisters the unit; it doesn't mount or unmount
anything immediately.

## History file

`~/.local/share/bindfs-gui/history.json` — one entry per (source, target)
pair: `source`, `target`, `read_only`, `advanced_flags`, `last_used`,
`mount_at_login`, `id`. Mounting again with the same source/target updates
the existing entry instead of duplicating it.

## Icon

`folder-blue-sync` from the [Papirus icon theme](https://github.com/PapirusDevelopmentTeam/papirus-icon-theme)
(GPLv3), resolved via the system icon theme.
