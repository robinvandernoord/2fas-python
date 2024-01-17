import base64
import hashlib
import json
import logging
import sys
import time
from getpass import getpass
from pathlib import Path
from typing import Any, Optional

import cryptography.exceptions
import keyring
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from keyring.backend import KeyringBackend

from ._types import AnyDict, TwoFactorAuthDetails

# Suppress keyring warnings
keyring_logger = logging.getLogger("keyring")
keyring_logger.setLevel(logging.ERROR)  # Set the logging level to ERROR for keyring logger


def _decrypt(encrypted: str, passphrase: str) -> list[AnyDict]:
    # thanks https://github.com/wodny/decrypt-2fas-backup/blob/master/decrypt-2fas-backup.py
    credentials_enc, pbkdf2_salt, nonce = map(base64.b64decode, encrypted.split(":"))
    kdf = PBKDF2HMAC(algorithm=SHA256(), length=32, salt=pbkdf2_salt, iterations=10000)
    key = kdf.derive(passphrase.encode())
    aesgcm = AESGCM(key)
    credentials_dec = aesgcm.decrypt(nonce, credentials_enc, None)
    dec = json.loads(credentials_dec)  # type: list[AnyDict]
    if not isinstance(dec, list):
        raise TypeError("Unexpected data structure in input file.")
    return dec


def decrypt(encrypted: str, passphrase: str) -> list[TwoFactorAuthDetails]:
    try:
        dicts = _decrypt(encrypted, passphrase)
        return [TwoFactorAuthDetails.load(d) for d in dicts]
    except cryptography.exceptions.InvalidTag as e:
        # wrong passphrase!
        raise PermissionError("Invalid passphrase for file.") from e


def hash_string(data: Any) -> str:
    """
    Hashes a string using SHA-256.
    """
    sha256 = hashlib.sha256()
    sha256.update(str(data).encode())
    return sha256.hexdigest()


tmp = Path("/tmp")
tmp_file = tmp / ".2fas"

# APPNAME is session specific but with global prefix for easy clean up
PREFIX = "2fas:"

if tmp_file.exists() and (session := tmp_file.read_text()) and session.startswith(PREFIX):
    # existing session
    APPNAME = session
else:
    # new session!
    session = hash_string((time.time()))  # random enough for this purpose
    APPNAME = f"{PREFIX}{session}"
    tmp_file.write_text(APPNAME)


def retrieve_credentials(filename: str) -> Optional[str]:
    return keyring.get_password(APPNAME, hash_string(filename))


def save_credentials(filename: str) -> str:
    passphrase = getpass("Passphrase? ")
    keyring.set_password(APPNAME, hash_string(filename), passphrase)

    return passphrase


def cleanup_keyring() -> None:
    import keyring.backends.SecretService

    kr: keyring.backends.SecretService.Keyring | KeyringBackend = keyring.get_keyring()
    if not hasattr(kr, "get_preferred_collection"):
        print(f"Can't clean up this keyring backend! {type(kr)}", file=sys.stderr)  # todo: only if verbose
        return

    c = kr.get_preferred_collection()

    # get old 2fas: keyring items:
    relevant = [
        _
        for _ in c.get_all_items()
        if (
            service := _.get_attributes().get("service", "")
        )  # must have a 'service' attribute, otherwise it's unrelated
        and service.startswith(PREFIX)  # must be a 2fas: service, otherwise it's unrelated
        and service != APPNAME  # must not be the currently active session
    ]

    print(
        "removed",
        len([_.delete() for _ in relevant]),
        "old items",
        # todo: only if verbose I guess
        file=sys.stderr,
    )
