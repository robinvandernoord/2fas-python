import json
import sys
import typing
from collections import defaultdict
from pathlib import Path
from typing import Optional

from ._security import decrypt, keyring_manager
from ._types import TwoFactorAuthDetails, into_class
from .utils import flatten, fuzzy_match

T_TwoFactorAuthDetails = typing.TypeVar("T_TwoFactorAuthDetails", bound=TwoFactorAuthDetails)


class TwoFactorStorage(typing.Generic[T_TwoFactorAuthDetails]):
    _multidict: defaultdict[str, list[T_TwoFactorAuthDetails]]
    count: int

    def __init__(self, _klass: typing.Type[T_TwoFactorAuthDetails] = None) -> None:
        # _klass is purely for annotation atm

        self._multidict = defaultdict(list)  # one name can map to multiple keys
        self.count = 0

    def __len__(self) -> int:
        return self.count

    def __bool__(self) -> bool:
        return self.count > 0

    def add(self, entries: list[T_TwoFactorAuthDetails]) -> None:
        for entry in entries:
            name = (entry.name or "").lower()
            self._multidict[name].append(entry)

        self.count += len(entries)

    def __getitem__(self, item: str) -> "list[T_TwoFactorAuthDetails]":
        # class[property] syntax
        return self._multidict[item.lower()]

    def keys(self) -> list[str]:
        return list(self._multidict.keys())

    def items(self) -> typing.Generator[tuple[str, list[T_TwoFactorAuthDetails]], None, None]:
        yield from self._multidict.items()

    def _fuzzy_find(self, find: typing.Optional[str], fuzz_threshold: int) -> list[T_TwoFactorAuthDetails]:
        if not find:
            # don't loop
            return list(self)

        all_items = self._multidict.items()

        find = find.lower()
        # if nothing found exactly, try again but fuzzy (could be slower)
        # search in key:
        fuzzy = [
            # search in key
            v
            for k, v in all_items
            if fuzzy_match(k.lower(), find) > fuzz_threshold
        ]
        if fuzzy and (flat := flatten(fuzzy)):
            return flat

        # search in value:
        # str is short, repr is json
        return [
            # search in value instead
            v
            for v in list(self)
            if fuzzy_match(repr(v).lower(), find) > fuzz_threshold
        ]

    def generate(self) -> list[tuple[str, str]]:
        return [(_.name, _.generate()) for _ in self]

    def find(
        self, target: Optional[str] = None, fuzz_threshold: int = 75
    ) -> "TwoFactorStorage[T_TwoFactorAuthDetails]":
        target = (target or "").lower()
        # first try exact match:
        if items := self._multidict.get(target):
            return new_auth_storage(items)
        # else: fuzzy match:
        return new_auth_storage(self._fuzzy_find(target, fuzz_threshold))

    def all(self) -> list[T_TwoFactorAuthDetails]:
        return list(self)

    def __iter__(self) -> typing.Generator[T_TwoFactorAuthDetails, None, None]:
        for entries in self._multidict.values():
            yield from entries

    def __repr__(self) -> str:
        return f"<TwoFactorStorage with {len(self._multidict)} keys and {self.count} entries>"


def new_auth_storage(initial_items: list[T_TwoFactorAuthDetails] = None) -> TwoFactorStorage[T_TwoFactorAuthDetails]:
    storage: TwoFactorStorage[T_TwoFactorAuthDetails] = TwoFactorStorage()

    if initial_items:
        storage.add(initial_items)

    return storage


def load_services(filename: str, _max_retries: int = 0) -> TwoFactorStorage[TwoFactorAuthDetails]:
    filepath = Path(filename).expanduser()
    with filepath.open() as f:
        data_raw = f.read()
        data = json.loads(data_raw)

    storage: TwoFactorStorage[TwoFactorAuthDetails] = new_auth_storage()

    if decrypted := data["services"]:
        services = into_class(decrypted, TwoFactorAuthDetails)
        storage.add(services)
        return storage

    encrypted = data["servicesEncrypted"]

    retries = 0
    while True:
        password = keyring_manager.retrieve_credentials(filename) or keyring_manager.save_credentials(filename)
        try:
            entries = decrypt(encrypted, password)
            storage.add(entries)
            return storage
        except PermissionError as e:
            retries += 1  # only really useful for pytest
            print(e, file=sys.stderr)
            keyring_manager.delete_credentials(filename)

            if _max_retries and retries > _max_retries:
                raise e
