import typing
import warnings


class DummyGUI: ...


def dummy_start_gui_with_exception(e: Exception) -> typing.Callable[..., typing.NoReturn]:
    def dummy_start_gui(*_: typing.Any, **__: typing.Any) -> typing.NoReturn:
        warnings.warn("Can't use the gui! You may need to run `pip install 2fas[gui]` to fix this.", source=e)
        exit(2)

    return dummy_start_gui


try:
    from ._gui import GUI, start_gui
except ImportError as e:
    GUI = DummyGUI  # type: ignore
    start_gui = dummy_start_gui_with_exception(e)

__all__ = [
    "GUI",
    "start_gui",
]
