"""
This file talks to a FIDO2 authenticator (e.g. a YubiKey) to wrap and unwrap vault keys.

Why hmac-secret and not one of the other things a YubiKey can do:

- it programs *nothing* on the key. No OTP slot is overwritten, no PIV slot is occupied,
  no resident-credential storage is consumed. Unplug the key and there is no trace of
  2fas on it.
- it needs no PIN to *use* (a touch is enough), which is the whole point of the feature.
- the only state is the credential id, which is the credential itself, wrapped under the
  authenticator's master secret. We keep that in ~/.config/2fas/keys.

The token never sees your vault. It answers one question - "what is
HMAC-SHA256(CredRandom, salt) for this credential?" - and the answer is used to derive a
key that encrypts the vault key we already had. So this layer protects a *cache*; the
.2fas file itself stays passphrase-encrypted, which is exactly why lock-out is
impossible and why your passphrase remains the security ceiling.

This module deliberately uses the low-level Ctap2 API rather than fido2's WebAuthn
client: a CLI is not a website and should not have to invent an origin to satisfy an
RP-id check.
"""

import contextlib
import os
import threading
import typing

RP_ID = "2fas.local"
RP_NAME = "2fas"
USER_ID = b"2fas-cli"
HKDF_INFO_PREFIX = b"2fas-yubikey-wrap-v1:"
HMAC_SALT_LENGTH = 32  # required by the hmac-secret extension
NONCE_LENGTH = 12  # AES-GCM
DEFAULT_TIMEOUT = 30.0

# The unlock path always asserts with user presence only and never with user
# verification. That is not just a convenience choice: hmac-secret returns a *different*
# secret when uv is used (CredRandomWithUV vs CredRandomWithoutUV), so mixing the two
# would silently make previously wrapped keys unopenable.
ASSERT_OPTIONS: dict[str, bool] = {"up": True, "uv": False}


class YubiKeyError(RuntimeError):
    """
    Anything that went wrong while talking to an authenticator.

    Every one of these is recoverable: the passphrase always remains a valid way in.
    """


class Fido2NotInstalled(YubiKeyError):
    """The optional `fido2` dependency is missing (`pip install 2fas[yubikey]`)."""


class NoAuthenticator(YubiKeyError):
    """No FIDO2 authenticator is plugged in, or we are not allowed to talk to it."""


class HmacSecretUnsupported(YubiKeyError):
    """An authenticator was found, but it does not implement the hmac-secret extension."""


class TouchTimeout(YubiKeyError):
    """The user did not touch the key in time."""


class PinRequired(YubiKeyError):
    """Enrolment needs the authenticator's PIN, because one is configured."""


class WrongCredential(YubiKeyError):
    """This authenticator does not know the credential this vault was enrolled with."""


def fido2_available() -> bool:
    """
    Whether the optional `fido2` dependency is importable.
    """
    try:
        import fido2  # noqa: F401
    except ImportError:
        return False

    return True


def _require_fido2() -> None:
    if not fido2_available():
        raise Fido2NotInstalled("The 'fido2' package is required for YubiKey support: pip install '2fas[yubikey]'")


class Authenticator(typing.NamedTuple):
    """
    A description of a connected authenticator, for `--doctor`.
    """

    product: str
    firmware: str
    extensions: list[str]
    supports_hmac_secret: bool
    has_pin: bool
    always_uv: bool


@contextlib.contextmanager
def _open_devices() -> typing.Iterator[list[typing.Any]]:
    """
    Open every connected FIDO2 HID device and close them all again afterwards.
    """
    _require_fido2()
    from fido2.hid import CtapHidDevice

    try:
        devices = list(CtapHidDevice.list_devices())
    except OSError as e:  # pragma: no cover - depends on udev/hidraw permissions
        raise NoAuthenticator(f"Could not enumerate FIDO2 devices: {e}") from e

    try:
        yield devices
    finally:
        for device in devices:
            with contextlib.suppress(Exception):
                device.close()


def describe_authenticators() -> list[Authenticator]:
    """
    Report on every connected authenticator, without asking the user for anything.
    """
    from fido2.ctap2.base import Ctap2

    found = []
    with _open_devices() as devices:
        for device in devices:
            try:
                ctap = Ctap2(device)
            except Exception:  # a non-CTAP2 (U2F-only) device is not an error
                continue

            info = ctap.info
            version = info.firmware_version or 0
            found.append(
                Authenticator(
                    product=str(getattr(device, "product_name", None) or "unknown"),
                    # firmware_version is packed as major.minor.patch bytes:
                    firmware=f"{(version >> 16) & 0xFF}.{(version >> 8) & 0xFF}.{version & 0xFF}",
                    extensions=list(info.extensions or []),
                    supports_hmac_secret="hmac-secret" in (info.extensions or []),
                    has_pin=bool((info.options or {}).get("clientPin")),
                    always_uv=bool((info.options or {}).get("alwaysUv")),
                )
            )

    return found


@contextlib.contextmanager
def _hmac_secret_authenticator() -> typing.Iterator[typing.Any]:
    """
    Yield a Ctap2 handle for the first connected authenticator that speaks hmac-secret.

    Raises:
        NoAuthenticator: nothing usable is plugged in.
        HmacSecretUnsupported: something is plugged in, but it can not do this.
    """
    from fido2.ctap2.base import Ctap2

    with _open_devices() as devices:
        if not devices:
            raise NoAuthenticator("No FIDO2 authenticator found. Is your key plugged in?")

        saw_ctap2 = False
        for device in devices:
            try:
                ctap = Ctap2(device)
            except Exception:
                continue

            saw_ctap2 = True
            if "hmac-secret" in (ctap.info.extensions or []):
                yield ctap
                return

        if saw_ctap2:
            raise HmacSecretUnsupported("Your authenticator does not support the hmac-secret extension.")

        raise NoAuthenticator("A device was found, but it does not speak CTAP2.")


def _shared_secret(ctap: typing.Any) -> tuple[typing.Any, typing.Any, bytes]:
    """
    Do the CTAP2 key agreement needed to send an encrypted hmac-secret salt.

    This is the three public calls that `ClientPin._get_shared_secret` wraps; done here
    so we do not depend on a private helper whose name has already changed once.
    """
    from fido2.ctap2.pin import ClientPin, PinProtocolV1, PinProtocolV2

    protocols = list(ctap.info.pin_uv_protocols or [])
    protocol = PinProtocolV2() if 2 in protocols or not protocols else PinProtocolV1()

    response = ctap.client_pin(protocol.VERSION, ClientPin.CMD.GET_KEY_AGREEMENT)
    encapsulate = typing.cast(
        typing.Callable[[typing.Any], tuple[typing.Any, bytes]],
        protocol.encapsulate,
    )
    key_agreement, shared = encapsulate(response[ClientPin.RESULT.KEY_AGREEMENT])
    return protocol, key_agreement, shared


@contextlib.contextmanager
def _touch_deadline(timeout: float) -> typing.Iterator[threading.Event]:
    """
    Cancel the pending CTAP request if the user does not touch the key in time.
    """
    event = threading.Event()
    timer = threading.Timer(timeout, event.set)
    timer.daemon = True
    timer.start()
    try:
        yield event
    finally:
        timer.cancel()


def _translate_ctap_error(error: Exception, event: threading.Event) -> YubiKeyError:
    """
    Turn a raw CtapError into something with an actionable message.
    """
    from fido2.ctap import CtapError

    if not isinstance(error, CtapError):  # pragma: no cover
        return YubiKeyError(str(error))

    code = error.code
    if event.is_set() or code in (CtapError.ERR.KEEPALIVE_CANCEL, CtapError.ERR.USER_ACTION_TIMEOUT):
        return TouchTimeout("Timed out waiting for a touch on your security key.")
    if code in (CtapError.ERR.PUAT_REQUIRED, CtapError.ERR.PIN_INVALID, CtapError.ERR.PIN_AUTH_INVALID):
        return PinRequired(f"Your authenticator wants its PIN: {error}")
    if code in (CtapError.ERR.NO_CREDENTIALS, CtapError.ERR.INVALID_CREDENTIAL):
        return WrongCredential("This security key was not the one this vault was enrolled with.")

    return YubiKeyError(str(error))


def _keepalive_printer(announce: typing.Callable[[], None]) -> typing.Callable[[int], None]:
    """
    Build an on_keepalive callback that tells the user to touch their key, once.

    CTAP sends status 2 ('up needed') repeatedly while it waits; we only want one prompt.
    """
    announced = False

    def on_keepalive(status: int) -> None:
        nonlocal announced
        if status == 2 and not announced:
            announced = True
            announce()

    return on_keepalive


def create_credential(
    pin: str = None,
    timeout: float = DEFAULT_TIMEOUT,
    announce: typing.Callable[[], None] = lambda: None,
) -> bytes:
    """
    Register a new non-discoverable hmac-secret credential and return its credential id.

    Note that CTAP2 requires the PIN for makeCredential whenever the authenticator has
    one configured, even though the later unlocks will not. That is why enrolment may ask
    for a PIN and daily use never does.

    Args:
        pin: the authenticator's PIN, if it has one.
        timeout: seconds to wait for a touch.
        announce: called once when the key is waiting to be touched.

    Raises:
        YubiKeyError: and subclasses; the caller should fall back to the passphrase.
    """
    with _hmac_secret_authenticator() as ctap:
        pin_uv_param = None
        pin_uv_protocol = None
        client_data_hash = os.urandom(32)

        if (ctap.info.options or {}).get("clientPin"):
            if not pin:
                raise PinRequired("This authenticator has a PIN, which is required to enroll a new credential.")

            from fido2.ctap2.pin import ClientPin

            client_pin = ClientPin(ctap)
            token = client_pin.get_pin_token(pin, ClientPin.PERMISSION.MAKE_CREDENTIAL, RP_ID)
            pin_uv_param = client_pin.protocol.authenticate(token, client_data_hash)
            pin_uv_protocol = client_pin.protocol.VERSION

        with _touch_deadline(timeout) as event:
            try:
                response = ctap.make_credential(
                    client_data_hash=client_data_hash,
                    rp={"id": RP_ID, "name": RP_NAME},
                    user={"id": USER_ID, "name": RP_NAME},
                    key_params=[{"type": "public-key", "alg": -7}],
                    extensions={"hmac-secret": True},
                    # rk=False: a non-discoverable credential, so nothing is stored on the key.
                    options={"rk": False},
                    pin_uv_param=pin_uv_param,
                    pin_uv_protocol=pin_uv_protocol,
                    event=event,
                    on_keepalive=_keepalive_printer(announce),
                )
            except Exception as e:  # normalized below
                raise _translate_ctap_error(e, event) from e

        credential = response.auth_data.credential_data
        if credential is None:  # pragma: no cover
            raise YubiKeyError("The authenticator did not return a credential.")

        if not (response.auth_data.extensions or {}).get("hmac-secret"):
            raise HmacSecretUnsupported("The authenticator refused to enable hmac-secret for this credential.")

        return bytes(credential.credential_id)


def evaluate_hmac_secret(
    credential_id: bytes,
    hmac_salt: bytes,
    timeout: float = DEFAULT_TIMEOUT,
    announce: typing.Callable[[], None] = lambda: None,
) -> bytes:
    """
    Ask the authenticator for HMAC-SHA256(CredRandom, hmac_salt); requires a touch.

    Args:
        credential_id: as returned by `create_credential`.
        hmac_salt: 32 bytes, stored alongside the wrapped key.
        timeout: seconds to wait for a touch.
        announce: called once when the key is waiting to be touched.

    Raises:
        YubiKeyError: and subclasses; the caller should fall back to the passphrase.
    """
    if len(hmac_salt) != HMAC_SALT_LENGTH:  # pragma: no cover
        raise ValueError(f"hmac_salt must be {HMAC_SALT_LENGTH} bytes.")

    with _hmac_secret_authenticator() as ctap:
        protocol, key_agreement, shared = _shared_secret(ctap)
        salt_enc = protocol.encrypt(shared, hmac_salt)
        salt_auth = protocol.authenticate(shared, salt_enc)

        with _touch_deadline(timeout) as event:
            try:
                assertion = ctap.get_assertion(
                    rp_id=RP_ID,
                    client_data_hash=os.urandom(32),
                    allow_list=[{"type": "public-key", "id": credential_id}],
                    extensions={
                        "hmac-secret": {
                            1: key_agreement,
                            2: salt_enc,
                            3: salt_auth,
                            4: protocol.VERSION,
                        }
                    },
                    options=ASSERT_OPTIONS,
                    event=event,
                    on_keepalive=_keepalive_printer(announce),
                )
            except Exception as e:  # normalized below
                raise _translate_ctap_error(e, event) from e

        output = (assertion.auth_data.extensions or {}).get("hmac-secret")
        if not output:
            raise HmacSecretUnsupported("The authenticator did not return an hmac-secret output.")

        secret = protocol.decrypt(shared, output)
        if secret is None or len(secret) < HMAC_SALT_LENGTH:  # pragma: no cover
            raise YubiKeyError("The authenticator returned an unusable hmac-secret output.")

        # we only ever send one salt, so only the first 32 bytes are ours:
        return bytes(secret[:HMAC_SALT_LENGTH])


def _wrapping_key(secret: bytes, vault_id: str) -> bytes:
    """
    Stretch the token's answer into an AES key, bound to this specific vault.
    """
    from cryptography.hazmat.primitives.hashes import SHA256
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    hkdf = HKDF(algorithm=SHA256(), length=32, salt=None, info=HKDF_INFO_PREFIX + vault_id.encode())
    return hkdf.derive(secret)


def wrap_key(secret: bytes, vault_id: str, vault_key: bytes) -> tuple[bytes, bytes]:
    """
    Encrypt a vault key under the token's answer.

    Returns:
        (nonce, ciphertext)
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(NONCE_LENGTH)
    ciphertext = AESGCM(_wrapping_key(secret, vault_id)).encrypt(nonce, vault_key, vault_id.encode())
    return nonce, ciphertext


def unwrap_key(secret: bytes, vault_id: str, nonce: bytes, ciphertext: bytes) -> bytes:
    """
    Decrypt a vault key that `wrap_key` produced.

    Raises:
        YubiKeyError: if the token's answer does not fit this blob, e.g. because it is a
            different security key, or because the blob was written with user
            verification and this assertion was not (or vice versa).
    """
    import cryptography.exceptions
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    try:
        return AESGCM(_wrapping_key(secret, vault_id)).decrypt(nonce, ciphertext, vault_id.encode())
    except cryptography.exceptions.InvalidTag as e:
        raise WrongCredential("The stored key does not belong to this security key.") from e


def new_hmac_salt() -> bytes:
    """
    A fresh per-vault salt for the hmac-secret call.
    """
    return os.urandom(HMAC_SALT_LENGTH)
