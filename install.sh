#!/usr/bin/env bash
# Symlinks the launcher into ~/.local/bin and installs the .desktop entry.
# Both are user-level; nothing here touches the system.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="$HOME/.local/share/applications"

mkdir -p "$BIN_DIR" "$APPS_DIR"
chmod +x "$APP_DIR/bindfs-gui"
ln -sf "$APP_DIR/bindfs-gui" "$BIN_DIR/bindfs-gui"
cp "$APP_DIR/bindfs-gui.desktop" "$APPS_DIR/bindfs-gui.desktop"
update-desktop-database "$APPS_DIR" 2>/dev/null || true

echo "Linked $BIN_DIR/bindfs-gui -> $APP_DIR/bindfs-gui"
echo "Installed $APPS_DIR/bindfs-gui.desktop"
