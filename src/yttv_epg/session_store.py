from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from yttv_epg.crypto import decrypt, encrypt, load_or_create_secret

log = logging.getLogger(__name__)


def _atomic_write(path: Path, data: bytes) -> None:
    fd, name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass
class SavedSession:
    kind: str
    cookies: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "cookies": self.cookies}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Optional["SavedSession"]:
        cookies = data.get("cookies")
        kind = data.get("kind")
        if kind in {"cookies", "browser"} and isinstance(cookies, list):
            return cls(kind=str(kind), cookies=[c for c in cookies if isinstance(c, dict)])
        return None


class SessionStore:
    def __init__(self, data_dir: Path, configured_secret: str) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.secret = load_or_create_secret(data_dir / ".secret", configured_secret)
        self.path = data_dir / "session.enc"
        self.legacy_path = data_dir / "token.enc"
        self.load_error = ""
        self._unreadable_path: Optional[Path] = None

    def load(self) -> Optional[SavedSession]:
        path = self.path if self.path.exists() else self.legacy_path
        if not path.exists():
            return None
        try:
            raw = decrypt(self.secret, path.read_bytes())
            data = json.loads(raw.decode("utf-8"))
            session = SavedSession.from_dict(data) if isinstance(data, dict) else None
            if session is None and path != self.legacy_path:
                raise ValueError("Invalid session structure")
        except (OSError, ValueError, UnicodeError):
            if not self.load_error:
                log.warning("Saved session could not be read; preserving it for recovery")
            self.load_error = "Saved session could not be read. Check YTTV_EPG_SECRET or sign in again. The original file is preserved."
            self._unreadable_path = path
            return None
        if session is None and path == self.legacy_path:
            # Old OAuth tokens cannot sign in to YouTube TV; drop them.
            path.unlink(missing_ok=True)
        self.load_error = ""
        self._unreadable_path = None
        return session

    def save(self, session: SavedSession) -> None:
        blob = encrypt(self.secret, json.dumps(session.to_dict()).encode("utf-8"))
        if self._unreadable_path is not None and self._unreadable_path.exists():
            # Never overwrite an earlier recovery copy.
            fd, name = tempfile.mkstemp(prefix="session-recovery-", suffix=".enc", dir=self.data_dir)
            os.close(fd)
            recovery = Path(name)
            try:
                _atomic_write(recovery, self._unreadable_path.read_bytes())
            except Exception:
                recovery.unlink(missing_ok=True)
                raise
        _atomic_write(self.path, blob)
        self.load_error = ""
        self._unreadable_path = None
        if self.legacy_path.exists():
            self.legacy_path.unlink()

    def clear(self) -> None:
        for path in (self.path, self.legacy_path):
            if path.exists():
                path.unlink()
        self.load_error = ""
        self._unreadable_path = None

    @property
    def signed_in(self) -> bool:
        return self.load() is not None
