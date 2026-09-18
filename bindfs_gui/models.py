"""Data types shared between the mount backend, history store, and UI."""

from __future__ import annotations

from dataclasses import dataclass, field
import uuid


@dataclass
class HistoryEntry:
    source: str
    target: str
    read_only: bool = False
    advanced_flags: str = ""
    last_used: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "read_only": self.read_only,
            "advanced_flags": self.advanced_flags,
            "last_used": self.last_used,
        }

    @staticmethod
    def from_json(data: dict) -> "HistoryEntry":
        return HistoryEntry(
            id=data.get("id") or uuid.uuid4().hex,
            source=data["source"],
            target=data["target"],
            read_only=bool(data.get("read_only", False)),
            advanced_flags=data.get("advanced_flags", ""),
            last_used=data.get("last_used", ""),
        )


@dataclass
class ActiveMount:
    """A bindfs mount currently live on the system, found via /proc."""

    source: str
    target: str
    read_only: bool
    options: str
    pid: int
