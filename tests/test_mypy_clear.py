import typing

import pytest

from src.twofas.cli_support import clear


@clear()
def with_parens(into: str) -> str:
    return into


@clear
def without_parens(into: str) -> str:
    return into


@pytest.mark.mypy_testing
def test_returntype_clear() -> None:
    xyz = with_parens("xyz")

    typing.reveal_type(xyz)  # R: builtins.str

    abc = without_parens("xyz")

    typing.reveal_type(abc)  # R: builtins.str
