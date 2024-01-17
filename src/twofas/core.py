import json
from pathlib import Path

from ._security import decrypt, retrieve_credentials, save_credentials
from ._types import TwoFactorAuthDetails


def load_services(filename: str) -> list[TwoFactorAuthDetails]:
    filepath = Path(filename)
    with filepath.open() as f:
        data_raw = f.read()
        data = json.loads(data_raw)

    encrypted = data["servicesEncrypted"]
    password = retrieve_credentials(filename) or save_credentials(filename)

    return decrypt(encrypted, password)
