"""
This file decides how your vault gets unlocked, and how often you are asked.

Two independent questions:

1. *how* - `unlock-method`, either `password` or `security-key`. The key replaces the
   passphrase, it is not a second factor: the .2fas file itself never stops being
   passphrase-encrypted, so the passphrase always remains a valid way in and lock-out is
   impossible. The flip side, worth saying out loud: your effective strength is the weaker
   of the two paths, which is your passphrase.
2. *how often* - `password-unlock-policy` and `security-key-unlock-policy`, one of:

   | policy       | password path                          | security key path   |
   |--------------|----------------------------------------|---------------------|
   | `os-session` | asked once per boot (key in keyring)   | one touch per boot  |
   | `process`    | asked once per run of `2fas`           | one touch per run   |
   | `code`       | asked for every code you generate      | one touch per code  |

   These are configured separately because the passphrase stays a live fallback, so both
   paths are in daily use, and because they do not cost the same: a tighter policy costs
   the key user a one-second touch and the passphrase user a full master passphrase.

What is cached is the derived 32-byte AES key, never the passphrase. A stolen cache
therefore does not reveal a passphrase you may have reused elsewhere.

Note what the `code` policy does and does not buy. The vault is decrypted once and stays
in RAM for the lifetime of the process; the check happens just before a code is shown.
So it buys presence attestation - somebody at your unattended terminal with the menu open
can not pull a code - and not protection of the key material.
"""

import base64
import contextlib
import enum
import getpass
import sys
import typing as t
from pathlib import Path

import keyring
import lib2fas
import pyjson5
import rich
from keyring.errors import KeyringError
from rich.markup import escape

from . import security_key
from .cli_settings import CliSettings
from .keystore import KeyStore, WrappedKey, new_wrapped_key, vault_id_for
from .security_key import SecurityKeyError


class UnlockMethod(enum.StrEnum):
    """
    How your vault gets unlocked.

    StrEnum and not a plain str: the value is what ends up in the TOML file and in the
    keyring, so it has to stay a string, but everything in the code should be spelling it
    once rather than repeating a literal.
    """

    PASSWORD = "password"
    SECURITY_KEY = "security-key"


class UnlockPolicy(enum.StrEnum):
    """
    How often you are asked.
    """

    OS_SESSION = "os-session"
    PROCESS = "process"
    CODE = "code"


DEFAULT_METHOD = UnlockMethod.PASSWORD
DEFAULT_PASSWORD_POLICY = UnlockPolicy.OS_SESSION
DEFAULT_SECURITY_KEY_POLICY = UnlockPolicy.PROCESS

POLICY_HELP: dict[UnlockPolicy, str] = {
    UnlockPolicy.OS_SESSION: "once per boot",
    UnlockPolicy.PROCESS: "once per run of 2fas",
    UnlockPolicy.CODE: "every single code",
}

# keyring username namespace for cached keys; kept separate from lib2fas' own
# passphrase items, which live under the same (per-OS-session) service name.
KEY_ITEM_PREFIX = "key:"


def parse_method(value: t.Any, fallback: UnlockMethod = DEFAULT_METHOD) -> UnlockMethod:
    """
    Validate an `unlock-method` setting, complaining once instead of crashing.
    """
    text = str(value or "").strip().lower().replace("_", "-")
    try:
        return UnlockMethod(text)
    except ValueError:
        if text:
            print(f"Unknown unlock-method '{text}', falling back to '{fallback}'.", file=sys.stderr)
        return fallback


def parse_policy(value: t.Any, fallback: UnlockPolicy) -> UnlockPolicy:
    """
    Validate an unlock policy setting, complaining once instead of crashing.
    """
    text = str(value or "").strip().lower().replace("_", "-")
    try:
        return UnlockPolicy(text)
    except ValueError:
        if text:
            print(f"Unknown unlock policy '{text}', falling back to '{fallback}'.", file=sys.stderr)
        return fallback


def vault_salt(filename: str | Path) -> bytes | None:
    """
    Read a vault's PBKDF2 salt without decrypting anything.

    Returns:
        the salt, or None if the file is missing, unreadable, or not encrypted at all.
    """
    path = Path(filename).expanduser()
    if not path.is_file():
        return None

    try:
        with path.open() as f:
            data = pyjson5.loads(f.read())
        encrypted = data.get("servicesEncrypted")
        return lib2fas.extract_salt(encrypted) if encrypted else None
    except (OSError, ValueError, TypeError, AttributeError, pyjson5.Json5Exception):
        return None


def prune_keystore(store: KeyStore, known_files: t.Iterable[str]) -> list[WrappedKey]:
    """
    Drop wrapped keys that can no longer belong to any vault this installation knows.

    Deliberately cheap: entries whose enrolled file still exists are kept without reading
    anything, so the (rare) case of a moved vault is the only one that costs file reads.
    """
    if not any(not (w.filename_hint and Path(w.filename_hint).exists()) for w in store.all()):
        return []

    live = {vault_id_for(salt) for file in known_files if (salt := vault_salt(file))}
    return store.prune(live)


class CachedKey(t.NamedTuple):
    """
    A derived vault key plus a note of which path produced it.
    """

    key: bytes
    via: UnlockMethod

    def encode(self) -> str:
        """
        Flatten into something a keyring can hold.
        """
        return f"{self.via}:{base64.b64encode(self.key).decode()}"

    @classmethod
    def decode(cls, raw: str) -> t.Self | None:
        """
        Parse `encode()` output, returning None if it is not intelligible.
        """
        via, _, encoded = raw.partition(":")
        if not encoded:
            return None

        try:
            return cls(base64.b64decode(encoded), UnlockMethod(via))
        except (ValueError, TypeError):
            return None


class ProcessKeyCache:
    """
    Holds derived keys for the lifetime of this process only. Nothing is written anywhere.
    """

    def __init__(self) -> None:
        """
        Start out empty.
        """
        self._keys: dict[str, CachedKey] = {}

    def get(self, vault_id: str) -> CachedKey | None:
        """
        Look up a cached key.
        """
        return self._keys.get(vault_id)

    def put(self, vault_id: str, cached: CachedKey) -> None:
        """
        Remember a key until this process exits.
        """
        self._keys[vault_id] = cached

    def drop(self, vault_id: str) -> None:
        """
        Forget one key.
        """
        self._keys.pop(vault_id, None)


class SessionCacheProtocol(t.Protocol):
    """
    Where a derived key lives between runs of 2fas, if anywhere.
    """

    def get(self, vault_id: str) -> "CachedKey | None":
        """
        Look up a key an earlier run left behind.
        """

    def put(self, vault_id: str, cached: "CachedKey") -> None:
        """
        Leave a key for the next run.
        """

    def drop(self, vault_id: str) -> None:
        """
        Forget one key.
        """


class NoSessionCache(SessionCacheProtocol):
    """
    Stand-in for when there is no login keyring to scope anything to.

    `os-session` then degrades to `process`: there is nowhere to remember a key across
    runs, so we simply do not. Having this as a class rather than a special case keeps the
    'is there a keyring' question in one place - and gives tests something to inject.
    """

    def get(self, vault_id: str) -> "CachedKey | None":  # noqa: ARG002 - part of the protocol
        """
        Nothing is ever stored, so nothing is ever found.
        """
        return None

    def put(self, vault_id: str, cached: "CachedKey") -> None:
        """
        Deliberately does nothing.
        """

    def drop(self, vault_id: str) -> None:
        """
        Deliberately does nothing.
        """


class SessionKeyCache(SessionCacheProtocol):
    """
    Holds derived keys in the login keyring, scoped to the current OS session.

    Scoping works exactly as lib2fas' passphrase storage does: the keyring service name
    is regenerated per OS session, so after a reboot the old items are unreachable and get
    garbage-collected. That is a forget-on-reboot mechanism and not an access-control one -
    while your login keyring is unlocked, any process running as you can read these items.
    """

    def service(self) -> str | None:
        """
        The current OS session's keyring service name, or None if there is no keyring.
        """
        return getattr(lib2fas.keyring_manager, "appname", "") or None

    def get(self, vault_id: str) -> CachedKey | None:
        """
        Look up a cached key for this OS session.
        """
        if not (service := self.service()):
            return None

        try:
            raw = keyring.get_password(service, KEY_ITEM_PREFIX + vault_id)
        except KeyringError as e:  # pragma: no cover
            print(f"Keyring failing: {e}", file=sys.stderr)
            return None

        return CachedKey.decode(raw) if raw else None

    def put(self, vault_id: str, cached: CachedKey) -> None:
        """
        Remember a key until the next boot.
        """
        if not (service := self.service()):
            return

        try:
            keyring.set_password(service, KEY_ITEM_PREFIX + vault_id, cached.encode())
        except KeyringError as e:  # pragma: no cover
            print(f"Keyring failing: {e}", file=sys.stderr)

    def drop(self, vault_id: str) -> None:
        """
        Forget one key.
        """
        if not (service := self.service()):
            return

        # nothing to delete is not a problem:
        with contextlib.suppress(KeyringError):
            keyring.delete_password(service, KEY_ITEM_PREFIX + vault_id)


def default_session_cache() -> SessionCacheProtocol:
    """
    A keyring-backed cache, or a do-nothing one when there is no keyring.

    A DummyKeyringManager (which is what lib2fas falls back to when no backend is
    available) has no session name to scope items to, so there is nothing to write to and
    `os-session` degrades to `process`.
    """
    return SessionKeyCache() if getattr(lib2fas.keyring_manager, "appname", "") else NoSessionCache()


class PolicyUnlocker(lib2fas.UnlockerProtocol):
    """
    The unlocker `load_services` calls, wired to the user's method and policy settings.

    Tries the security key first when that is what the user configured, and falls back to
    the passphrase whenever the key is unavailable - not plugged in, not touched in time,
    or not the one this vault was enrolled with. Falling back re-enrols nothing: the key
    is by definition absent or unresponsive at that moment.
    """

    method: UnlockMethod
    password_policy: UnlockPolicy
    security_key_policy: UnlockPolicy
    force_password: bool

    # which path actually produced the key we are using. The policy follows the path
    # taken, not the method configured: a passphrase typed because the key was missing
    # must not then be re-prompted for every code.
    used_path: UnlockMethod | None = None
    current_key: bytes | None = None

    def __init__(
        self,
        method: UnlockMethod = DEFAULT_METHOD,
        password_policy: UnlockPolicy = DEFAULT_PASSWORD_POLICY,
        security_key_policy: UnlockPolicy = DEFAULT_SECURITY_KEY_POLICY,
        force_password: bool = False,
        store: KeyStore = None,
        touch_timeout: float = None,
        session_cache: SessionCacheProtocol = None,
        keyring_manager: lib2fas.KeyringManagerProtocol = None,
        prompt: t.Callable[[str], str] = None,
        backend: t.Any = None,
    ) -> None:
        """
        Args:
            method: which path to try first.
            password_policy: how often to ask for the passphrase.
            security_key_policy: how often to ask for a touch.
            force_password: skip the security key entirely (the `--password` escape hatch).
            store: where wrapped keys live.
            touch_timeout: seconds to wait for a touch.
            session_cache: where keys are kept across runs of 2fas.
            keyring_manager: where lib2fas keeps passphrases from earlier versions.
            prompt: how to ask for the passphrase.
            backend: what talks to the security key; a stand-in makes this testable
                without hardware.
        """
        self.method = method
        self.password_policy = password_policy
        self.security_key_policy = security_key_policy
        self.force_password = force_password
        self.store = store or KeyStore()
        self.touch_timeout = touch_timeout
        self.keyring_manager = keyring_manager or lib2fas.keyring_manager
        self.prompt = prompt or getpass.getpass
        self.backend = backend or security_key

        self.process_cache = ProcessKeyCache()
        self.session_cache = session_cache or default_session_cache()
        self._vault: tuple[str, bytes, str] | None = None  # (filename, salt, vault_id)

    @classmethod
    def from_settings(cls, settings: CliSettings, force_password: bool = False) -> t.Self:
        """
        Build an unlocker from the user's config file.
        """
        return cls(
            method=parse_method(settings.unlock_method),
            password_policy=parse_policy(settings.password_unlock_policy, DEFAULT_PASSWORD_POLICY),
            security_key_policy=parse_policy(settings.security_key_unlock_policy, DEFAULT_SECURITY_KEY_POLICY),
            force_password=force_password,
        )

    # --- policy ---

    def vault(self) -> tuple[str, bytes, str] | None:
        """
        The (filename, salt, vault_id) of the vault we last unlocked, if any.
        """
        return self._vault

    def effective_policy(self) -> UnlockPolicy:
        """
        The policy governing the path we are actually on.
        """
        path = self.used_path or (UnlockMethod.PASSWORD if self.force_password else self.method)
        return self.policy_for(path)

    def policy_for(self, path: UnlockMethod) -> UnlockPolicy:
        """
        The policy governing one specific path, regardless of which one we are on.
        """
        return self.security_key_policy if path == UnlockMethod.SECURITY_KEY else self.password_policy

    def _may_persist(self) -> bool:
        return self.effective_policy() == UnlockPolicy.OS_SESSION

    def intended_path(self, vault_id: str) -> UnlockMethod:
        """
        The path this unlock is supposed to take, before anything has been tried.

        Falls back to the passphrase when the security key is configured but this
        particular vault has no key set up, since that is what would happen anyway.
        """
        if self.force_password or self.method != UnlockMethod.SECURITY_KEY:
            return UnlockMethod.PASSWORD

        return UnlockMethod.SECURITY_KEY if self.store.get(vault_id) else UnlockMethod.PASSWORD

    def _cached(self, vault_id: str) -> CachedKey | None:
        """
        Find a usable cached key, or None if the policy says we must ask again.

        Two conditions, and both were missing before:

        - the cache entry has to come from the path we are configured to use. A key cached
          while unlocking with a passphrase must not silently satisfy a run configured to
          use the security key - that would make the setting look like it did nothing.
        - the keyring (cross-process) cache may only be read when *that* path's policy is
          `os-session`. Under `process` the promise is "ask once per run", and reading a
          key another run left behind breaks it just as thoroughly as writing one would.
        """
        intended = self.intended_path(vault_id)

        if (cached := self.process_cache.get(vault_id)) and cached.via == intended:
            return cached

        if self.policy_for(intended) != UnlockPolicy.OS_SESSION:
            return None

        if (cached := self.session_cache.get(vault_id)) and cached.via == intended:
            return cached

        return None

    # --- UnlockerProtocol ---

    def unlock(self, filename: str, salt: bytes) -> bytes | None:
        """
        Produce the derived key for a vault, asking as little as the policy allows.
        """
        vault_id = vault_id_for(salt)
        self._vault = (filename, salt, vault_id)

        if cached := self._cached(vault_id):
            self.used_path = cached.via
            self.current_key = cached.key
            # a key found in the session keyring is worth keeping for this process too:
            self.process_cache.put(vault_id, cached)
            return cached.key

        if cached := self._unlock_with_security_key(vault_id):
            return self._accept(vault_id, cached)

        return self._accept(vault_id, self._unlock_with_password(filename, salt))

    def invalidate(self, filename: str, salt: bytes) -> None:
        """
        Forget the key we handed out, because it did not decrypt the vault.

        For the passphrase path that means the stored passphrase was wrong. For the
        security-key path it means the wrapped key no longer matches the vault, which the
        salt-keyed store makes unlikely - but if it happens, dropping it sends the user
        back to the passphrase instead of into an unwinnable retry loop.
        """
        vault_id = vault_id_for(salt)
        self.process_cache.drop(vault_id)
        self.session_cache.drop(vault_id)
        self.keyring_manager.delete_credentials(filename)

        if self.used_path == UnlockMethod.SECURITY_KEY:
            print("The key stored for your security key did not fit this vault; removing it.", file=sys.stderr)
            self.store.delete(vault_id)
            self.force_password = True

        self.used_path = None
        self.current_key = None

    def cleanup(self) -> int:
        """
        Drop keyring items (passphrases and cached keys) from previous OS sessions.
        """
        return self.keyring_manager.cleanup_keyring()

    # --- the two paths ---

    def _accept(self, vault_id: str, cached: CachedKey | None) -> bytes | None:
        if cached is None:  # pragma: no cover - getpass does not return None
            return None

        self.used_path = cached.via
        self.current_key = cached.key

        self.process_cache.put(vault_id, cached)
        if self._may_persist():
            self.session_cache.put(vault_id, cached)

        return cached.key

    def _unlock_with_security_key(self, vault_id: str) -> CachedKey | None:
        """
        Unwrap this vault's key with the enrolled security key, or None to fall back.
        """
        if self.force_password or self.method != UnlockMethod.SECURITY_KEY:
            return None

        if not (wrapped := self.store.get(vault_id)):
            rich.print("[yellow]No security key is set up for this vault " "(run `2fas --setup-key`).[/yellow]")
            return None

        try:
            secret = self.backend.evaluate_hmac_secret(
                wrapped.credential_id,
                wrapped.hmac_salt,
                timeout=self.touch_timeout or self.backend.DEFAULT_TIMEOUT,
                announce=announce_touch,
            )
            return CachedKey(
                self.backend.unwrap_key(secret, vault_id, wrapped.nonce, wrapped.ciphertext),
                UnlockMethod.SECURITY_KEY,
            )
        except SecurityKeyError as e:
            rich.print(
                f"[yellow]Security key unavailable ({escape(str(e))}) - " "falling back to your passphrase.[/yellow]"
            )
            return None

    def _unlock_with_password(self, filename: str, salt: bytes) -> CachedKey | None:
        """
        Ask for the passphrase (or read it from the keyring) and derive the key.
        """
        # the keyring passphrase item is only consulted under 'os-session'; the tighter
        # policies mean "ask me", and reading a stored passphrase would not be asking.
        passphrase = None
        if self.password_policy == UnlockPolicy.OS_SESSION:
            passphrase = self.keyring_manager.retrieve_credentials(filename)

        if not passphrase:
            passphrase = self.prompt(f"Passphrase for '{filename}'? ")

        return CachedKey(lib2fas.derive_key(passphrase, salt), UnlockMethod.PASSWORD)

    # --- per-code confirmation ---

    def needs_confirmation(self) -> bool:
        """
        Whether the `code` policy applies to the path we are on.
        """
        return self.effective_policy() == UnlockPolicy.CODE

    def confirm(self) -> bool:
        """
        Re-attest presence before a code is shown, under the `code` policy.

        This verifies against the key we already hold, so a wrong passphrase or the wrong
        security key is actually rejected rather than merely noted.

        Returns:
            True if the check passed (or was not required).
        """
        if not self.needs_confirmation():
            return True

        if self._vault is None or self.current_key is None:  # pragma: no cover
            return True

        filename, salt, vault_id = self._vault

        try:
            if self.used_path == UnlockMethod.SECURITY_KEY:
                fresh = self._confirm_with_security_key(vault_id)
            else:
                fresh = lib2fas.derive_key(self.prompt(f"Passphrase for '{filename}'? "), salt)
        except SecurityKeyError as e:
            rich.print(f"[red]Could not confirm with your security key: {escape(str(e))}[/red]")
            return False

        if fresh == self.current_key:
            return True

        rich.print("[red]That did not match; not showing the code.[/red]")
        return False

    def _confirm_with_security_key(self, vault_id: str) -> bytes:
        wrapped = self.store.get(vault_id)
        if wrapped is None:  # pragma: no cover
            raise SecurityKeyError("The enrolment for this vault disappeared.")

        secret = self.backend.evaluate_hmac_secret(
            wrapped.credential_id,
            wrapped.hmac_salt,
            timeout=self.touch_timeout or self.backend.DEFAULT_TIMEOUT,
            announce=announce_touch,
        )
        return t.cast(bytes, self.backend.unwrap_key(secret, vault_id, wrapped.nonce, wrapped.ciphertext))


def announce_touch() -> None:
    """
    Tell the user their security key is waiting.
    """
    rich.print("[blue]Touch your security key...[/blue]")


def enroll(
    filename: str,
    salt: bytes,
    vault_key: bytes,
    pin: str = None,
    store: KeyStore = None,
    timeout: float = None,
) -> str:
    """
    Wrap this vault's key under a fresh credential on the connected security key.

    Two touches are needed here (one to create the credential, one to read its secret);
    every later unlock needs exactly one. Nothing is stored on the key itself - the
    credential id we keep *is* the credential, encrypted under the key's master secret.

    Args:
        filename: only kept as a human-readable hint in the stored blob.
        salt: the vault's PBKDF2 salt, which identifies it.
        vault_key: the derived key to wrap; get this by unlocking with the passphrase first.
        pin: the authenticator's PIN, if it has one (CTAP2 requires it to create a credential).
        store: where to write; overridable for tests.
        timeout: seconds to wait for each touch.

    Returns:
        the vault id the enrolment was filed under.

    Raises:
        SecurityKeyError: and subclasses.
    """
    store = store or KeyStore()
    timeout = timeout or security_key.DEFAULT_TIMEOUT
    vault_id = vault_id_for(salt)

    credential_id = security_key.create_credential(pin=pin, timeout=timeout, announce=announce_touch)
    hmac_salt = security_key.new_hmac_salt()
    secret = security_key.evaluate_hmac_secret(credential_id, hmac_salt, timeout=timeout, announce=announce_touch)
    nonce, ciphertext = security_key.wrap_key(secret, vault_id, vault_key)

    store.put(
        new_wrapped_key(
            vault_id=vault_id,
            credential_id=credential_id,
            hmac_salt=hmac_salt,
            nonce=nonce,
            ciphertext=ciphertext,
            rp_id=security_key.RP_ID,
            filename_hint=filename,
        )
    )

    return vault_id
