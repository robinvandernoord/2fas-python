import sys

from ._security import keyring_manager
from .core import load_services


def _main(filename: str = "") -> None:
    keyring_manager.cleanup_keyring()

    if not filename:
        print("todo: remember previous file(s)")
        return

    decrypted = load_services(filename)

    print([(_, _.generate()) for _ in decrypted.all()])


def main() -> None:
    return _main(*sys.argv[1:])


if __name__ == "__main__":
    main()
