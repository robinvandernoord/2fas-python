import pytest

from src.twofas.cli_support import state, generate_custom_style, generate_choices


def test_state():
    # test singleton:
    assert state is state.__class__()


def test_style():
    assert generate_custom_style()
    assert generate_custom_style("blue", "blue")

    with pytest.raises(ValueError):
        assert generate_custom_style("this-is-not-a-color", "this-is-not-a-color")


def test_choices():
    c = generate_choices({})
    assert len(c) == 1

    c = generate_choices({"label": "value"}, with_exit=False)
    assert len(c) == 1
