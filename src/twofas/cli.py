import os
import sys
import typing

import questionary
import rich
import typer

from .__about__ import __version__
from ._security import keyring_manager
from ._types import TwoFactorAuthDetails
from .cli_settings import get_cli_setting, load_cli_settings, set_cli_setting
from .cli_support import clear, exit_with_clear, generate_custom_style, state
from .core import TwoFactorStorage, load_services

app = typer.Typer()

TwoFactorDetailStorage: typing.TypeAlias = TwoFactorStorage[TwoFactorAuthDetails]


def prepare_to_generate(filename: str = None) -> TwoFactorDetailStorage:
    keyring_manager.cleanup_keyring()
    return load_services(filename or default_2fas_file())


def print_for_service(service: TwoFactorAuthDetails) -> None:
    service_name = service.name
    code = service.generate()

    if state.verbose:
        username = service.otp.account  # or .label ?
        rich.print(f"- {service_name} ({username}): {code}")
    else:
        rich.print(f"- {service_name}: {code}")


def generate_all_totp(services: TwoFactorDetailStorage) -> None:
    for service in services:
        print_for_service(service)


def generate_one_otp(services: TwoFactorDetailStorage) -> None:
    while service_name := questionary.autocomplete(
        "Choose a service", choices=services.keys(), style=generate_custom_style()
    ).ask():
        for service in services.find(service_name):
            print_for_service(service)


@clear
def show_service_info(services: TwoFactorDetailStorage, about: str) -> None:
    rich.print(services[about])


def show_service_info_interactive(services: TwoFactorDetailStorage) -> None:
    while about := questionary.select(
        "About which service?", choices=services.keys(), style=generate_custom_style()
    ).ask():
        show_service_info(services, about)
        if questionary.press_any_key_to_continue("Press 'Enter' to continue; Other keys to exit").ask() is None:
            exit_with_clear(0)


@clear
def command_interactive(filename: str = None) -> None:
    if not filename:
        # get from settings or
        filename = default_2fas_file()

    services = prepare_to_generate(filename)

    rich.print(f"Active file: [blue]{filename}[/blue]")

    match questionary.select(
        "What do you want to do?",
        choices=[
            questionary.Choice("Generate a TOTP code", "generate-one", shortcut_key="1"),
            questionary.Choice("Generate all TOTP codes", "generate-all", shortcut_key="2"),
            questionary.Choice("Info about a Service", "see-info", shortcut_key="3"),
            questionary.Choice("Settings", "settings", shortcut_key="4"),
            questionary.Choice("Exit", "exit", shortcut_key="0"),
        ],
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
            # manage files
            # change specific settings
            # default file - choose from list of files
        case _:
            exit_with_clear(0)


def default_2fas_file() -> str:
    settings = state.settings
    if settings.default_file:
        return settings.default_file

    elif settings.files:
        return settings.files[0]

    filename: str = questionary.path(
        "Path to .2fas file?",
        validate=lambda it: it.endswith(".2fas"),
        # file_filter=lambda it: it.endswith(".2fas"),
        style=generate_custom_style(),
    ).ask()

    set_cli_setting("default-file", filename)
    settings.add_file(filename)

    return filename


def default_2fas_services() -> TwoFactorDetailStorage:
    filename = default_2fas_file()
    return prepare_to_generate(filename)


def command_generate(filename: str | None, other_args: list[str]) -> None:
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
    value = get_cli_setting(key)
    rich.print(f"- {key}: {value}")


def set_setting(key: str, value: str) -> None:
    set_cli_setting(key, value)


def list_settings() -> None:
    rich.print("Current settings:")
    for key, value in state.settings.__dict__.items():
        if key.startswith("_"):
            continue

        rich.print(f"- {key}: {value}")


@clear
def set_default_file_interactive(filename: str) -> None:
    new_filename = questionary.select(
        "Pick a file:",
        choices=state.settings.files or [],
        default=filename,
        style=generate_custom_style(),
        use_shortcuts=True,
    ).ask()

    set_setting("default-file", new_filename)
    prepare_to_generate(new_filename)  # ask for passphrase

    return command_settings(new_filename)


@clear
def command_settings(filename: str) -> None:
    rich.print(f"Active file: [blue]{filename}[/blue]")
    action = questionary.select(
        "What do you want to do?",
        choices=[
            questionary.Choice("Set default file", "set-default-file", shortcut_key="1"),
            questionary.Choice("Manage files", "manage-files", shortcut_key="2"),
            questionary.Choice("Back", "back", shortcut_key="3"),
            questionary.Choice("Exit", "exit", shortcut_key="0"),
        ],
        use_shortcuts=True,
        style=generate_custom_style(),
    ).ask()

    match action:
        case "set-default-file":
            set_default_file_interactive(filename)
        case "manage-files":
            print("todo: manage files")
        case "back":
            return command_interactive(filename)
        case _:
            exit_with_clear(1)


def command_setting(args: list[str]) -> None:
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
    python = sys.executable
    pip = f"{python} -m pip"
    cmd = f"{pip} install --upgrade 2fas"
    if os.system(cmd):  # nosec: B605
        rich.print("[red] could not self-update [/red]")
    else:
        rich.print("[green] 2fas is at the latest version [/green]")


def print_version() -> None:
    rich.print(__version__)


@app.command()
def main(
    args: list[str] = typer.Argument(None),
    # mutually exclusive actions:
    setting: bool = typer.Option(False, "--setting", "--settings", "-s"),
    info: str = typer.Option(None, "--info", "-i"),
    self_update: bool = typer.Option(False, "--self-update", "-u"),
    generate_all: bool = typer.Option(False, "--all", "-a"),
    version: bool = typer.Option(False, "--version"),
    # flags:
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:  # pragma: no cover
    """
    Cli entrypoint.
    """
    # 2fas

    # 2fas path/to/file.fas <service>
    # 2fas <service> path/to/file.fas
    # 2fas <subcommand>

    # 2fas --setting key value
    # 2fas --setting key=value

    # stateless actions:
    if version:
        return print_version()
    elif self_update:
        command_update()

    # stateful:

    settings = load_cli_settings()
    state.update(verbose=settings.auto_verbose or verbose, settings=settings)

    file_args = [_ for _ in args if _.endswith(".2fas")]
    if len(file_args) > 1:
        rich.print("[red]Err: can't work on multiple .2fas files![/red]", file=sys.stderr)
        exit(1)

    filename = file_args[0] if file_args else default_2fas_file()
    settings.add_file(filename)

    other_args = [_ for _ in args if not _.endswith(".2fas")]

    if setting:
        command_setting(args)
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

    # todo: something to --remove files from history
    # todo: better --help info
