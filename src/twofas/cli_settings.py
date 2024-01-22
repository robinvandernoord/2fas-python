import typing
from pathlib import Path
from typing import Any

import tomli_w
from configuraptor import TypedConfig, asdict
from configuraptor.core import convert_key

config = Path("~/.config").expanduser()
config.mkdir(exist_ok=True)
DEFAULT_SETTINGS = config / "2fas.toml"
DEFAULT_SETTINGS.touch(exist_ok=True)

CONFIG_KEY = "tool.2fas"


class CliSettings(TypedConfig):
    files: list[str] | None
    default_file: str | None


def load_cli_settings(input_file: str | Path = DEFAULT_SETTINGS, **overwrite: Any) -> CliSettings:
    return CliSettings.load([input_file, overwrite], key=CONFIG_KEY)


def get_cli_setting(key: str, filename: str | Path = DEFAULT_SETTINGS) -> typing.Any:
    key = convert_key(key)
    settings = load_cli_settings(filename)
    return getattr(settings, key)


def set_cli_setting(key: str, value: typing.Any, filename: str | Path = DEFAULT_SETTINGS) -> None:
    filepath = Path(filename)
    key = convert_key(key)

    settings = load_cli_settings(filepath)
    settings.update(**{key: value})

    inner_data = asdict(
        settings,
        with_top_level_key=False,
    )

    # toml can't deal with None, so skip those:
    inner_data = {k: v for k, v in inner_data.items() if v is not None}

    outer_data = {"tool": {"2fas": inner_data}}

    filepath.write_text(tomli_w.dumps(outer_data))
