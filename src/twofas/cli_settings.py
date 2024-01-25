import typing
from pathlib import Path
from typing import Any

import tomli_w
from configuraptor import TypedConfig, asdict, beautify, singleton
from configuraptor.core import convert_key

config = Path("~/.config").expanduser()
config.mkdir(exist_ok=True)
DEFAULT_SETTINGS = config / "2fas.toml"
DEFAULT_SETTINGS.touch(exist_ok=True)

CONFIG_KEY = "tool.2fas"


def expand_path(file: str | Path) -> str:
    return str(Path(file).expanduser())


def expand_paths(paths: typing.Iterable[str]) -> list[str]:
    return [expand_path(f) for f in paths]


@beautify
class CliSettings(TypedConfig, singleton.Singleton):
    files: list[str] | None
    default_file: str | None
    auto_verbose: bool = False

    def add_file(self, filename: str | None, _config_file: str | Path = DEFAULT_SETTINGS) -> None:
        if not filename:
            return

        filename = expand_path(filename)

        files = self.files or []
        if filename not in files:
            files.append(filename)

            set_cli_setting("files", expand_paths(files), _config_file)

        self.files = expand_paths(files)

    def remove_file(self, filenames: str | typing.Iterable[str], _config_file: str | Path = DEFAULT_SETTINGS) -> None:
        if isinstance(filenames, str | Path):
            filenames = [filenames]

        filenames = set(expand_paths(filenames))

        files = [expand_path(_) for _ in (self.files or []) if _ not in filenames]

        if self.default_file in filenames:
            print("yuhu", files, self.default_file)
            new_default = files[0] if files else None
            set_cli_setting("default-file", new_default, _config_file)
            self.default_file = new_default
            print("yuhup", new_default, self.default_file)

        set_cli_setting("files", files, _config_file)
        self.files = files

        print(f"{self=}")


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
    settings.update(**{key: value}, _convert_types=True)

    inner_data = asdict(
        settings,
        with_top_level_key=False,
    )

    # toml can't deal with None, so skip those:
    inner_data = {k: v for k, v in inner_data.items() if v is not None}
    outer_data = {"tool": {"2fas": inner_data}}

    filepath.write_text(tomli_w.dumps(outer_data))
