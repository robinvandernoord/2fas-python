import typing

from more_itertools import flatten as _flatten
from rapidfuzz import fuzz

T = typing.TypeVar("T")


def flatten(data: list[list[T]]) -> list[T]:
    return list(_flatten(data))


def fuzzy_match(val1: str, val2: str) -> float:
    return fuzz.partial_ratio(val1, val2)
