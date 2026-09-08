from __future__ import annotations

from pathlib import Path

from yttv_epg.crypto import decrypt, encrypt, load_or_create_secret


def test_round_trip_encryption():
    blob = encrypt("unit-test-secret", b'{"ok": true}')
    assert blob != b'{"ok": true}'
    assert decrypt("unit-test-secret", blob) == b'{"ok": true}'


def test_generated_secret_stays_stable(tmp_path: Path):
    path = tmp_path / ".secret"
    first = load_or_create_secret(path, "")
    second = load_or_create_secret(path, "")
    assert first == second
    assert path.stat().st_mode & 0o777 == 0o600
