import pytest

from src.twofas import load_services
from src.twofas._types import TwoFactorAuthDetails
from src.twofas.core import TwoFactorStorage
from ._shared import CWD

FILENAME = str(CWD / "2fas-demo-nopass.2fas")


def test_empty():
    storage = TwoFactorStorage()
    assert not storage


@pytest.fixture
def services():
    yield load_services(FILENAME)


def test_load(services):
    assert services

    assert len(list(services)) == services.count == 4

    assert len(services.keys()) == 3  # 1 2 and 3

    assert "3" in repr(services) and "4" in repr(services)

    example_1 = services["Example 1"]
    example_1a, example_1b = example_1  # type: TwoFactorAuthDetails

    totp_1a = example_1a.generate()
    totp_1b = example_1b.generate_int()

    assert totp_1a
    assert totp_1b

    assert totp_1a != str(totp_1b)
    assert int(totp_1a) != totp_1b

    example_2 = services["Example 2"]
    assert len(example_2) == 1

    example_2 = example_2[0]

    assert str(example_2.generate_int()).rjust(6, '0') == example_2.generate()
    assert example_2.generate_int() == int(example_2.generate())


def test_search_exact(services):
    found = services.find("Example 1")
    assert len(found) == 2
    assert found == services["Example 1"]


def test_search_fuzzy(services):
    assert services.find() == services.all()

    found = services.find("Example")
    assert len(found) == 4

    found = services.find("1")
    assert len(found) == 2

    found = services.find("2")
    assert len(found) == 1

    found = services.find("___")
    assert len(found) == 0
