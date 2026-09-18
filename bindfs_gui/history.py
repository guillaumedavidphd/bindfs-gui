"""Load and save ~/.local/share/bindfs-gui/history.json.

Every write is atomic (write to a temp file, then rename) so a crash or a
second instance can never leave the history file half-written.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path

from .models import HistoryEntry

HISTORY_DIR = Path.home() / ".local" / "share" / "bindfs-gui"
HISTORY_FILE = HISTORY_DIR / "history.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_history() -> list[HistoryEntry]:
    if not HISTORY_FILE.exists():
        return []
    try:
        raw = json.loads(HISTORY_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    entries = [HistoryEntry.from_json(item) for item in raw if "source" in item and "target" in item]
    entries.sort(key=lambda e: e.last_used, reverse=True)
    return entries


def save_history(entries: list[HistoryEntry]) -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = HISTORY_FILE.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps([e.to_json() for e in entries], indent=2))
    os.replace(tmp_path, HISTORY_FILE)


def upsert_entry(entries: list[HistoryEntry], source: str, target: str,
                  read_only: bool, advanced_flags: str) -> list[HistoryEntry]:
    """Add a new entry, or refresh an existing one for the same source/target pair."""
    key = (os.path.normpath(source), os.path.normpath(target))
    for entry in entries:
        if (os.path.normpath(entry.source), os.path.normpath(entry.target)) == key:
            entry.read_only = read_only
            entry.advanced_flags = advanced_flags
            entry.last_used = _now_iso()
            return entries
    entries.append(HistoryEntry(source=source, target=target, read_only=read_only,
                                 advanced_flags=advanced_flags, last_used=_now_iso()))
    return entries


def remove_entry(entries: list[HistoryEntry], entry_id: str) -> list[HistoryEntry]:
    return [e for e in entries if e.id != entry_id]
