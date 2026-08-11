import typing

import lib2fas
import pytest

from src.twofas import unlock as unlock_module
from src.twofas.keystore import KeyStore, new_wrapped_key, vault_id_for
from src.twofas.unlock import (
    CachedKey,
    PolicyUnlocker,
    ProcessKeyCache,
    UnlockMethod,
    UnlockPolicy,
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


class FakeSessionCache:
    """Stands in for the login keyring, which the machine running the tests may not have."""

    def __init__(self, **entries: CachedKey) -> None:
        self.entries = dict(entries)
        self.writes: list[tuple[str, str]] = []

    def get(self, vault_id: str) -> CachedKey | None:
        return self.entries.get(vault_id)

    def put(self, vault_id: str, cached: CachedKey) -> None:
        self.entries[vault_id] = cached
        self.writes.append((vault_id, cached.via))

    def drop(self, vault_id: str) -> None:
        self.entries.pop(vault_id, None)


class FakeKeyring(lib2fas.KeyringManagerProtocol):
    """Stands in for lib2fas' keyring manager, holding a passphrase an older version left."""

    def __init__(self, passphrase: str = None) -> None:
        self.passphrase = passphrase

    def retrieve_credentials(self, filename: str) -> str | None:
        return self.passphrase

    def save_credentials(self, filename: str) -> str:  # pragma: no cover
        return self.passphrase or ""

    def delete_credentials(self, filename: str) -> None:
        self.passphrase = None

    def cleanup_keyring(self) -> int:
        return 0


def typed(*values: str) -> typing.Callable[[str], str]:
    """A passphrase prompt that answers with each value in turn, repeating the last."""
    answers = list(values)

    def prompt(_: str) -> str:
        return answers.pop(0) if len(answers) > 1 else answers[0]

    return prompt


def unlocker_for(store: KeyStore, session: FakeSessionCache = None, **kwargs) -> PolicyUnlocker:
    """A PolicyUnlocker with every outside dependency replaced by something inspectable."""
    kwargs.setdefault("prompt", typed(PASSWORD))
    kwargs.setdefault("keyring_manager", FakeKeyring())
    return PolicyUnlocker(store=store, session_cache=session or FakeSessionCache(), **kwargs)


# --- settings parsing ---


def test_parse_method():
    assert parse_method("security-key") is UnlockMethod.SECURITY_KEY
    assert parse_method("PASSWORD") is UnlockMethod.PASSWORD
    assert parse_method("security_key") is UnlockMethod.SECURITY_KEY  # underscores are forgiven
    assert parse_method(None) is UnlockMethod.PASSWORD
    assert parse_method("nonsense") is UnlockMethod.PASSWORD


def test_parse_policy():
    assert parse_policy("code", UnlockPolicy.PROCESS) is UnlockPolicy.CODE
    assert parse_policy("os_session", UnlockPolicy.PROCESS) is UnlockPolicy.OS_SESSION
    assert parse_policy("", UnlockPolicy.PROCESS) is UnlockPolicy.PROCESS
    assert parse_policy("nonsense", UnlockPolicy.OS_SESSION) is UnlockPolicy.OS_SESSION


def test_settings_round_trip_through_toml(tmp_path):
    # the reason these were plain strings before: configuraptor runs values through type
    # conversion on the way to the TOML file, and a mangled value would silently reset
    # someone's unlock method. A StrEnum has to survive that untouched.
    from configuraptor import Singleton

    from src.twofas.cli_settings import get_cli_setting, set_cli_setting

    config = tmp_path / "config.toml"
    config.write_text("[tool.2fas]\n")

    Singleton.clear()
    set_cli_setting("unlock-method", UnlockMethod.SECURITY_KEY, config)
    set_cli_setting("security-key-unlock-policy", UnlockPolicy.CODE, config)

    assert 'unlock_method = "security-key"' in config.read_text()
    assert 'security_key_unlock_policy = "code"' in config.read_text()

    Singleton.clear()
    assert parse_method(get_cli_setting("unlock-method", config)) is UnlockMethod.SECURITY_KEY
    assert (
        parse_policy(get_cli_setting("security-key-unlock-policy", config), UnlockPolicy.PROCESS) is UnlockPolicy.CODE
    )
    Singleton.clear()


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
    cached = CachedKey(b"0" * 32, UnlockMethod.SECURITY_KEY)
    assert CachedKey.decode(cached.encode()) == cached

    assert CachedKey.decode("nonsense") is None
    assert CachedKey.decode("password:") is None


def test_process_cache():
    cache = ProcessKeyCache()
    assert cache.get("x") is None

    cache.put("x", CachedKey(b"1" * 32, UnlockMethod.PASSWORD))
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


def test_password_path_unlocks_and_caches(store, salt, key):
    unlocker = unlocker_for(store, password_policy="process", prompt=typed(PASSWORD, "wrong"))

    assert unlocker.unlock(FILENAME, salt) == key
    assert unlocker.used_path == "password"
    # the second call would get the wrong passphrase, so it must not be asking:
    assert unlocker.unlock(FILENAME, salt) == key


def test_process_policy_never_touches_the_keyring(store, salt):
    session = FakeSessionCache()

    unlocker_for(store, session, password_policy="process").unlock(FILENAME, salt)
    assert session.writes == []

    unlocker_for(store, session, password_policy="os-session").unlock(FILENAME, salt)
    assert [via for _, via in session.writes] == ["password"]


def test_tight_policies_ignore_a_stored_passphrase(store, salt, key):
    # a passphrase left in the keyring by an older version must not silently satisfy
    # 'ask me every time'.
    unlocker = unlocker_for(store, password_policy="code", keyring_manager=FakeKeyring(PASSWORD))

    assert unlocker.unlock(FILENAME, salt) == key
    assert unlocker.needs_confirmation()


def test_load_services_through_the_unlocker(store, salt):
    assert lib2fas.load_services(FILENAME, unlocker=unlocker_for(store, password_policy="process"))


def test_wrong_passphrase_is_retried_and_not_remembered(store, salt):
    unlocker = unlocker_for(store, password_policy="process", prompt=typed("wrong", PASSWORD))

    assert lib2fas.load_services(FILENAME, max_retries=3, unlocker=unlocker)


# --- the security key path, with the hardware faked out ---


class FakeSecurityKey:
    """Stands in for src.twofas.security_key, so the policy logic is testable without hardware."""

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
            raise unlock_module.SecurityKeyError("wrong key")
        return bytes(a ^ b for a, b in zip(ciphertext, secret))


def enrolled_store(store: KeyStore, salt: bytes, key: bytes, fake: FakeSecurityKey) -> KeyStore:
    vault_id = vault_id_for(salt)
    nonce, ciphertext = fake.wrap_key(fake.secret, vault_id, key)
    store.put(new_wrapped_key(vault_id, b"cred", b"H" * 32, nonce, ciphertext, "2fas.local", FILENAME))
    return store


def security_key_unlocker(store: KeyStore, fake: FakeSecurityKey, session: FakeSessionCache = None, **kwargs):
    """A PolicyUnlocker whose 'hardware' is a FakeSecurityKey."""
    kwargs.setdefault("method", "security-key")
    return unlocker_for(store, session, backend=fake, **kwargs)


def test_security_key_path_unlocks_without_a_passphrase(store, salt, key):
    fake = FakeSecurityKey()
    enrolled_store(store, salt, key, fake)

    unlocker = security_key_unlocker(store, fake, security_key_policy="process", prompt=typed("should not be asked"))

    assert unlocker.unlock(FILENAME, salt) == key
    assert unlocker.used_path == "security-key"
    assert fake.touches == 1


def test_falls_back_to_the_passphrase_when_the_key_is_missing(store, salt, key):
    enrolled_store(store, salt, key, FakeSecurityKey())
    absent = FakeSecurityKey(error=unlock_module.SecurityKeyError("not plugged in"))

    unlocker = security_key_unlocker(store, absent, security_key_policy="code")

    assert unlocker.unlock(FILENAME, salt) == key
    # the policy must follow the path taken, not the method configured:
    assert unlocker.used_path == "password"
    assert unlocker.effective_policy() == "os-session"
    assert not unlocker.needs_confirmation()


def test_no_enrolment_falls_back_without_touching_hardware(store, salt, key):
    fake = FakeSecurityKey()
    unlocker = security_key_unlocker(store, fake)

    assert unlocker.unlock(FILENAME, salt) == key
    assert unlocker.used_path == "password"
    assert fake.touches == 0


def test_force_password_skips_the_key(store, salt, key):
    fake = FakeSecurityKey()
    enrolled_store(store, salt, key, fake)

    unlocker = security_key_unlocker(store, fake, force_password=True)

    assert unlocker.unlock(FILENAME, salt) == key
    assert fake.touches == 0


def test_confirmation_rejects_a_wrong_passphrase(store, salt):
    unlocker = unlocker_for(store, password_policy="code", prompt=typed(PASSWORD, PASSWORD, "wrong"))
    unlocker.unlock(FILENAME, salt)

    assert unlocker.confirm()
    assert not unlocker.confirm()


def test_confirmation_is_skipped_under_looser_policies(store, salt):
    unlocker = unlocker_for(store, password_policy="process", prompt=typed(PASSWORD, "would fail if asked"))
    unlocker.unlock(FILENAME, salt)

    assert unlocker.confirm()


def test_confirmation_touches_the_key_every_time(store, salt, key):
    fake = FakeSecurityKey()
    enrolled_store(store, salt, key, fake)

    unlocker = security_key_unlocker(store, fake, security_key_policy="code")
    assert unlocker.unlock(FILENAME, salt) == key

    assert unlocker.confirm()
    assert unlocker.confirm()
    assert fake.touches == 3  # one unlock plus two confirmations


# --- the cache must respect both the configured method and the policy tier ---


def test_process_policy_ignores_a_key_another_run_left_behind(store, salt, key):
    # 'once per run' has to mean it, so the cross-process cache may not even be read.
    cached = {vault_id_for(salt): CachedKey(key, UnlockMethod.PASSWORD)}
    prompted: list[str] = []

    def counting_prompt(message: str) -> str:
        prompted.append(message)
        return PASSWORD

    # under os-session the key comes from the keyring, so nothing is asked:
    unlocker_for(store, FakeSessionCache(**cached), password_policy="os-session", prompt=counting_prompt).unlock(
        FILENAME, salt
    )
    assert prompted == []

    # under process that same cache entry must be ignored:
    unlocker_for(store, FakeSessionCache(**cached), password_policy="process", prompt=counting_prompt).unlock(
        FILENAME, salt
    )
    assert len(prompted) == 1


def test_a_passphrase_cache_does_not_satisfy_the_security_key_method(store, salt, key):
    # the bug: after setting up a key, a key cached by the earlier passphrase run kept
    # unlocking the vault, so switching the method looked like it did nothing at all.
    fake = FakeSecurityKey()
    enrolled_store(store, salt, key, fake)
    session = FakeSessionCache(**{vault_id_for(salt): CachedKey(key, UnlockMethod.PASSWORD)})

    unlocker = security_key_unlocker(store, fake, session, security_key_policy="os-session")

    assert unlocker.unlock(FILENAME, salt) == key
    assert unlocker.used_path == "security-key"
    assert fake.touches == 1


def test_a_security_key_cache_is_reused_under_os_session(store, salt, key):
    fake = FakeSecurityKey()
    enrolled_store(store, salt, key, fake)
    session = FakeSessionCache(**{vault_id_for(salt): CachedKey(key, UnlockMethod.SECURITY_KEY)})

    unlocker = security_key_unlocker(store, fake, session, security_key_policy="os-session")

    assert unlocker.unlock(FILENAME, salt) == key
    assert fake.touches == 0  # one touch per boot, and this boot already had one


def test_security_key_touches_every_run_under_process(store, salt, key):
    fake = FakeSecurityKey()
    enrolled_store(store, salt, key, fake)
    session = FakeSessionCache(**{vault_id_for(salt): CachedKey(key, UnlockMethod.SECURITY_KEY)})

    unlocker = security_key_unlocker(store, fake, session, security_key_policy="process")

    assert unlocker.unlock(FILENAME, salt) == key
    assert fake.touches == 1
    assert session.writes == []  # and nothing is left behind for the next run

    # ...but within this one run the key is not asked for twice:
    assert unlocker.unlock(FILENAME, salt) == key
    assert fake.touches == 1


def test_unenrolled_vault_uses_the_passphrase_cache(store, salt, key):
    # method is security-key, but this particular vault has no key set up: the passphrase
    # is what will be used, so its cache is the right one to consult.
    session = FakeSessionCache(**{vault_id_for(salt): CachedKey(key, UnlockMethod.PASSWORD)})

    unlocker = security_key_unlocker(
        store, FakeSecurityKey(), session, password_policy="os-session", prompt=typed("would fail if asked")
    )

    assert unlocker.unlock(FILENAME, salt) == key
    assert unlocker.used_path == "password"
