import pytest

from src.twofas.cli_support import state, generate_custom_style


def test_state():
    # test singleton:
    assert state is state.__class__()


def test_style():
    assert generate_custom_style()
    assert generate_custom_style("blue", "blue")

    with pytest.raises(ValueError):
        assert generate_custom_style("this-is-not-a-color", "this-is-not-a-color")
