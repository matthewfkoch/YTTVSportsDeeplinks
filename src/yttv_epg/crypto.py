from __future__ import annotations

import base64
import hashlib
import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


def fernet_from_secret(secret: str) -> Fernet:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def load_or_create_secret(path: Path, configured: str) -> str:
    if configured.strip():
        return configured.strip()
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    secret = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(secret)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return secret


def encrypt(secret: str, payload: bytes) -> bytes:
    return fernet_from_secret(secret).encrypt(payload)


def decrypt(secret: str, blob: bytes) -> bytes:
    try:
        return fernet_from_secret(secret).decrypt(blob)
    except InvalidToken as exc:
        raise ValueError("Could not decrypt the saved session. Check YTTV_EPG_SECRET.") from exc
