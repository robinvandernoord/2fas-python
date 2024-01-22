import sys
import typing

import configuraptor
import questionary
import rich
import typer

from ._security import keyring_manager
from ._types import TwoFactorAuthDetails
from .cli_settings import get_cli_setting, load_cli_settings, set_cli_setting
from .core import TwoFactorStorage, load_services

app = typer.Typer()

TwoFactorDetailStorage: typing.TypeAlias = TwoFactorStorage[TwoFactorAuthDetails]


class AppState(configuraptor.TypedConfig, configuraptor.Singleton):
    verbose: bool = False


state = AppState.load({})


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


def prepare_to_generate(filename: str) -> TwoFactorDetailStorage:
    keyring_manager.cleanup_keyring()
    return load_services(filename)


def generate_all_totp(services: TwoFactorDetailStorage) -> None:
    print("verbose", state.verbose)

    for service_name, code in services.generate():
        rich.print(f"- {service_name}: {code}")


def generate_one_otp(services: TwoFactorDetailStorage) -> None:
    print("verbose", state.verbose)

    while service_name := questionary.autocomplete(
        "Choose a service", choices=services.keys(), style=generate_custom_style()
    ).ask():
        for service_name, code in services.find(service_name).generate():
            rich.print(f"- {service_name}: {code}")


def command_interactive(filename: str = None) -> None:
    if not filename:
        # get from settings or
        filename = default_2fas_file()

    services = prepare_to_generate(filename)

    match questionary.select(
        "What do you want to do?",
        choices=[
            questionary.Choice("Generate a TOTP", "generate-one", shortcut_key="1"),
            questionary.Choice("Generate all TOTPs", "generate-all", shortcut_key="2"),
            questionary.Choice("Settings", "settings", shortcut_key="3"),
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
        case "settings":
            print("todo: settings")
            # manage files
            # change specific settings
            # default file - choose from list of files
        case _:
            exit(0)


def default_2fas_file() -> str:
    print("todo: query filename or get from settings")
    return "~/Nextcloud/2fa/2fas-backup-20240117132052.2fas"


def default_2fas_services() -> TwoFactorDetailStorage:
    filename = default_2fas_file()
    return prepare_to_generate(filename)


def command_generate(args: list[str]) -> None:
    file_args = [_ for _ in args if _.endswith(".2fas")]
    if len(file_args) > 1:
        rich.print("[red]Err: can't work on multiple .2fas files![/red]", file=sys.stderr)
        exit(1)

    filename = file_args[0] if file_args else default_2fas_file()
    print(f"todo: store {filename} in ~/.config/2fas settings")
    print("todo: possibly set default in settings? ")

    other_args = [_ for _ in args if not _.endswith(".2fas")]

    storage = prepare_to_generate(filename)
    found: list[TwoFactorAuthDetails] = []

    if not other_args:
        # only .2fas file entered - switch to interactive
        return command_interactive(filename)

    for query in other_args:
        found.extend(storage.find(query))

    for twofa in found:
        rich.print(f"- {twofa.name}:", twofa.generate())


def get_setting(key: str) -> None:
    value = get_cli_setting(key)
    rich.print(f"- {key}: {value}")


def set_setting(key: str, value: str) -> None:
    set_cli_setting(key, value)


def list_settings() -> None:
    settings = load_cli_settings()
    rich.print("Current settings:")
    for key, value in settings.__dict__.items():
        if key.startswith("_"):
            continue

        rich.print(f"- {key}: {value}")


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


@app.command()
def main(
    args: list[str] = typer.Argument(None),
    setting: bool = typer.Option(False, "--setting", "--settings", "-s"),
    generate_all: bool = typer.Option(False, "--all", "-a"),
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
    if verbose:
        state.update(verbose=verbose)

    if setting:
        command_setting(args)
    elif generate_all:
        # todo: look for .2fas file in 'args' !
        services = default_2fas_services()
        generate_all_totp(services)
    elif args:
        command_generate(args)
    else:
        command_interactive()

    # todo: something like --add and --remove files
    # todo: better --help info
