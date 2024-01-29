import typing

import pytest

from src.twofas.cli_support import clear


@clear()
def with_parens_with_arg(into: str) -> str:
    return into


@clear
def without_parens_with_arg(into: str) -> str:
    return into


@clear
def without_parens_without_arg() -> str:
    return "hi"


@clear()
def with_parens_without_arg() -> str:
    return "hi"


@pytest.mark.mypy_testing
def test_returntype_clear_with_arg() -> None:
    xyz = with_parens_with_arg("xyz")

    typing.reveal_type(xyz)  # R: builtins.str

    abc = without_parens_with_arg("xyz")

    typing.reveal_type(abc)  # R: builtins.str


@pytest.mark.mypy_testing
def test_returntype_clear_without_arg() -> None:
    xyz = with_parens_without_arg()

    typing.reveal_type(xyz)  # R: builtins.str

    abc = without_parens_without_arg()

    typing.reveal_type(abc)  # R: builtins.str
