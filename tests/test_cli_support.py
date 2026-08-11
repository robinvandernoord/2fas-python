import threading
import time

import pytest
import questionary
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from src.twofas.cli_support import (
    cursor_value,
    escapable,
    generate_choices,
    generate_custom_style,
    state,
)


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


def _piped(keys: str, delay: float = 0.0):
    """Run a menu against a pipe, optionally sending the keys a moment after it starts."""
    choices = [
        questionary.Choice("first", "a"),
        questionary.Choice("second", "b"),
        questionary.Choice("third", "c"),
    ]

    with create_pipe_input() as pipe:
        question = questionary.select(
            "q?", choices=choices, default="b", input=pipe, output=DummyOutput(), use_shortcuts=True
        )
        escapable(question)
        if delay:
            threading.Timer(delay, lambda: pipe.send_text(keys)).start()
        else:
            pipe.send_text(keys)
        started = time.monotonic()
        result = question.unsafe_ask()
        return result, time.monotonic() - started - delay


def test_menu_starts_on_the_current_value():
    # `default` is what parks the cursor, so plain Enter must return it:
    assert _piped("\r")[0] == "b"


def test_escape_backs_out_of_a_menu():
    assert _piped("\x1b")[0] is None


def test_escape_does_not_break_arrow_keys():
    # arrow keys *are* escape sequences, so a too-eager Escape binding would eat them.
    assert _piped("\x1b[B\r")[0] == "c"
    assert _piped("\x1b[A\r")[0] == "a"


def test_escape_is_not_perceptibly_slow():
    # it used to take 1.5s (1.0 binding + 0.5 sequence timeout), which reads as
    # "escape does not work" and gets you pressing it a second time.
    result, elapsed = _piped("\x1b", delay=0.2)

    assert result is None
    assert elapsed < 0.4, f"escape took {elapsed:.3f}s"


def test_ctrl_c_is_not_swallowed():
    # Escape means 'back'; Ctrl-C means 'quit', as it does in every other CLI.
    with pytest.raises(KeyboardInterrupt):
        _piped("\x03")


def test_style_without_selected_marking():
    # single-choice menus turn 'selected' off, because questionary lets it override the
    # cursor highlight and then one row is painted a different color for no reason.
    assert generate_custom_style(mark_selected=False)


def test_cursor_skips_an_unselectable_current():
    choices = generate_choices({"a": "a", "b": "b"}, with_exit=False, disabled={"b": "not yet"})

    assert cursor_value(choices, "a") == "a"
    # 'b' is what the settings file says, but it is greyed out: no cursor rather than a crash
    assert cursor_value(choices, "b") is None
    assert cursor_value(choices, "nonsense") is None
    assert cursor_value(choices, None) is None

    # a separator has no usable value and must not become the cursor target:
    assert cursor_value([questionary.Separator()], None) is None
