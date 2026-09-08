from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from yttv_epg.crypto import decrypt, encrypt, load_or_create_secret


@dataclass
class SavedSession:
    kind: str
    cookies: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "cookies": self.cookies}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Optional["SavedSession"]:
        cookies = data.get("cookies")
        if data.get("kind") == "cookies" and isinstance(cookies, list):
            return cls(kind="cookies", cookies=[c for c in cookies if isinstance(c, dict)])
        return None


class SessionStore:
    def __init__(self, data_dir: Path, configured_secret: str) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.secret = load_or_create_secret(data_dir / ".secret", configured_secret)
        self.path = data_dir / "session.enc"
        self.legacy_path = data_dir / "token.enc"

    def load(self) -> Optional[SavedSession]:
        path = self.path if self.path.exists() else self.legacy_path
        if not path.exists():
            return None
        raw = decrypt(self.secret, path.read_bytes())
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            return None
        session = SavedSession.from_dict(data)
        if session is None and path == self.legacy_path:
            # Old OAuth tokens cannot sign in to YouTube TV; drop them.
            path.unlink(missing_ok=True)
        return session

    def save(self, session: SavedSession) -> None:
        blob = encrypt(self.secret, json.dumps(session.to_dict()).encode("utf-8"))
        self.path.write_bytes(blob)
        self.path.chmod(0o600)
        if self.legacy_path.exists():
            self.legacy_path.unlink()

    def clear(self) -> None:
        for path in (self.path, self.legacy_path):
            if path.exists():
                path.unlink()

    @property
    def signed_in(self) -> bool:
        return self.load() is not None
