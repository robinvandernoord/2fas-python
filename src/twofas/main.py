import sys

from ._security import cleanup_keyring
from .core import load_services


def _main(filename: str = '') -> None:
    cleanup_keyring()

    if not filename:
        print('todo: remember previous file(s)')
        return

    decrypted = load_services(filename)

    print([(_, _.generate()) for _ in decrypted])


def main() -> None:
    return _main(*sys.argv[1:])


if __name__ == "__main__":
    # fixme: soft-code
    # todo: store prefered 2fas file somewhere
    # todo: deal with unencrypted ones
    main()
