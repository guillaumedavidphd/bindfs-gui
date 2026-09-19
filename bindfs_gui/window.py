"""The single window: a new-mount form plus one merged list of every
history entry and every currently-active bindfs mount, live status included.
"""

from __future__ import annotations

import os
import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, GLib

from . import history, mounts, persistence
from .models import ActiveMount, HistoryEntry

_ACTIVE_KNOWN = "active_known"
_ACTIVE_UNMANAGED = "active_unmanaged"
_INACTIVE = "inactive"


def _normalized(path: str) -> str:
    return os.path.normpath(path)


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs, title="BindFS Mounts", default_width=560, default_height=680)

        self._source_path: str | None = None
        self._target_path: str | None = None
        self._history: list[HistoryEntry] = []
        self._active: list[ActiveMount] = []
        self._mount_rows: list[Gtk.Widget] = []

        self._build_ui()
        self.refresh()

    # -- UI construction ---------------------------------------------------

    def _build_ui(self) -> None:
        toolbar_view = Adw.ToolbarView()

        header = Adw.HeaderBar()
        refresh_button = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Refresh")
        refresh_button.connect("clicked", lambda _b: self.refresh())
        header.pack_end(refresh_button)
        toolbar_view.add_top_bar(header)

        self._toast_overlay = Adw.ToastOverlay()

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24,
                               margin_top=24, margin_bottom=24, margin_start=24, margin_end=24)
        content_box.append(self._build_new_mount_group())

        self._mounts_group = Adw.PreferencesGroup(title="Mounts")
        content_box.append(self._mounts_group)

        scrolled = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        scrolled.set_child(content_box)

        self._toast_overlay.set_child(scrolled)
        toolbar_view.set_content(self._toast_overlay)
        self.set_content(toolbar_view)

    def _build_new_mount_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="New Mount")

        self._source_row = Adw.ActionRow(title="Source folder", subtitle="Not selected")
        source_browse = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER,
                                    css_classes=["flat"])
        source_browse.connect("clicked", self._on_browse_source)
        self._source_row.add_suffix(source_browse)
        group.add(self._source_row)

        self._target_row = Adw.ActionRow(title="Target folder", subtitle="Not selected")
        target_browse = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER,
                                    css_classes=["flat"])
        target_browse.connect("clicked", self._on_browse_target)
        self._target_row.add_suffix(target_browse)
        group.add(self._target_row)

        self._read_only_row = Adw.SwitchRow(title="Read-only", subtitle="Mount with -o ro")
        group.add(self._read_only_row)

        self._advanced_row = Adw.EntryRow(title="Advanced bindfs flags (optional)")
        group.add(self._advanced_row)

        self._mount_button = Gtk.Button(label="Mount", css_classes=["suggested-action", "pill"],
                                         halign=Gtk.Align.END, sensitive=False)
        self._mount_button.connect("clicked", self._on_mount_clicked)
        button_box = Gtk.Box(halign=Gtk.Align.END, margin_top=6)
        button_box.append(self._mount_button)
        group.add(button_box)

        return group

    # -- Source/target pickers ----------------------------------------------

    def _on_browse_source(self, _button: Gtk.Button) -> None:
        Gtk.FileDialog(title="Choose source folder").select_folder(self, None, self._on_source_chosen)

    def _on_source_chosen(self, dialog: Gtk.FileDialog, result) -> None:
        try:
            gfile = dialog.select_folder_finish(result)
        except GLib.Error:
            return
        self._source_path = gfile.get_path()
        self._source_row.set_subtitle(self._source_path)
        self._update_mount_button_sensitivity()

    def _on_browse_target(self, _button: Gtk.Button) -> None:
        Gtk.FileDialog(title="Choose target folder").select_folder(self, None, self._on_target_chosen)

    def _on_target_chosen(self, dialog: Gtk.FileDialog, result) -> None:
        try:
            gfile = dialog.select_folder_finish(result)
        except GLib.Error:
            return
        self._target_path = gfile.get_path()
        self._target_row.set_subtitle(self._target_path)
        self._update_mount_button_sensitivity()

    def _update_mount_button_sensitivity(self) -> None:
        self._mount_button.set_sensitive(bool(self._source_path and self._target_path))

    # -- Mount / unmount / save / delete actions -----------------------------

    def _on_mount_clicked(self, _button: Gtk.Button) -> None:
        source, target = self._source_path, self._target_path
        read_only = self._read_only_row.get_active()
        advanced_flags = self._advanced_row.get_text()

        def work():
            mounts.do_mount(source, target, read_only, advanced_flags)

        def done(_result, error):
            if error is not None:
                self._show_error("Could not mount", str(error))
                return
            self._history = history.upsert_entry(self._history, source, target, read_only, advanced_flags)
            history.save_history(self._history)
            self._toast(f"Mounted {target}")
            self.refresh()

        self._run_async(work, done)

    def _remount_entry(self, entry: HistoryEntry) -> None:
        def work():
            mounts.do_mount(entry.source, entry.target, entry.read_only, entry.advanced_flags)

        def done(_result, error):
            if error is not None:
                self._show_error("Could not mount", str(error))
                return
            self._history = history.upsert_entry(self._history, entry.source, entry.target,
                                                   entry.read_only, entry.advanced_flags)
            history.save_history(self._history)
            self._toast(f"Mounted {entry.target}")
            self.refresh()

        self._run_async(work, done)

    def _on_unmount_clicked(self, target: str) -> None:
        def work():
            mounts.do_unmount(target)

        def done(_result, error):
            if error is not None:
                if isinstance(error, mounts.UnmountError) and error.busy:
                    self._show_error("Target is busy", f"{target} is still in use. Close any open "
                                      f"files or programs using it, then try again.\n\n{error}")
                else:
                    self._show_error("Could not unmount", str(error))
                return
            self._toast(f"Unmounted {target}")
            self.refresh()

        self._run_async(work, done)

    def _on_save_to_history_clicked(self, active_mount: ActiveMount) -> None:
        self._history = history.upsert_entry(self._history, active_mount.source, active_mount.target,
                                              active_mount.read_only, "")
        history.save_history(self._history)
        self._toast("Saved to history")
        self.refresh()

    def _on_delete_clicked(self, entry: HistoryEntry) -> None:
        dialog = Adw.AlertDialog(heading="Delete this entry?",
                                  body=f"Remove {entry.target} from history. "
                                       "This does not unmount it if it's currently active.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_delete_confirmed, entry.id)
        dialog.present(self)

    def _on_delete_confirmed(self, _dialog: Adw.AlertDialog, response: str, entry_id: str) -> None:
        if response != "delete":
            return
        self._history = history.remove_entry(self._history, entry_id)
        history.save_history(self._history)
        self._toast("Deleted")
        self.refresh()

    def _on_mount_at_login_toggled(self, switch: Gtk.Switch, requested: bool,
                                    entry: HistoryEntry) -> bool:
        try:
            if requested:
                persistence.enable(entry)
            else:
                persistence.disable(entry.id)
        except Exception as exc:  # noqa: BLE001 -- surfaced to the user, not swallowed
            self._show_error("Could not update login persistence", str(exc))
            return True  # leave the switch showing its previous (unconfirmed) state

        entry.mount_at_login = requested
        history.save_history(self._history)
        switch.set_state(requested)
        self._toast("Will mount at login" if requested else "Removed from login mounts")
        return True

    # -- Background work / feedback helpers ----------------------------------

    def _run_async(self, work, done) -> None:
        def thread_body():
            try:
                result = work()
                error = None
            except Exception as exc:  # noqa: BLE001 -- surfaced to the user, not swallowed
                result = None
                error = exc

            def invoke():
                done(result, error)
                return False

            GLib.idle_add(invoke)

        threading.Thread(target=thread_body, daemon=True).start()

    def _toast(self, message: str) -> None:
        self._toast_overlay.add_toast(Adw.Toast(title=message))

    def _show_error(self, heading: str, body: str) -> None:
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.set_body_use_markup(False)
        dialog.add_response("ok", "OK")
        dialog.present(self)

    # -- List rendering -------------------------------------------------------

    def refresh(self) -> None:
        self._active = mounts.list_active_mounts()
        self._history = history.load_history()
        self._rebuild_mounts_list()

    def _rebuild_mounts_list(self) -> None:
        for row in self._mount_rows:
            self._mounts_group.remove(row)
        self._mount_rows = []

        active_by_key = {(_normalized(am.source), _normalized(am.target)): am for am in self._active}
        matched_keys = set()

        merged = []
        for entry in self._history:
            key = (_normalized(entry.source), _normalized(entry.target))
            active_mount = active_by_key.get(key)
            if active_mount is not None:
                matched_keys.add(key)
                merged.append((_ACTIVE_KNOWN, entry, active_mount))
            else:
                merged.append((_INACTIVE, entry, None))

        for key, active_mount in active_by_key.items():
            if key not in matched_keys:
                merged.append((_ACTIVE_UNMANAGED, None, active_mount))

        merged.sort(key=lambda item: item[0] == _INACTIVE)

        if not merged:
            placeholder = Adw.ActionRow(title="No mounts yet",
                                         subtitle="Pick a source and target above, then click Mount.")
            self._mounts_group.add(placeholder)
            self._mount_rows.append(placeholder)
            return

        for state, entry, active_mount in merged:
            row = self._build_mount_row(state, entry, active_mount)
            self._mounts_group.add(row)
            self._mount_rows.append(row)

    def _build_mount_row(self, state: str, entry: HistoryEntry | None,
                          active_mount: ActiveMount | None) -> Adw.ActionRow:
        target = active_mount.target if active_mount else entry.target
        source = active_mount.source if active_mount else entry.source
        read_only = active_mount.read_only if active_mount else entry.read_only
        mode = "read-only" if read_only else "read-write"

        row = Adw.ActionRow(title=target)

        dot = Gtk.Box(width_request=10, height_request=10, valign=Gtk.Align.CENTER)
        dot.add_css_class("mount-status-dot")
        dot.add_css_class("inactive" if state == _INACTIVE else "active")
        row.add_prefix(dot)

        login_suffix = " · mounts at login" if entry and entry.mount_at_login else ""

        if state == _ACTIVE_KNOWN:
            row.set_subtitle(f"{source} · {mode} · mounted{login_suffix}")
            self._add_login_switch(row, entry)
            unmount_button = Gtk.Button(label="Unmount", valign=Gtk.Align.CENTER)
            unmount_button.connect("clicked", lambda _b: self._on_unmount_clicked(target))
            row.add_suffix(unmount_button)
        elif state == _ACTIVE_UNMANAGED:
            row.set_subtitle(f"{source} · {mode} · mounted, not saved")
            save_button = Gtk.Button(label="Save to history", valign=Gtk.Align.CENTER)
            save_button.connect("clicked", lambda _b: self._on_save_to_history_clicked(active_mount))
            row.add_suffix(save_button)
            unmount_button = Gtk.Button(label="Unmount", valign=Gtk.Align.CENTER)
            unmount_button.connect("clicked", lambda _b: self._on_unmount_clicked(target))
            row.add_suffix(unmount_button)
        else:
            row.set_subtitle(f"{source} · {mode} · not mounted{login_suffix}")
            self._add_login_switch(row, entry)
            mount_button = Gtk.Button(label="Mount", valign=Gtk.Align.CENTER)
            mount_button.connect("clicked", lambda _b: self._remount_entry(entry))
            row.add_suffix(mount_button)
            delete_button = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
                                        css_classes=["flat"], tooltip_text="Delete from history")
            delete_button.connect("clicked", lambda _b: self._on_delete_clicked(entry))
            row.add_suffix(delete_button)

        return row

    def _add_login_switch(self, row: Adw.ActionRow, entry: HistoryEntry) -> None:
        switch = Gtk.Switch(valign=Gtk.Align.CENTER, tooltip_text="Mount at login")
        switch.set_active(entry.mount_at_login)
        switch.set_state(entry.mount_at_login)
        switch.connect("state-set", self._on_mount_at_login_toggled, entry)
        row.add_suffix(switch)
