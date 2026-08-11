"""
This file contains helpers for the cli.
"""

import subprocess
import typing

import configuraptor
import questionary
from configuraptor import beautify, postpone
from prompt_toolkit.key_binding import KeyBindings

from .cli_settings import CliSettings
from .unlock import PolicyUnlocker


@beautify
class AppState(configuraptor.TypedConfig, configuraptor.Singleton):
    """
    Global state (settings from config + run-specific variables such as --verbose).
    """

    verbose: bool = False
    settings: CliSettings = postpone()
    # the unlocker for this run; see twofas.cli.get_unlocker
    unlocker: PolicyUnlocker | None = None


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
            subprocess.run(["clear"], check=False)
            return fn(*args, **kwargs)

        return inner
    else:
        return typing.cast(
            typing.Callable[[typing.Callable[P, R]], typing.Callable[P, R]],
            clear,
        )


@clear
def exit_with_clear(status_code: int) -> typing.Never:  # pragma: no cover
    """
    First clear the screen with the @clear decorator, then exit with a specific exit code.
    """
    exit(status_code)


def generate_custom_style(
    main_color: str = "green",  # "#673ab7"
    secondary_color: str = "#673ab7",  # "#f44336"
    mark_selected: bool = True,
) -> questionary.Style:
    """
    Reusable questionary style for all prompts of this tool.

    Primary and secondary color can be changed, other styles stay the same for consistency.

    Args:
        main_color: cursor and prompt color.
        secondary_color: submitted-answer color.
        mark_selected: keep the 'selected' color, which a checkbox needs to show its ticks.
            Single-choice menus pass False: they use `default` only to park the cursor on
            the value in force, and questionary's 'selected' style *overrides* the cursor
            highlight, so leaving it on paints that one row a different color for no reason.
    """
    return questionary.Style(
        [
            ("qmark", f"fg:{main_color} bold"),  # token in front of the question
            ("question", "bold"),  # question text
            ("answer", f"fg:{secondary_color} bold"),  # submitted answer text behind the question
            ("pointer", f"fg:{main_color} bold"),  # pointer used in select and checkbox prompts
            ("highlighted", f"fg:{main_color} bold"),  # pointed-at choice in select and checkbox prompts
            ("selected", f"fg:{main_color} bold" if mark_selected else ""),  # a checkbox' ticked items
            ("separator", "fg:#cc5454"),  # separator in lists
            ("instruction", ""),  # user instructions for select, rawselect, checkbox
            ("text", ""),  # plain text
            ("disabled", "fg:#858585 italic"),  # disabled choices for select and checkbox prompts
        ]
    )


# How long prompt_toolkit may spend deciding what a keypress meant.
#
# Escape is the problem child: on its own it means "back out", but it is also the first
# byte of every arrow key, so it can not be acted on the instant it arrives. Two separate
# waits used to add up to a second and a half, which reads as "Escape does not work" and
# gets you pressing it again:
#
# - `timeoutlen` (1.0s by default) is for an ambiguous *binding* - a complete match that is
#   also the prefix of a longer one. Binding Escape eagerly (below) settles that case
#   immediately, so this can go near zero.
# - `ttimeoutlen` (0.5s by default) is for an incomplete *escape sequence*, and this one
#   has to stay generous enough that a slow link can not split `ESC [ B` into a bare
#   Escape. 150ms is imperceptible and survives a 100ms gap between bytes.
BINDING_TIMEOUT = 0.05
ESCAPE_SEQUENCE_TIMEOUT = 0.15


def escapable(question: questionary.Question) -> questionary.Question:
    """
    Let Escape back out of a prompt, promptly.

    questionary only binds Ctrl-C, which leaves Escape - the key people actually reach for -
    doing nothing at all. See BINDING_TIMEOUT for why this also retunes the timeouts.
    """

    def escape(event: typing.Any) -> None:
        event.app.exit(result=None)

    bindings = question.application.key_bindings
    if isinstance(bindings, KeyBindings):
        add = typing.cast(typing.Callable[..., typing.Callable[[typing.Any], typing.Any]], bindings.add)
        add("escape", eager=True)(escape)

    question.application.timeoutlen = BINDING_TIMEOUT
    question.application.ttimeoutlen = ESCAPE_SEQUENCE_TIMEOUT
    return question


def ask(question: questionary.Question) -> typing.Any:
    """
    Ask a prompt where Escape backs out and Ctrl-C quits the program.

    Two keys, two meanings, everywhere in this tool: Escape returns None so the caller can
    go back a step, and Ctrl-C raises KeyboardInterrupt so it does what Ctrl-C does in every
    other command-line program.
    """
    return escapable(question).unsafe_ask()


def cursor_value(choices: list[questionary.Choice], current: typing.Any) -> typing.Any:
    """
    Where the cursor should start: on `current`, unless that can not be selected.

    A setting can perfectly well name an option that is greyed out right now - e.g.
    `unlock-method = security-key` with no key set up yet - and questionary raises on an
    unselectable initial choice, so that case has to degrade to 'no preference' rather
    than take the menu down with it.
    """
    selectable = {
        choice.value for choice in choices if not isinstance(choice, questionary.Separator) and not choice.disabled
    }
    return current if current in selectable else None


def menu(
    message: str,
    choices: list[questionary.Choice],
    current: typing.Any = None,
) -> typing.Any:
    """
    Ask one of this tool's menus.

    Every menu in 2fas goes through here, so they all behave the same: number shortcuts,
    Escape to go back, Ctrl-C to quit, and the cursor parked on the value already in force.

    Args:
        message: the question.
        choices: as built by `generate_choices`.
        current: the value in force, if any. Ignored when it is not selectable - a setting
            can name an option that is currently greyed out, and that must not be fatal.

    Returns:
        the value of the chosen option, or None if the user backed out.
    """
    return ask(
        questionary.select(
            message,
            choices=choices,
            # `default` is questionary's only lever for where the cursor starts:
            default=cursor_value(choices, current),
            use_shortcuts=True,
            use_indicator=False,
            style=generate_custom_style(mark_selected=False),
        )
    )


def generate_choices(
    choices: dict[str, typing.Any], with_exit: bool = True, disabled: dict[typing.Any, str] = {}
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
