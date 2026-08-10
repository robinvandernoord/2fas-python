"""
This file stores per-vault blobs (currently: keys wrapped by a hardware token) on disk.

Layout: ~/.config/2fas/keys/<vault_id>.json, one file per vault, mode 0600.

`vault_id` is sha256 of the vault's PBKDF2 salt, not of its path. That is deliberate:

- it survives renaming and moving the .2fas file;
- it self-invalidates when the user re-exports their vault from their phone, because a
  new export means a new salt, so there is simply no entry and the passphrase is asked
  for again. Keying on the path would instead produce a *wrong* blob, which surfaces as
  a spurious "invalid passphrase" through the retry loop in lib2fas.
"""

import base64
import hashlib
import json
import os
import time
import typing
from pathlib import Path

from .cli_settings import KEYS_DIR

# Bump this whenever a stored blob stops being readable by the current code - including
# when `security_key.HKDF_INFO_PREFIX` changes, since that silently changes the wrapping
# key. An unreadable blob is rejected here and reads as "no security key set up", which
# sends the user to `--setup-key`; without the bump they would get a confusing
# "this key does not belong to that vault" instead.
CURRENT_VERSION = 2


def vault_id_for(salt: bytes) -> str:
    """
    Stable identifier for a vault, derived from the PBKDF2 salt inside the file.
    """
    return hashlib.sha256(salt).hexdigest()


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _unb64(data: str) -> bytes:
    return base64.b64decode(data)


class WrappedKey(typing.NamedTuple):
    """
    One vault's derived key, encrypted under a key that only the hardware token can produce.
    """

    vault_id: str
    credential_id: bytes
    hmac_salt: bytes
    nonce: bytes
    ciphertext: bytes
    rp_id: str
    filename_hint: str
    created: int

    def to_json(self) -> dict[str, typing.Any]:
        """
        Serializable form, as written to disk.
        """
        return {
            "version": CURRENT_VERSION,
            "vault_id": self.vault_id,
            "method": "fido2-hmac-secret",
            "rp_id": self.rp_id,
            "credential_id": _b64(self.credential_id),
            "hmac_salt": _b64(self.hmac_salt),
            "nonce": _b64(self.nonce),
            "ciphertext": _b64(self.ciphertext),
            # purely so a human can tell which entry is which; never used for lookup:
            "filename_hint": self.filename_hint,
            "created": self.created,
        }

    @classmethod
    def from_json(cls, data: dict[str, typing.Any]) -> "WrappedKey":
        """
        Parse a blob written by `to_json`.

        Raises:
            ValueError: on an unknown version or a malformed blob.
        """
        version = data.get("version")
        if version != CURRENT_VERSION:
            raise ValueError(f"Unsupported wrapped key version: {version}")

        try:
            return cls(
                vault_id=str(data["vault_id"]),
                credential_id=_unb64(data["credential_id"]),
                hmac_salt=_unb64(data["hmac_salt"]),
                nonce=_unb64(data["nonce"]),
                ciphertext=_unb64(data["ciphertext"]),
                rp_id=str(data.get("rp_id", "")),
                filename_hint=str(data.get("filename_hint", "")),
                created=int(data.get("created", 0)),
            )
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f"Malformed wrapped key: {e}") from e


class KeyStore:
    """
    Reads and writes the wrapped keys in ~/.config/2fas/keys.
    """

    directory: Path

    def __init__(self, directory: Path = KEYS_DIR) -> None:
        """
        Args:
            directory: where the blobs live; overridable for tests.
        """
        self.directory = directory

    def _path(self, vault_id: str) -> Path:
        return self.directory / f"{vault_id}.json"

    def get(self, vault_id: str) -> WrappedKey | None:
        """
        Load the wrapped key for a vault, or None if there is none (or it is unreadable).
        """
        path = self._path(vault_id)
        if not path.is_file():
            return None

        try:
            return WrappedKey.from_json(json.loads(path.read_text()))
        except (OSError, ValueError, json.JSONDecodeError):
            # a corrupt blob should not be fatal: the passphrase always still works.
            return None

    def put(self, wrapped: WrappedKey) -> Path:
        """
        Write (or replace) the wrapped key for a vault, readable only by this user.
        """
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)

        path = self._path(wrapped.vault_id)
        # write via a private temp file so a reader never sees a half-written blob,
        # and so the file is never briefly world-readable:
        tmp = path.with_suffix(".json.tmp")
        descriptor = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as f:
            json.dump(wrapped.to_json(), f, indent=2)

        tmp.replace(path)
        return path

    def delete(self, vault_id: str) -> bool:
        """
        Remove the wrapped key for a vault. Returns whether there was anything to remove.
        """
        path = self._path(vault_id)
        if not path.is_file():
            return False

        path.unlink()
        return True

    def all(self) -> list[WrappedKey]:
        """
        Every readable wrapped key currently stored.
        """
        if not self.directory.is_dir():
            return []

        result = []
        for path in sorted(self.directory.glob("*.json")):
            if wrapped := self.get(path.stem):
                result.append(wrapped)

        return result

    def prune(self, live_vault_ids: typing.Collection[str]) -> list[WrappedKey]:
        """
        Drop entries that can no longer belong to a vault this installation knows about.

        Deliberately conservative: an entry is only removed when its vault_id is not among
        the live ones *and* the file it was enrolled against is gone. A vault on a USB
        stick that happens to be unplugged should not lose its enrolment.

        Returns:
            the entries that were removed.
        """
        removed = []
        for wrapped in self.all():
            if wrapped.vault_id in live_vault_ids:
                continue
            if wrapped.filename_hint and Path(wrapped.filename_hint).exists():
                continue

            self.delete(wrapped.vault_id)
            removed.append(wrapped)

        return removed


def new_wrapped_key(
    vault_id: str,
    credential_id: bytes,
    hmac_salt: bytes,
    nonce: bytes,
    ciphertext: bytes,
    rp_id: str,
    filename_hint: str,
) -> WrappedKey:
    """
    Build a WrappedKey stamped with the current time.
    """
    return WrappedKey(
        vault_id=vault_id,
        credential_id=credential_id,
        hmac_salt=hmac_salt,
        nonce=nonce,
        ciphertext=ciphertext,
        rp_id=rp_id,
        filename_hint=filename_hint,
        created=int(time.time()),
    )
