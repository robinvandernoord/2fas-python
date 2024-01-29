"""
This file contains the Typer CLI.
"""

import os
import sys
import typing

import questionary
import rich
import typer
from lib2fas._security import keyring_manager
from lib2fas._types import TwoFactorAuthDetails
from lib2fas.core import TwoFactorStorage, load_services

from .__about__ import __version__
from .cli_settings import (
    expand_path,
    get_cli_setting,
    load_cli_settings,
    set_cli_setting,
)
from .cli_support import (
    clear,
    exit_with_clear,
    generate_choices,
    generate_custom_style,
    state,
)

app = typer.Typer()

TwoFactorDetailStorage: typing.TypeAlias = TwoFactorStorage[TwoFactorAuthDetails]


def prepare_to_generate(filename: str = None) -> TwoFactorDetailStorage:
    """
    Clear old keyring entries (from previous sessions) and decrypt the selected 2fas file.
    """
    keyring_manager.cleanup_keyring()
    return load_services(filename or default_2fas_file())


def print_for_service(service: TwoFactorAuthDetails) -> None:
    """
    Print the name, current TOTP code and optionally username for a specific service.
    """
    service_name = service.name
    code = service.generate()

    if state.verbose:
        username = service.otp.account  # or .label ?
        rich.print(f"- {service_name} ({username}): {code}")
    else:
        rich.print(f"- {service_name}: {code}")


def generate_all_totp(services: TwoFactorDetailStorage) -> None:
    """
    Generate TOTP codes for all services.
    """
    for service in services:
        print_for_service(service)


def generate_one_otp(services: TwoFactorDetailStorage) -> None:
    """
    Query the user for a service, then generate a TOTP code for it.
    """
    service_name: str
    while service_name := questionary.autocomplete(
        "Choose a service", choices=services.keys(), style=generate_custom_style()
    ).ask():
        for service in services.find(service_name):
            print_for_service(service)


@clear
def show_service_info(services: TwoFactorDetailStorage, about: str) -> None:
    """
    `--info <service>` to show the raw JSON info for a service as stored in the .2fas file.
    """
    rich.print(services[about])


def show_service_info_interactive(services: TwoFactorDetailStorage) -> None:
    """
    Menu when choosing "Info about a Service".

    The raw JSON info for a service as stored in the .2fas file will be printed out.
    """
    about: str
    while about := questionary.select(
        "About which service?", choices=services.keys(), style=generate_custom_style()
    ).ask():
        show_service_info(services, about)
        if questionary.press_any_key_to_continue("Press 'Enter' to continue; Other keys to exit").ask() is None:
            exit_with_clear(0)


@clear
def command_interactive(filename: str = None) -> None:
    """
    Interactive menu when using 2fas without any action flags.
    """
    if not filename:
        # get from settings or
        filename = default_2fas_file()

    services = prepare_to_generate(filename)

    rich.print(f"Active file: [blue]{filename}[/blue]")

    match questionary.select(
        "What do you want to do?",
        choices=generate_choices(
            {
                "Generate a TOTP code": "generate-one",
                "Generate all TOTP codes": "generate-all",
                "Info about a Service": "see-info",
                "Settings": "settings",
            }
        ),
        use_shortcuts=True,
        style=generate_custom_style(),
    ).ask():
        case "generate-one":
            # query list of items
            return generate_one_otp(services)
        case "generate-all":
            # show all
            return generate_all_totp(services)
        case "see-info":
            return show_service_info_interactive(services)
        case "settings":
            return command_settings(filename)
        case _:
            exit_with_clear(0)


def add_2fas_file() -> str:
    """
    Query the user for a 2fas file and remember it for later.
    """
    settings = state.settings

    filename: str = questionary.path(
        "Path to .2fas file?",
        validate=lambda it: it.endswith(".2fas"),
        # file_filter=lambda it: it.endswith(".2fas"),
        style=generate_custom_style(),
    ).ask()

    if filename is None:
        return exit_with_clear(0)

    filename = expand_path(filename)

    settings.add_file(filename)
    return filename


def default_2fas_file() -> str:
    """
    Load the default 2fas file from settings or query the user for it.
    """
    settings = state.settings
    if settings.default_file:
        return settings.default_file

    elif settings.files:
        return settings.files[0]

    filename = add_2fas_file()
    set_cli_setting("default-file", filename)

    return expand_path(filename)


def default_2fas_services() -> TwoFactorDetailStorage:
    """
    Load the 2fas services from the active default file.
    """
    filename = default_2fas_file()
    return prepare_to_generate(filename)


def command_generate(filename: str | None, other_args: list[str]) -> None:
    """
    Handles the generation of OTP codes for the specified service(s) \
        or initiates an interactive menu if no services are specified.

    Args:
        filename: path to the active .2fas file
        other_args: list of services to generate codes for. If empty, an interactive menu will be shown.
    """
    storage = prepare_to_generate(filename)
    found: list[TwoFactorAuthDetails] = []

    if not other_args:
        # only .2fas file entered - switch to interactive
        return command_interactive(filename)

    for query in other_args:
        found.extend(storage.find(query))

    for twofa in found:
        print_for_service(twofa)


def get_setting(key: str) -> None:
    """
    `--setting key` to get a specifi setting's value.
    """
    value = get_cli_setting(key)
    rich.print(f"- {key}: {value}")


def set_setting(key: str, value: str) -> None:
    """
    `--setting key value` to update a setting.
    """
    set_cli_setting(key, value)


def list_settings() -> None:
    """
    Use --settings to show all current settings.
    """
    rich.print("Current settings:")
    for key, value in state.settings.__dict__.items():
        if key.startswith("_"):
            continue

        rich.print(f"- {key}: {value}")


@clear
def set_default_file_interactive(filename: str) -> None:
    """
    Interactive menu (after Settings) to set the default 2fas file.
    """
    new_filename = questionary.select(
        "Pick a file:",
        choices=state.settings.files or [],
        default=filename,
        style=generate_custom_style(),
        use_shortcuts=True,
    ).ask()

    if new_filename is None:
        return command_settings(filename)

    set_setting("default-file", new_filename)
    prepare_to_generate(new_filename)  # ask for passphrase

    return command_settings(new_filename)


@clear()
def command_manage_files(filename: str = None) -> None:
    """
    Interactive menu (after Settings) to manage known files.
    """
    to_remove = questionary.checkbox(
        "Which files do you want to remove?",
        choices=state.settings.files or [],
        style=generate_custom_style(),
    ).ask()
    if to_remove is not None:
        state.settings.remove_file(to_remove)

    if filename:
        return command_settings(filename)

    return None


@clear
def toggle_autoverbose(filename: str) -> None:
    """
    Interactive menu to manage the 'auto verbose' setting.
    """
    settings = state.settings

    is_enabled = "yes" if settings.auto_verbose else "no"
    color = "green" if settings.auto_verbose else "red"
    rich.print(f"[blue]Auto Verbose enabled:[/blue] [{color}]{is_enabled}[/{color}]")

    text_enabled = "Enable"
    new_value = (
        questionary.select(
            "Use Auto Verbose?",
            choices=[
                text_enabled,
                "Disable",
            ],
            style=generate_custom_style(),
        ).ask()
        == text_enabled
    )

    settings.auto_verbose = new_value
    state.verbose = new_value
    set_cli_setting("auto_verbose", new_value)
    return command_settings(filename)


@clear
def command_settings(filename: str) -> None:
    """
    Menu that shows up when you've chosen 'Settings' from the interactive menu.
    """
    rich.print(f"Active file: [blue]{filename}[/blue]")
    action = questionary.select(
        "What do you want to do?",
        choices=generate_choices(
            {
                "Show current settings": "show-settings",
                "Set default file": "set-default-file",
                "Add file": "add-file",
                "Remove files": "remove-files",
                "Toggle auto-verbose": "auto-verbose",
                "Back": "back",
            }
        ),
        use_shortcuts=True,
        style=generate_custom_style(),
    ).ask()

    match action:
        case "show-settings":
            return command_setting([])
        case "set-default-file":
            set_default_file_interactive(filename)
        case "add-file":
            prepare_to_generate(add_2fas_file())
            return command_settings(filename)
        case "remove-files":
            return command_manage_files(filename)
        case "back":
            return command_interactive(filename)
        case "auto-verbose":
            return toggle_autoverbose(filename)
        case _:
            exit_with_clear(1)


def command_setting(args: list[str]) -> None:
    """
    Triggered when using --setting, --settings, -s.

    Multiple options:
    --setting
    --setting key
    --setting key value, --setting key=value
    """
    # required until PyCharm understands 'match' better:
    keyvalue: str
    key: str
    value: str

    match args:
        case []:
            list_settings()
        case [keyvalue]:
            # key=value
            if "=" not in keyvalue:
                # get setting
                get_setting(keyvalue)
            else:
                # set settings
                set_setting(*keyvalue.split("=", 1))
        case [key, value]:
            set_setting(key, value)
        case other:
            raise ValueError(f"Can't set setting '{other}'.")


def command_update() -> None:
    """
    --self-update tries to update this library to the latest version on pypi.
    """
    python = sys.executable
    pip = f"{python} -m pip"
    cmd = f"{pip} install --upgrade 2fas"
    if os.system(cmd):  # nosec: B605
        rich.print("[red] could not self-update [/red]")
    else:
        rich.print("[green] 2fas is at the latest version [/green]")


def print_version() -> None:
    """
    --version prints the currently installed version of this library.
    """
    from lib2fas.__about__ import __version__ as core_version

    rich.print("CLI version: ", __version__)
    rich.print("lib2fas version: ", core_version)


@app.command()
def main(
    args: list[str] = typer.Argument(None),
    # mutually exclusive actions:
    setting: bool = typer.Option(
        False,
        "--setting",
        "--settings",
        "-s",
        help="Use `--setting` without an argument to see all settings. "
        "Use `--setting <name>` to see the current value of a setting. "
        "Use `--setting <name> <value>` to update a setting.",
    ),
    info: str = typer.Option(
        None, "--info", "-i", help="`--info <service>` show all known info about a TOTP service from your .2fas file."
    ),
    self_update: bool = typer.Option(
        False, "--self-update", "-u", help="Try to update the 2fas tool to the latest version."
    ),
    generate_all: bool = typer.Option(False, "--all", "-a", help="Generate all TOTP codes from the active file."),
    version: bool = typer.Option(False, "--version", help="Show the current version of the 2fas cli tool."),
    remove: bool = typer.Option(
        False, "--remove", "--rm", "-r", help="`--remove <filename>` to remove a .2fas file from the known files"
    ),
    # flags:
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show more details (e.g. the username for a TOTP service). "
        "You can use `auto-verbose` in settings to always show more info.",
    ),
) -> None:  # pragma: no cover
    """
    You can use this command in multiple ways.

    2fas

    2fas path/to/file.fas <service>

    2fas <service> path/to/file.fas

    2fas <subcommand>

    2fas --setting key value

    2fas --setting key=value
    """
    # stateless actions:
    if version:
        return print_version()
    elif self_update:
        return command_update()

    # stateful:

    settings = load_cli_settings()
    state.update(verbose=settings.auto_verbose or verbose, settings=settings)

    file_args = [_ for _ in args if _.endswith(".2fas")]
    if len(file_args) > 1:
        rich.print("[red]Err: can't work on multiple .2fas files![/red]", file=sys.stderr)
        exit(1)

    filename = expand_path(file_args[0] if file_args else default_2fas_file())
    settings.add_file(filename)

    other_args = [_ for _ in args if not _.endswith(".2fas")]

    if setting:
        command_setting(args)
    elif remove and file_args:
        settings.remove_file(file_args[0])
    elif remove:
        command_manage_files()
    elif info:
        services = prepare_to_generate(filename)
        show_service_info(services, about=info)
    elif generate_all:
        services = prepare_to_generate(filename)
        generate_all_totp(services)
    elif args:
        command_generate(filename, other_args)
    else:
        command_interactive(filename)
