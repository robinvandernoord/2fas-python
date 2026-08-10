import typing

import lib2fas
import pytest

from src.twofas import unlock as unlock_module
from src.twofas.keystore import KeyStore, new_wrapped_key, vault_id_for
from src.twofas.unlock import (
    CachedKey,
    PolicyUnlocker,
    ProcessKeyCache,
    parse_method,
    parse_policy,
    prune_keystore,
    vault_salt,
)

from ._shared import CWD

FILENAME = str(CWD / "2fas-demo-pass.2fas")
PLAIN_FILENAME = str(CWD / "2fas-demo-nopass.2fas")
PASSWORD = "test"


@pytest.fixture
def store(tmp_path) -> KeyStore:
    return KeyStore(tmp_path / "keys")


@pytest.fixture
def salt() -> bytes:
    result = vault_salt(FILENAME)
    assert result is not None
    return result


@pytest.fixture
def key(salt) -> bytes:
    return lib2fas.derive_key(PASSWORD, salt)


@pytest.fixture
def no_session_cache(monkeypatch):
    """The container running these tests has no login keyring; make that explicit."""
    monkeypatch.setattr(unlock_module.SessionKeyCache, "service", lambda self: None)


def typed(value: str) -> typing.Callable[[str], str]:
    return lambda _: value


# --- settings parsing ---


def test_parse_method():
    assert parse_method("yubikey") == "yubikey"
    assert parse_method("PASSWORD") == "password"
    assert parse_method(None) == "password"
    assert parse_method("nonsense") == "password"


def test_parse_policy():
    assert parse_policy("code", "process") == "code"
    assert parse_policy("os_session", "process") == "os-session"  # underscores are forgiven
    assert parse_policy("", "process") == "process"
    assert parse_policy("nonsense", "os-session") == "os-session"


# --- vault identity ---


def test_vault_salt():
    assert vault_salt(FILENAME)
    assert vault_salt(PLAIN_FILENAME) is None  # not encrypted -> nothing to identify
    assert vault_salt("/does/not/exist.2fas") is None


def test_vault_id_is_path_independent(tmp_path, salt):
    copy = tmp_path / "renamed.2fas"
    copy.write_bytes(open(FILENAME, "rb").read())

    assert vault_salt(copy) == salt
    assert vault_id_for(vault_salt(copy)) == vault_id_for(salt)


# --- cache plumbing ---


def test_cached_key_roundtrip():
    cached = CachedKey(b"0" * 32, "yubikey")
    assert CachedKey.decode(cached.encode()) == cached

    assert CachedKey.decode("nonsense") is None
    assert CachedKey.decode("password:") is None


def test_process_cache():
    cache = ProcessKeyCache()
    assert cache.get("x") is None

    cache.put("x", CachedKey(b"1" * 32, "password"))
    assert cache.get("x").key == b"1" * 32

    cache.drop("x")
    assert cache.get("x") is None


# --- the keystore ---


def test_keystore_roundtrip(store, salt):
    vault_id = vault_id_for(salt)
    assert store.get(vault_id) is None

    wrapped = new_wrapped_key(vault_id, b"cred", b"s" * 32, b"n" * 12, b"ct", "2fas.local", FILENAME)
    path = store.put(wrapped)

    assert oct(path.stat().st_mode)[-3:] == "600"
    assert store.get(vault_id) == wrapped
    assert [_.vault_id for _ in store.all()] == [vault_id]

    assert store.delete(vault_id)
    assert not store.delete(vault_id)


def test_keystore_ignores_corrupt_blobs(store):
    store.directory.mkdir(parents=True)
    (store.directory / "deadbeef.json").write_text("{not json")
    (store.directory / "cafe.json").write_text('{"version": 99}')

    assert store.get("deadbeef") is None
    assert store.all() == []


def test_prune_keeps_entries_whose_file_still_exists(store, salt):
    store.put(new_wrapped_key(vault_id_for(salt), b"c", b"s" * 32, b"n" * 12, b"ct", "2fas.local", FILENAME))

    assert prune_keystore(store, []) == []  # file exists -> keep, without reading anything
    assert len(store.all()) == 1


def test_prune_drops_orphans(store):
    store.put(new_wrapped_key("orphan", b"c", b"s" * 32, b"n" * 12, b"ct", "2fas.local", "/gone/vault.2fas"))

    removed = prune_keystore(store, [])
    assert [_.vault_id for _ in removed] == ["orphan"]
    assert store.all() == []


def test_prune_keeps_moved_vaults(store, salt):
    # the enrolled path is gone, but a known file still has that salt: keep it.
    store.put(new_wrapped_key(vault_id_for(salt), b"c", b"s" * 32, b"n" * 12, b"ct", "2fas.local", "/gone/vault.2fas"))

    assert prune_keystore(store, [FILENAME]) == []
    assert len(store.all()) == 1


# --- the policy engine ---


def test_password_path_unlocks_and_caches(monkeypatch, store, salt, key, no_session_cache):
    monkeypatch.setattr("getpass.getpass", typed(PASSWORD))

    unlocker = PolicyUnlocker(password_policy="process", store=store)
    assert unlocker.unlock(FILENAME, salt) == key
    assert unlocker.used_path == "password"

    # second call must not prompt again:
    monkeypatch.setattr("getpass.getpass", typed("wrong"))
    assert unlocker.unlock(FILENAME, salt) == key


def test_process_policy_never_touches_the_keyring(monkeypatch, store, salt):
    monkeypatch.setattr("getpass.getpass", typed(PASSWORD))
    written: list[tuple[str, str]] = []
    monkeypatch.setattr(unlock_module.SessionKeyCache, "service", lambda self: "2fas:test")
    monkeypatch.setattr(unlock_module.SessionKeyCache, "get", lambda self, vault_id: None)
    monkeypatch.setattr(
        unlock_module.SessionKeyCache, "put", lambda self, vault_id, cached: written.append((vault_id, cached.via))
    )

    PolicyUnlocker(password_policy="process", store=store).unlock(FILENAME, salt)
    assert written == []

    PolicyUnlocker(password_policy="os-session", store=store).unlock(FILENAME, salt)
    assert [via for _, via in written] == ["password"]


def test_tight_policies_ignore_a_stored_passphrase(monkeypatch, store, salt, key, no_session_cache):
    # a passphrase left in the keyring must not silently satisfy 'ask me every time'.
    monkeypatch.setattr(lib2fas.keyring_manager, "retrieve_credentials", lambda filename: PASSWORD, raising=False)
    monkeypatch.setattr("getpass.getpass", typed(PASSWORD))

    unlocker = PolicyUnlocker(password_policy="code", store=store)
    assert unlocker.unlock(FILENAME, salt) == key
    assert unlocker.needs_confirmation()


def test_load_services_through_the_unlocker(monkeypatch, store, salt, no_session_cache):
    monkeypatch.setattr("getpass.getpass", typed(PASSWORD))

    unlocker = PolicyUnlocker(password_policy="process", store=store)
    assert lib2fas.load_services(FILENAME, unlocker=unlocker)


def test_wrong_passphrase_is_retried_and_not_remembered(monkeypatch, store, salt, no_session_cache):
    attempts = iter(["wrong", PASSWORD])
    monkeypatch.setattr("getpass.getpass", lambda _: next(attempts))

    unlocker = PolicyUnlocker(password_policy="process", store=store)
    assert lib2fas.load_services(FILENAME, _max_retries=3, unlocker=unlocker)


# --- the yubikey path, with the hardware faked out ---


class FakeYubiKey:
    """Stands in for src.twofas.yubikey, so the policy logic is testable without hardware."""

    def __init__(self, secret: bytes = b"S" * 32, error: Exception = None) -> None:
        self.secret = secret
        self.error = error
        self.touches = 0

    DEFAULT_TIMEOUT = 30.0
    RP_ID = "2fas.local"

    def evaluate_hmac_secret(self, credential_id, hmac_salt, timeout=None, announce=None):
        self.touches += 1
        if self.error:
            raise self.error
        return self.secret

    def new_hmac_salt(self) -> bytes:
        return b"H" * 32

    def create_credential(self, pin=None, timeout=None, announce=None) -> bytes:
        return b"credential-id"

    def wrap_key(self, secret, vault_id, vault_key):
        assert secret == self.secret
        return b"n" * 12, bytes(a ^ b for a, b in zip(vault_key, secret))

    def unwrap_key(self, secret, vault_id, nonce, ciphertext):
        if secret != self.secret:
            raise unlock_module.YubiKeyError("wrong key")
        return bytes(a ^ b for a, b in zip(ciphertext, secret))


def enrolled_store(store: KeyStore, salt: bytes, key: bytes, fake: FakeYubiKey) -> KeyStore:
    vault_id = vault_id_for(salt)
    nonce, ciphertext = fake.wrap_key(fake.secret, vault_id, key)
    store.put(new_wrapped_key(vault_id, b"cred", b"H" * 32, nonce, ciphertext, "2fas.local", FILENAME))
    return store


def test_yubikey_path_unlocks_without_a_passphrase(monkeypatch, store, salt, key, no_session_cache):
    fake = FakeYubiKey()
    enrolled_store(store, salt, key, fake)

    monkeypatch.setattr("getpass.getpass", typed("should not be asked"))
    unlocker = PolicyUnlocker(method="yubikey", yubikey_policy="process", store=store)
    unlocker._import_yubikey = lambda: fake

    assert unlocker.unlock(FILENAME, salt) == key
    assert unlocker.used_path == "yubikey"
    assert fake.touches == 1


def test_falls_back_to_the_passphrase_when_the_key_is_missing(monkeypatch, store, salt, key, no_session_cache):
    fake = FakeYubiKey(error=unlock_module.YubiKeyError("not plugged in"))
    enrolled_store(store, salt, key, FakeYubiKey())

    monkeypatch.setattr("getpass.getpass", typed(PASSWORD))
    unlocker = PolicyUnlocker(method="yubikey", yubikey_policy="code", store=store)
    unlocker._import_yubikey = lambda: fake

    assert unlocker.unlock(FILENAME, salt) == key
    # the policy must follow the path taken, not the method configured:
    assert unlocker.used_path == "password"
    assert unlocker.effective_policy() == "os-session"
    assert not unlocker.needs_confirmation()


def test_no_enrolment_falls_back_without_touching_hardware(monkeypatch, store, salt, key, no_session_cache):
    fake = FakeYubiKey()
    monkeypatch.setattr("getpass.getpass", typed(PASSWORD))

    unlocker = PolicyUnlocker(method="yubikey", store=store)
    unlocker._import_yubikey = lambda: fake

    assert unlocker.unlock(FILENAME, salt) == key
    assert unlocker.used_path == "password"
    assert fake.touches == 0


def test_force_password_skips_the_key(monkeypatch, store, salt, key, no_session_cache):
    fake = FakeYubiKey()
    enrolled_store(store, salt, key, fake)
    monkeypatch.setattr("getpass.getpass", typed(PASSWORD))

    unlocker = PolicyUnlocker(method="yubikey", store=store, force_password=True)
    unlocker._import_yubikey = lambda: fake

    assert unlocker.unlock(FILENAME, salt) == key
    assert fake.touches == 0


def test_confirmation_rejects_a_wrong_passphrase(monkeypatch, store, salt, key, no_session_cache):
    monkeypatch.setattr("getpass.getpass", typed(PASSWORD))
    unlocker = PolicyUnlocker(password_policy="code", store=store)
    unlocker.unlock(FILENAME, salt)

    assert unlocker.confirm()

    monkeypatch.setattr("getpass.getpass", typed("wrong"))
    assert not unlocker.confirm()


def test_confirmation_is_skipped_under_looser_policies(monkeypatch, store, salt, no_session_cache):
    monkeypatch.setattr("getpass.getpass", typed(PASSWORD))
    unlocker = PolicyUnlocker(password_policy="process", store=store)
    unlocker.unlock(FILENAME, salt)

    monkeypatch.setattr("getpass.getpass", typed("would fail if it were asked"))
    assert unlocker.confirm()


def test_confirmation_touches_the_key_every_time(store, salt, key, no_session_cache):  # noqa: ARG001
    fake = FakeYubiKey()
    enrolled_store(store, salt, key, fake)

    unlocker = PolicyUnlocker(method="yubikey", yubikey_policy="code", store=store)
    unlocker._import_yubikey = lambda: fake
    assert unlocker.unlock(FILENAME, salt) == key

    assert unlocker.confirm()
    assert unlocker.confirm()
    assert fake.touches == 3  # one unlock plus two confirmations
