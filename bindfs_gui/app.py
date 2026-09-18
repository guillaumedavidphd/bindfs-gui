"""GTK4 + libadwaita application entry point."""

from __future__ import annotations

import sys

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, Gtk

from .window import MainWindow

APP_ID = "com.gdavid.BindfsGui"

_CSS = b"""
.mount-status-dot {
    border-radius: 9999px;
    min-width: 10px;
    min-height: 10px;
}
.mount-status-dot.active { background-color: @success_color; }
.mount-status-dot.inactive { background-color: alpha(@window_fg_color, 0.25); }
"""


class Application(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(_CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self) -> None:
        window = self.props.active_window or MainWindow(application=self)
        window.present()


def main() -> int:
    return Application().run(sys.argv)
