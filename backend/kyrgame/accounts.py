from __future__ import annotations

from dataclasses import dataclass

from pwdlib import PasswordHash


_PASSWORD_HASH = PasswordHash.recommended()


@dataclass(frozen=True)
class PasswordVerification:
    valid: bool
    updated_hash: str | None = None


def normalize_userid(userid: str) -> str:
    return userid.strip().lower()


def hash_password(password: str) -> str:
    return _PASSWORD_HASH.hash(password)


def verify_password(password: str, stored_hash: str) -> PasswordVerification:
    valid, updated_hash = _PASSWORD_HASH.verify_and_update(password, stored_hash)
    return PasswordVerification(valid=valid, updated_hash=updated_hash)
