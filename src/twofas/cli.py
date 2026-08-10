"""
This file contains the Typer CLI.
"""

import os
import sys
import typing
from pathlib import Path

import questionary
import rich
import typer
from lib2fas import TwoFactorAuthDetails, TwoFactorStorage, load_services
from rich.markup import escape

from . import security_key
from .__about__ import __version__
from .cli_settings import (
    expand_path,
    get_cli_setting,
    load_cli_settings,
    set_cli_setting,
)
from .cli_support import (
    ask,
    clear,
    exit_with_clear,
    generate_choices,
    generate_custom_style,
    menu,
    state,
)
from . import install
from .install import detect_install_plan, run_install
from .keystore import KeyStore, vault_id_for
from .unlock import (
    POLICY_HELP,
    PolicyUnlocker,
    UnlockMethod,
    UnlockPolicy,
    enroll,
    parse_method,
    parse_policy,
    prune_keystore,
    vault_salt,
)

app = typer.Typer()

TwoFactorDetailStorage: typing.TypeAlias = TwoFactorStorage[TwoFactorAuthDetails]

# 'security-key' is the setting value (and works for any FIDO2 key, not only YubiKeys);
# "security key" is what it is called in the menus, where it needs to be self-explanatory.
METHOD_LABELS: dict[UnlockMethod, str] = {
    "password": "Passphrase",
    "security-key": "Security key, with your passphrase as fallback",
}

_unlocker: PolicyUnlocker | None = None


def get_unlocker(force_password: bool = False) -> PolicyUnlocker:
    """
    The unlocker for this invocation, built once from the user's settings.

    It is a single instance on purpose: it remembers which path actually unlocked the
    vault, which is what the per-code policy follows.
    """
    global _unlocker  # one unlocker per invocation, by design

    if _unlocker is None:
        _unlocker = PolicyUnlocker.from_settings(state.settings, force_password=force_password)

    return _unlocker


def prepare_to_generate(filename: str = None) -> TwoFactorDetailStorage | None:
    """
    Clear stale unlock state (from previous sessions) and decrypt the selected 2fas file.
    """
    unlocker = get_unlocker()
    unlocker.cleanup()
    prune_keystore(unlocker.store, state.settings.files or [])

    filepath = filename or default_2fas_file()
    if not (services := load_services(filepath, unlocker=unlocker)):
        rich.print(f"[red]Error: {filepath} does not exit![/red]")
    return services


def print_for_service(service: TwoFactorAuthDetails) -> None:
    """
    Print the name, current TOTP code and optionally username for a specific service.
    """
    service_name = service.name
    code = service.generate()

    if state.verbose and service.otp:
        username = service.otp.account  # or .label ?
        rich.print(f"- {service_name} ({username}): {code}")
    else:
        rich.print(f"- {service_name}: {code}")


def confirm_presence() -> bool:
    """
    Run the per-code check, if the active unlock policy asks for one.

    Called once per user-visible action rather than once per printed line: under `--all`
    that is one check for the whole batch, and in the interactive menu it is one check per
    service you pick. Otherwise the `code` policy would mean a touch per service in your
    vault, which nobody wants.
    """
    return get_unlocker().confirm()


def generate_all_totp(services: TwoFactorDetailStorage) -> None:
    """
    Generate TOTP codes for all services.
    """
    if not confirm_presence():
        return

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
        if not confirm_presence():
            continue

        for service in services.find(service_name):
            print_for_service(service)


@clear
def show_service_info(services: TwoFactorDetailStorage, about: str) -> None:
    """
    `--info <service>` to show the raw JSON info for a service as stored in the .2fas file.
    """
    # this prints the raw entry, secret included, so it gets the same gate as a code:
    if not confirm_presence():
        return

    rich.print(services[about])


def show_service_info_interactive(services: TwoFactorDetailStorage) -> None:
    """
    Menu when choosing "Info about a Service".

    The raw JSON info for a service as stored in the .2fas file will be printed out.
    """
    about: str
    names = services.keys()  # a TwoFactorStorage method, not a dict view
    while about := menu("About which service?", generate_choices({_: _ for _ in names}, with_exit=False)):
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

    if services := prepare_to_generate(filename):
        rich.print(f"Active file: [blue]{filename}[/blue]")

    match menu(
        "What do you want to do?",
        generate_choices(
            {
                "Generate a TOTP code": "generate-one",
                "Generate all TOTP codes": "generate-all",
                "Info about a Service": "see-info",
                "Settings": "settings",
            },
            disabled=(
                {
                    # you may only change settings if loading services failed
                    "generate-one": "Disabled when services failed to load",
                    "generate-all": "Disabled when services failed to load",
                    "see-info": "Disabled when services failed to load",
                }
                if services is None
                else {}
            ),
        ),
    ):
        case "generate-one":
            # query list of items
            assert services, "If services is None, this selection branch should be disabled in `generate_choices`."
            return generate_one_otp(services)
        case "generate-all":
            # show all
            assert services, "If services is None, this selection branch should be disabled in `generate_choices`."
            return generate_all_totp(services)
        case "see-info":
            assert services, "If services is None, this selection branch should be disabled in `generate_choices`."
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


def default_2fas_services() -> TwoFactorDetailStorage | None:
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
    if not (storage := prepare_to_generate(filename)):
        # nothing to do
        return

    found: list[TwoFactorAuthDetails] = []

    if not other_args:
        # only .2fas file entered - switch to interactive
        return command_interactive(filename)

    for query in other_args:
        found.extend(storage.find(query))

    if not confirm_presence():
        return

    for twofa in found:
        print_for_service(twofa)


def is_security_key_set_up(filename: str, store: KeyStore = None) -> bool:
    """
    Whether the active file already has a security key set up.

    This is what gates the menu: offering "unlock with a security key" before one exists
    would set a method that silently falls back to the passphrase on every single run.

    Args:
        filename: the active .2fas file.
        store: where wrapped keys live; overridable for tests.
    """
    if not (salt := vault_salt(filename)):
        return False

    store = store if store is not None else KeyStore()
    return store.get(vault_id_for(salt)) is not None


def ensure_fido2(interactive: bool = True) -> bool:
    """
    Make sure the optional `fido2` package is available, offering to install it.

    Which command that is depends on how 2fas itself was installed (uv tool, pipx, a plain
    venv), so it is worked out rather than guessed at. Installing into someone's
    environment is not something to do behind their back, so it always asks first, and
    outside a terminal it only prints the command.
    """
    if security_key.fido2_available():
        return True

    plan = detect_install_plan()
    rich.print(
        "[yellow]Security key support needs one extra Python package: "
        f"[bold]{install.EXTRA_PACKAGE}[/bold].[/yellow]"
    )
    rich.print(f"Detected a [blue]{plan.manager}[/blue] installation, so the command for you is:")
    rich.print(f"  [bold]{escape(plan.as_shell())}[/bold]")

    if not (interactive and sys.stdin.isatty()):
        rich.print(f"Run that, or `{escape(install.EXTRA_NAME)}` in your own way, and try again.")
        return False

    if not questionary.confirm(
        f"Install {install.EXTRA_PACKAGE} now with {plan.manager}?", default=False, style=generate_custom_style()
    ).ask():
        rich.print("Nothing installed.")
        return False

    if run_install(plan):
        rich.print(f"[green]{install.EXTRA_PACKAGE} installed.[/green]")
        return True

    rich.print(f"[red]That did not work. Try `{escape(plan.as_shell())}` by hand.[/red]")
    return False


def command_enroll(filename: str) -> None:
    """
    `--setup-key` to let your security key unlock the active vault from now on.

    Unlocks with your passphrase first, because that is the only way to get the key that
    gets wrapped. Your .2fas file is not touched, re-encrypted, or rewritten in any way;
    all this adds is an encrypted copy of the vault key in ~/.config/2fas/keys.
    """
    if not ensure_fido2():
        return

    # look at the hardware before asking for a passphrase, so a key that is not plugged
    # in costs the user nothing.
    try:
        authenticators = security_key.describe_authenticators()
    except security_key.SecurityKeyError as e:
        rich.print(f"[red]{escape(str(e))}[/red]")
        print_security_key_status()
        return

    if not any(_.supports_hmac_secret for _ in authenticators):
        rich.print("[red]No usable security key is connected.[/red]")
        print_security_key_status()
        return

    # enrolling wraps the key the *passphrase* produces, so the security key path is
    # skipped here even when it would have worked.
    unlocker = get_unlocker()
    unlocker.force_password = True

    if not prepare_to_generate(filename):
        return

    vault = unlocker.vault()
    if vault is None or unlocker.current_key is None:  # pragma: no cover
        rich.print("[red]Nothing to enroll: this file is not encrypted.[/red]")
        return

    active_file, salt, _ = vault

    pin = None
    if any(_.has_pin for _ in authenticators):
        # CTAP2 requires the PIN to *create* a credential whenever one is set,
        # even though the unlocks afterwards will only need a touch.
        rich.print(
            "[blue]Your key has a PIN, which CTAP2 needs to register a credential. Not needed after this.[/blue]"
        )
        # questionary rather than getpass, so the user gets * per character instead of a
        # dead-looking prompt.
        pin = ask(questionary.password("Security key PIN?", style=generate_custom_style())) or None

    # two touches, and it is worth saying so: one creates the credential, one reads the
    # secret it derives. Every unlock afterwards is a single touch.
    rich.print("[blue]Setup needs two touches; unlocking later needs one.[/blue]")

    try:
        enroll(active_file, salt, unlocker.current_key, pin=pin)
    except security_key.SecurityKeyError as e:
        rich.print(f"[red]Setup failed: {escape(str(e))}[/red]")
        return

    set_cli_setting("unlock-method", "security-key")
    rich.print(f"[green]Your security key can now unlock {active_file}.[/green]")
    rich.print(
        f"Unlock method is now [blue]security-key[/blue] "
        f"([blue]{POLICY_HELP[parse_policy(get_cli_setting('security-key-unlock-policy'), 'process')]}[/blue]). "
        "Your passphrase keeps working, and `2fas --password` skips the key for one run."
    )


def command_forget_key(filename: str) -> None:
    """
    `--forget-key` to remove the security key enrolment for the active vault.

    Only removes our stored blob. Nothing was ever written to the key itself, so there is
    nothing to clean up there.
    """
    if not (salt := vault_salt(filename)):
        rich.print(f"[red]Could not read a salt from {filename}; is it an encrypted .2fas file?[/red]")
        return

    if KeyStore().delete(vault_id_for(salt)):
        rich.print(f"[green]Removed the security key enrolment for {filename}.[/green]")
    else:
        rich.print(f"[yellow]No security key was enrolled for {filename}.[/yellow]")

    if parse_method(get_cli_setting("unlock-method")) == "security-key":
        set_cli_setting("unlock-method", "password")
        rich.print("Unlock method set back to [blue]password[/blue].")


def _hidraw_diagnosis() -> str:
    """
    Say in one clause why no authenticator was visible.

    On Linux the answer is almost always udev, so that case names the fix; the others just
    say what is true and leave it there.
    """
    if not sys.platform.startswith("linux"):
        return "none found"

    nodes = sorted(Path("/dev").glob("hidraw*"))
    if not nodes:
        return "none plugged in"

    if any(not os.access(_, os.R_OK | os.W_OK) for _ in nodes):
        return "no access to /dev/hidraw* - install libfido2's udev rules, then re-plug"

    return "nothing plugged in answered as a FIDO2 key"


def print_security_key_status() -> None:
    """
    Say what 2fas can see of your security key, in one short block.

    This lives in the setup screen rather than behind its own command: the only moment
    anyone wants to know their firmware version or whether udev is in the way is the moment
    setting up or unlocking did not work.
    """
    if not security_key.fido2_available():
        rich.print(
            "Connected key:  [yellow]unknown[/yellow] - the fido2 package is not installed "
            f"([bold]{escape(detect_install_plan().as_shell())}[/bold])"
        )
        return

    try:
        authenticators = security_key.describe_authenticators()
    except security_key.SecurityKeyError as e:
        rich.print(f"Connected key:  [red]{escape(str(e))}[/red]")
        return

    usable = [_ for _ in authenticators if _.supports_hmac_secret]
    if not authenticators:
        rich.print(f"Connected key:  [yellow]none[/yellow] - {_hidraw_diagnosis()}")
        return

    for auth in authenticators:
        if not auth.supports_hmac_secret:
            rich.print(f"Connected key:  [red]{auth.product} does not support hmac-secret[/red]")
            continue

        pin = ", has a PIN (only needed during setup)" if auth.has_pin else ""
        rich.print(f"Connected key:  [green]{auth.product}[/green] (firmware {auth.firmware}{pin})")
        if auth.always_uv:
            rich.print(
                "                [yellow]alwaysUv is enabled on this key. That forces user "
                "verification, which changes the hmac-secret output, so a key set up without it "
                "stops working. Your passphrase still works; run setup again to fix it.[/yellow]"
            )

    if not usable:
        rich.print("                [yellow]Nothing connected can be used to unlock your vault.[/yellow]")


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
    files = state.settings.files or []
    new_filename = menu("Pick a file:", generate_choices({_: _ for _ in files}, with_exit=False), current=filename)

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

    chosen = menu(
        "Use Auto Verbose?",
        generate_choices({"Enable": True, "Disable": False}, with_exit=False),
        current=settings.auto_verbose,
    )
    if chosen is None:
        return command_settings(filename)

    new_value = bool(chosen)
    settings.auto_verbose = new_value
    state.verbose = new_value
    set_cli_setting("auto_verbose", new_value)
    return command_settings(filename)


@clear
def choose_unlock_method(filename: str) -> None:
    """
    Menu to switch between passphrase and security key unlocking.

    Picking the security key is only possible once one is actually set up for this file;
    otherwise the option is shown greyed out with the reason, rather than letting the user
    select a method that would silently fall back to the passphrase on every run.
    """
    current = parse_method(state.settings.unlock_method)
    is_set_up = is_security_key_set_up(filename)

    rich.print(f"[blue]Unlock method:[/blue] {METHOD_LABELS[current]} ([dim]{current}[/dim])")
    rich.print(
        "Your .2fas file stays passphrase-encrypted either way, so your passphrase always "
        "keeps working and you can not lock yourself out."
    )

    chosen = menu(
        "How do you want to unlock your vault?",
        generate_choices(
            {f"{label}{' (current)' if value == current else ''}": value for value, label in METHOD_LABELS.items()},
            with_exit=False,
            disabled=({} if is_set_up else {"security-key": "Set up a security key for this file first"}),
        ),
        current=current,
    )

    if (method := parse_method(chosen, current)) != current:
        set_cli_setting("unlock-method", method)
        state.settings.unlock_method = method

    return command_security(filename)


@clear
def choose_unlock_policy(filename: str, method: UnlockMethod) -> None:
    """
    Menu for how often one of the two paths should ask for something.
    """
    setting = "security-key-unlock-policy" if method == "security-key" else "password-unlock-policy"
    default: UnlockPolicy = "process" if method == "security-key" else "os-session"
    current = parse_policy(getattr(state.settings, setting.replace("-", "_")), default)

    # what a tighter policy actually costs you differs enormously between the two paths:
    # a touch is a second, a master passphrase is not.
    costs: dict[UnlockPolicy, str] = (
        {
            "os-session": "one touch per boot",
            "process": "one touch per run of 2fas (recommended)",
            "code": "one touch for every code",
        }
        if method == "security-key"
        else {
            "os-session": "type it once per boot (recommended)",
            "process": "type it once per run of 2fas",
            "code": "type it for every single code - realistically unusable",
        }
    )

    rich.print(f"[blue]{setting}:[/blue] {current} ({POLICY_HELP[current]})")

    # label -> value, so questionary hands back the value and nothing has to map a display
    # string back to a setting. Indexing a dict with whatever came out of the prompt is how
    # this screen used to crash with KeyError.
    chosen = menu(
        "How often should 2fas ask?",
        generate_choices(
            {f"{policy}: {cost}{' (current)' if policy == current else ''}": policy for policy, cost in costs.items()},
            with_exit=False,
        ),
        current=current,
    )

    if (policy := parse_policy(chosen, current)) != current:
        set_cli_setting(setting, policy)
        setattr(state.settings, setting.replace("-", "_"), policy)

    return command_security(filename)


def _pause() -> None:
    questionary.press_any_key_to_continue().ask()


@clear
def command_security(filename: str) -> None:
    """
    Everything about unlocking, in one place under Settings.

    Grouped rather than spread across the main settings menu, because these four options
    only make sense in relation to each other: which method, how often each method asks,
    and whether a security key exists at all.
    """
    method = parse_method(state.settings.unlock_method)
    is_set_up = is_security_key_set_up(filename)

    password_policy = parse_policy(state.settings.password_unlock_policy, "os-session")
    security_key_policy = parse_policy(state.settings.security_key_unlock_policy, "process")

    rich.print(f"Active file:    [blue]{filename}[/blue]")
    rich.print(f"Unlock method:  [blue]{METHOD_LABELS[method]}[/blue]")
    if is_set_up:
        rich.print("Security key:   [green]set up for this file[/green]")
    else:
        rich.print("Security key:   [yellow]not set up for this file[/yellow]")
    rich.print(f"Asks you:       passphrase {POLICY_HELP[password_policy]}, touch {POLICY_HELP[security_key_policy]}")
    print_security_key_status()
    rich.print("")

    setup_label = (
        "Remove the security key for this file"
        if is_set_up
        else "Set up a security key for this file (YubiKey, SoloKey, ...)"
    )
    needs_key = {} if is_set_up else {"touch-policy": "Set up a security key for this file first"}

    action = menu(
        "What do you want to do?",
        generate_choices(
            {
                setup_label: "setup-key",
                "Change unlock method (passphrase / security key)": "unlock-method",
                "How often to ask for my passphrase": "password-policy",
                "How often to touch my security key": "touch-policy",
                "Back": "back",
            },
            disabled=needs_key,
        ),
    )

    match action:
        case "setup-key":
            command_forget_key(filename) if is_set_up else command_enroll(filename)
            _pause()
        case "unlock-method":
            return choose_unlock_method(filename)
        case "password-policy":
            return choose_unlock_policy(filename, "password")
        case "touch-policy":
            return choose_unlock_policy(filename, "security-key")
        case "back" | None:
            return command_settings(filename)
        case _:
            exit_with_clear(1)

    return command_security(filename)


@clear
def command_settings(filename: str) -> None:
    """
    Menu that shows up when you've chosen 'Settings' from the interactive menu.
    """
    rich.print(f"Active file: [blue]{filename}[/blue]")
    action = menu(
        "What do you want to do?",
        generate_choices(
            {
                "Show current settings": "show-settings",
                "Set default file": "set-default-file",
                "Add file": "add-file",
                "Remove files": "remove-files",
                "Toggle auto-verbose": "auto-verbose",
                "Unlocking & security key": "security",
                "Back": "back",
            }
        ),
    )

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
        case "back" | None:
            return command_interactive(filename)
        case "auto-verbose":
            return toggle_autoverbose(filename)
        case "security":
            return command_security(filename)
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
    enroll_key: bool = typer.Option(
        False,
        "--setup-key",
        "--enroll",
        help="Set up a FIDO2 security key (YubiKey, SoloKey, ...) to unlock the active .2fas file. "
        "Asks for your passphrase once and never modifies the .2fas file.",
    ),
    forget_key: bool = typer.Option(
        False, "--forget-key", help="Remove the security key setup for the active .2fas file."
    ),
    # flags:
    password: bool = typer.Option(
        False,
        "--password",
        "-p",
        help="Skip the security key for this run and use your passphrase. "
        "Always available; you can not lock yourself out.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show more details (e.g. the username for a TOTP service). "
        "You can use `auto-verbose` in settings to always show more info.",
    ),
    # menu items:
    step_one: bool = typer.Option(False, "-1", help="Menu Option 1: Generate a TOTP code"),
    step_two: bool = typer.Option(False, "-2", help="Menu Option 2: Generate all TOTP codes"),
    step_three: bool = typer.Option(False, "-3", help="Menu Option 3: Show service info"),
    step_four: bool = typer.Option(False, "-4", help="Menu Option 4: Modify settings"),
) -> None:  # pragma: no cover
    """
    You can use this command in multiple ways.

    2fas

    2fas path/to/file.fas <service>

    2fas <service> path/to/file.fas

    2fas <subcommand>

    2fas --setting key value

    2fas --setting key=value

    Skip the interactive menu:
    2fas -1 (or -2, -3, -4)
    """
    # stateless actions:
    if version:
        return print_version()
    elif self_update:
        return command_update()

    args = args or []

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

    # build the unlocker before anything can decrypt, so `--password` is respected:
    get_unlocker(force_password=password)

    if enroll_key:
        return command_enroll(filename)
    elif forget_key:
        return command_forget_key(filename)

    # if -1, -2, -3 or -4 is passed, skip the interactive menu and go to that function:
    if any((step_one, step_two, step_three, step_four)):
        if not (services := prepare_to_generate(filename)):
            print("Can not shortcut menu it there are no services.", file=sys.stderr)
            return None
        if step_one:
            generate_one_otp(services)
        if step_two:
            generate_all_totp(services)
        if step_three:
            show_service_info_interactive(services)
        if step_four:
            command_settings(filename)
        return None

    if setting:
        command_setting(args)
    elif remove and file_args:
        settings.remove_file(file_args[0])
    elif remove:
        command_manage_files(filename)
    elif info:
        if services := prepare_to_generate(filename):
            show_service_info(services, about=info)
    elif generate_all:
        if services := prepare_to_generate(filename):
            generate_all_totp(services)
    elif args:
        command_generate(filename, other_args)
    else:
        command_interactive(filename)

    return None
