"""
This file deals with managing settings for 2fas.
"""

import sys
import typing
from pathlib import Path
from typing import Any

import tomli_w
from configuraptor import TypedConfig, asdict, beautify, singleton
from configuraptor.core import convert_key

config = Path("~/.config").expanduser()

# 2fas used to be a single file (~/.config/2fas.toml), but it now also stores per-vault
# blobs (wrapped keys), which do not belong in a settings file. Hence a directory.
CONFIG_DIR = config / "2fas"
DEFAULT_SETTINGS = CONFIG_DIR / "config.toml"
KEYS_DIR = CONFIG_DIR / "keys"

# every path this settings file has previously lived at, oldest first:
LEGACY_SETTINGS = [config / "2fas.toml", CONFIG_DIR / "2fas.toml"]

CONFIG_KEY = "tool.2fas"


def _migrate_legacy_settings() -> None:
    """
    Move an older settings file to its current home, exactly once.

    A move and not a copy: two files that both look authoritative is worse than one move
    the user is told about.
    """
    if DEFAULT_SETTINGS.exists():
        return

    for previous in LEGACY_SETTINGS:
        if not previous.is_file():
            continue

        try:
            previous.replace(DEFAULT_SETTINGS)
        except OSError as e:  # pragma: no cover
            print(f"Could not move {previous} to {DEFAULT_SETTINGS}: {e}", file=sys.stderr)
            return

        print(f"Note: moved your 2fas settings from {previous} to {DEFAULT_SETTINGS}.", file=sys.stderr)
        return


config.mkdir(parents=True, exist_ok=True)
CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
_migrate_legacy_settings()
DEFAULT_SETTINGS.touch(exist_ok=True)


def expand_path(file: str | Path | None) -> str:
    """
    Expand ~/... into /home/<user>/...
    """
    if not file:
        return ""

    return str(Path(file).expanduser().absolute())


def expand_paths(paths: typing.Iterable[str]) -> list[str]:
    """
    Expand multiple paths.
    """
    return [expand_path(f) for f in paths]


@beautify
class CliSettings(TypedConfig, singleton.Singleton):
    """
    Class for the ~/.config/2fas/config.toml settings file.
    """

    files: list[str] | None
    default_file: str | None
    auto_verbose: bool = False

    # How your vault gets unlocked, and how often you are asked.
    # These are plain strings and not enums on purpose: `set_cli_setting` runs values
    # through configuraptor's type conversion, and a str annotation makes that a no-op.
    # See twofas.unlock for the accepted values and the validation.
    unlock_method: str = "password"
    password_unlock_policy: str = "os-session"
    security_key_unlock_policy: str = "process"

    def add_file(self, filename: str | None, _config_file: str | Path = DEFAULT_SETTINGS) -> str | None:
        """
        Add a new 2fas file to the configs history list.
        """
        if not filename:
            return None

        filename = expand_path(filename)

        files = self.files or []
        if filename not in files:
            files.append(filename)

            set_cli_setting("files", expand_paths(files), _config_file)

        self.files = expand_paths(files)
        return expand_path(filename)

    def remove_file(self, filenames: str | typing.Iterable[str], _config_file: str | Path = DEFAULT_SETTINGS) -> None:
        """
        Remove a known 2fas file from the config's history list.
        """
        if isinstance(filenames, str | Path):
            filenames = [filenames]

        filenames_to_remove = set(expand_paths(filenames))
        current_files = expand_paths(self.files or [])
        files = [_ for _ in current_files if _ not in filenames_to_remove]

        if expand_path(self.default_file) in filenames_to_remove:
            new_default = files[0] if files else None
            set_cli_setting("default-file", new_default, _config_file)
            self.default_file = new_default

        set_cli_setting("files", files, _config_file)
        self.files = files


def load_cli_settings(input_file: str | Path = DEFAULT_SETTINGS, **overwrite: Any) -> CliSettings:
    """
    Load the config file into a CliSettings instance.
    """
    return CliSettings.load([input_file, overwrite], strict=False, key=CONFIG_KEY)


def get_cli_setting(key: str, filename: str | Path = DEFAULT_SETTINGS) -> typing.Any:
    """
    Get a setting from the config file.
    """
    key = convert_key(key)
    settings = load_cli_settings(filename)
    return getattr(settings, key)


def set_cli_setting(key: str, value: typing.Any, filename: str | Path = DEFAULT_SETTINGS) -> None:
    """
    Update a setting in the config file.
    """
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
