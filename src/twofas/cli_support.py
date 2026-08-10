"""
This file contains helpers for the cli.
"""

import os
import typing

import configuraptor
import questionary
from configuraptor import beautify, postpone
from typing_extensions import Never

from .cli_settings import CliSettings


@beautify
class AppState(configuraptor.TypedConfig, configuraptor.Singleton):
    """
    Global state (settings from config + run-specific variables such as --verbose).
    """

    verbose: bool = False
    settings: CliSettings = postpone()


state = AppState.load({})

P = typing.ParamSpec("P")
R = typing.TypeVar("R")


@typing.overload
def clear(fn: typing.Callable[P, R]) -> typing.Callable[P, R]:
    """
    When calling clear with parens, you get the same callable back.
    """


@typing.overload
def clear(fn: None = None) -> typing.Callable[[typing.Callable[P, R]], typing.Callable[P, R]]:
    """
    When calling clear without parens, you'll get the same callable back later.
    """


def clear(
    fn: typing.Callable[P, R] | None = None,
) -> typing.Callable[P, R] | typing.Callable[[typing.Callable[P, R]], typing.Callable[P, R]]:  # pragma: no cover
    """
    Clear the screen before executing a function.

    Examples:
        @clear
        def some_fun(): ...

        @clear()
        def other_func(): ...
    """
    if fn:

        def inner(*args: P.args, **kwargs: P.kwargs) -> R:
            os.system("clear")  # nosec: B605 B607
            return fn(*args, **kwargs)

        return inner
    else:
        return clear


@clear
def exit_with_clear(status_code: int) -> Never:  # pragma: no cover
    """
    First clear the screen with the @clear decorator, then exit with a specific exit code.
    """
    exit(status_code)


def generate_custom_style(
    main_color: str = "green",  # "#673ab7"
    secondary_color: str = "#673ab7",  # "#f44336"
) -> questionary.Style:
    """
    Reusable questionary style for all prompts of this tool.

    Primary and secondary color can be changed, other styles stay the same for consistency.
    """
    return questionary.Style(
        [
            ("qmark", f"fg:{main_color} bold"),  # token in front of the question
            ("question", "bold"),  # question text
            ("answer", f"fg:{secondary_color} bold"),  # submitted answer text behind the question
            ("pointer", f"fg:{main_color} bold"),  # pointer used in select and checkbox prompts
            ("highlighted", f"fg:{main_color} bold"),  # pointed-at choice in select and checkbox prompts
            ("selected", "fg:#cc5454"),  # style for a selected item of a checkbox
            ("separator", "fg:#cc5454"),  # separator in lists
            ("instruction", ""),  # user instructions for select, rawselect, checkbox
            ("text", ""),  # plain text
            ("disabled", "fg:#858585 italic"),  # disabled choices for select and checkbox prompts
        ]
    )


def ask(question: questionary.Question) -> typing.Any:
    """
    Run a questionary prompt where Escape backs out, the same as Ctrl-C.

    questionary only binds Ctrl-C, which leaves Escape doing nothing in a menu - which is
    exactly the key people reach for. The binding is deliberately *not* eager: arrow keys
    arrive as escape sequences, so prompt_toolkit needs its moment to decide whether this
    was a bare Escape or the start of one.

    Returns:
        whatever the prompt returned, or None if the user backed out.
    """
    from prompt_toolkit.key_binding import KeyBindings

    def escape(event: typing.Any) -> None:
        event.app.exit(result=None)

    bindings = question.application.key_bindings
    if isinstance(bindings, KeyBindings):
        # not eager: arrow keys are escape sequences, so prompt_toolkit needs its moment
        # to tell a bare Escape from the start of one.
        add = typing.cast(typing.Callable[..., typing.Callable[[typing.Any], typing.Any]], bindings.add)
        add("escape")(escape)

    return question.ask()


def generate_choices(
    choices: dict[str, str], with_exit: bool = True, disabled: dict[str, str] = {}
) -> list[questionary.Choice]:
    """
    Turn a dict of label -> value items into a list of Choices with an automatic shortcut key (1 - 9).

    If with_exit is True, an option with shortcut key 0 will be added to quit the program.
    """
    result = [
        questionary.Choice(key, value, disabled=disabled.get(value), shortcut_key=str(idx))
        for idx, (key, value) in enumerate(choices.items(), 1)
    ]

    if with_exit:
        result.append(questionary.Choice("Exit", "exit", shortcut_key="0"))

    return result
