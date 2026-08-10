import pytest

from src.twofas.cli_support import generate_choices, generate_custom_style, state


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


def test_escape_backs_out_of_a_menu():
    import questionary
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    from src.twofas.cli_support import ask

    choices = [questionary.Choice("first", "a"), questionary.Choice("second", "b")]

    def run(keys: str):
        with create_pipe_input() as pipe:
            pipe.send_text(keys)
            return ask(questionary.select("q?", choices=choices, default="b", input=pipe, output=DummyOutput()))

    assert run("\r") == "b"  # default is where the cursor starts
    assert run("\x1b") is None  # escape backs out
    assert run("\x1b[A\r") == "a"  # ...without breaking arrow keys, which are escape sequences
