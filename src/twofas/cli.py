"""
This file contains the Typer CLI.
"""

import getpass
import os
import sys
import typing
from pathlib import Path

import questionary
import rich
import typer
from lib2fas import TwoFactorAuthDetails, TwoFactorStorage, load_services
from rich.markup import escape

from . import yubikey
from .__about__ import __version__
from .cli_settings import (
    CONFIG_DIR,
    DEFAULT_SETTINGS,
    KEYS_DIR,
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

# 'yubikey' is the setting value (and works for any FIDO2 key, not only YubiKeys);
# "security key" is what it is called in the menus, where it needs to be self-explanatory.
METHOD_LABELS: dict[UnlockMethod, str] = {
    "password": "Passphrase",
    "yubikey": "Security key, with your passphrase as fallback",
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

    if services := prepare_to_generate(filename):
        rich.print(f"Active file: [blue]{filename}[/blue]")

    match questionary.select(
        "What do you want to do?",
        choices=generate_choices(
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
        use_shortcuts=True,
        style=generate_custom_style(),
    ).ask():
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
    if yubikey.fido2_available():
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
        authenticators = yubikey.describe_authenticators()
    except yubikey.YubiKeyError as e:
        rich.print(f"[red]{escape(str(e))}[/red]")
        rich.print("Run `2fas --doctor` to see what is wrong.")
        return

    if not any(_.supports_hmac_secret for _ in authenticators):
        rich.print("[red]No security key that supports hmac-secret is connected.[/red]")
        rich.print("Run `2fas --doctor` to see what is wrong.")
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
        rich.print("[blue]Your security key has a PIN, which CTAP2 requires to register a new credential.[/blue]")
        rich.print("[blue]You will not need it again for day-to-day unlocking.[/blue]")
        pin = getpass.getpass("Security key PIN? ") or None

    try:
        enroll(active_file, salt, unlocker.current_key, pin=pin)
    except yubikey.YubiKeyError as e:
        rich.print(f"[red]Setup failed: {escape(str(e))}[/red]")
        return

    set_cli_setting("unlock-method", "yubikey")
    rich.print(f"[green]Enrolled a security key for {active_file}.[/green]")
    rich.print(
        f"Unlock method is now [blue]yubikey[/blue] "
        f"([blue]{POLICY_HELP[parse_policy(get_cli_setting('yubikey-unlock-policy'), 'process')]}[/blue]). "
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

    if parse_method(get_cli_setting("unlock-method")) == "yubikey":
        set_cli_setting("unlock-method", "password")
        rich.print("Unlock method set back to [blue]password[/blue].")


def _hidraw_diagnosis() -> str:
    """
    Explain why no authenticator was visible, on Linux where that is usually udev.
    """
    if not sys.platform.startswith("linux"):
        return "no FIDO2 device found"

    nodes = sorted(Path("/dev").glob("hidraw*"))
    if not nodes:
        return "no /dev/hidraw* nodes at all - is your key actually plugged in?"

    unreadable = [str(_) for _ in nodes if not os.access(_, os.R_OK | os.W_OK)]
    if unreadable:
        return (
            f"{len(unreadable)} of {len(nodes)} /dev/hidraw* nodes are not readable/writable by you "
            "- this is the usual cause. Install the udev rules that ship with libfido2 "
            "(70-u2f.rules) and re-plug the key."
        )

    return f"{len(nodes)} /dev/hidraw* nodes are accessible, but none of them answered as a FIDO2 authenticator"


def command_doctor(filename: str) -> None:
    """
    `--doctor` to check whether security key unlocking can work on this machine.

    Everything here is read-only and needs no touch, so it is safe to run any time.
    """
    rich.print("[bold]2fas doctor[/bold]\n")

    settings = state.settings
    rich.print("[bold]Configuration[/bold]")
    rich.print(f"- config directory: {CONFIG_DIR}")
    rich.print(f"- settings file: {DEFAULT_SETTINGS}")
    rich.print(f"- wrapped keys: {KEYS_DIR}")
    method = parse_method(settings.unlock_method)
    password_policy = parse_policy(settings.password_unlock_policy, "os-session")
    yubikey_policy = parse_policy(settings.yubikey_unlock_policy, "process")
    rich.print(f"- unlock-method: [blue]{method}[/blue]")
    rich.print(f"- password-unlock-policy: [blue]{password_policy}[/blue] ({POLICY_HELP[password_policy]})")
    rich.print(f"- yubikey-unlock-policy: [blue]{yubikey_policy}[/blue] ({POLICY_HELP[yubikey_policy]})")

    rich.print("\n[bold]Security key[/bold]")
    if not yubikey.fido2_available():
        rich.print(
            f"- [yellow]fido2 not installed[/yellow] - security key unlocking is off. "
            f"Install it with: [bold]{escape(detect_install_plan().as_shell())}[/bold]"
        )
    else:
        try:
            authenticators = yubikey.describe_authenticators()
        except yubikey.YubiKeyError as e:
            authenticators = []
            rich.print(f"- [red]{escape(str(e))}[/red]")

        if not authenticators:
            rich.print(f"- [yellow]{_hidraw_diagnosis()}[/yellow]")
        for auth in authenticators:
            rich.print(f"- {auth.product} (firmware {auth.firmware})")
            hmac = "[green]yes[/green]" if auth.supports_hmac_secret else "[red]no[/red]"
            rich.print(f"  - hmac-secret: {hmac}")
            rich.print(f"  - PIN configured: {'yes' if auth.has_pin else 'no'} (only needed to enroll)")
            if auth.always_uv:
                rich.print(
                    "  - [yellow]alwaysUv is enabled on this key. That forces user verification, "
                    "which changes the hmac-secret output, so a key enrolled without it will stop "
                    "unwrapping. Your passphrase still works; re-enroll to fix it.[/yellow]"
                )

    rich.print("\n[bold]Enrolled vaults[/bold]")
    if not (enrolled := KeyStore().all()):
        rich.print("- none yet (run `2fas --setup-key`, or Settings > Unlocking & security key)")
    active_salt = vault_salt(filename)
    active_id = vault_id_for(active_salt) if active_salt else None
    for wrapped in enrolled:
        marker = " [green](active file)[/green]" if wrapped.vault_id == active_id else ""
        hint = wrapped.filename_hint or "unknown file"
        exists = "" if Path(wrapped.filename_hint or "").exists() else " [yellow](file not found)[/yellow]"
        rich.print(f"- {wrapped.vault_id[:12]}… {hint}{exists}{marker}")


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

    chosen = questionary.select(
        "How do you want to unlock your vault?",
        choices=generate_choices(
            {f"{label}{' (current)' if value == current else ''}": value for value, label in METHOD_LABELS.items()},
            with_exit=False,
            disabled=({} if is_set_up else {"yubikey": "Set up a security key for this file first"}),
        ),
        use_shortcuts=True,
        style=generate_custom_style(),
    ).ask()

    if chosen is not None:
        set_cli_setting("unlock-method", chosen)
        state.settings.unlock_method = chosen

    return command_security(filename)


@clear
def choose_unlock_policy(filename: str, method: UnlockMethod) -> None:
    """
    Menu for how often one of the two paths should ask for something.
    """
    setting = "yubikey-unlock-policy" if method == "yubikey" else "password-unlock-policy"
    default: UnlockPolicy = "process" if method == "yubikey" else "os-session"
    current = parse_policy(getattr(state.settings, setting.replace("-", "_")), default)

    # what a tighter policy actually costs you differs enormously between the two paths:
    # a touch is a second, a master passphrase is not.
    costs: dict[UnlockPolicy, str] = (
        {
            "os-session": "one touch per boot",
            "process": "one touch per run of 2fas (recommended)",
            "code": "one touch for every code",
        }
        if method == "yubikey"
        else {
            "os-session": "type it once per boot (recommended)",
            "process": "type it once per run of 2fas",
            "code": "type it for every single code - realistically unusable",
        }
    )

    rich.print(f"[blue]{setting}:[/blue] {current} ({POLICY_HELP[current]})")
    labels = {f"{policy}: {cost}": policy for policy, cost in costs.items()}
    chosen = questionary.select(
        "How often should 2fas ask?",
        choices=list(labels),
        default=next(label for label, value in labels.items() if value == current),
        style=generate_custom_style(),
    ).ask()

    if chosen is not None:
        set_cli_setting(setting, labels[chosen])
        setattr(state.settings, setting.replace("-", "_"), labels[chosen])

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

    rich.print(f"Active file: [blue]{filename}[/blue]")
    rich.print(f"Unlock method: [blue]{METHOD_LABELS[method]}[/blue]")
    if is_set_up:
        rich.print("Security key: [green]set up for this file[/green]")
    else:
        rich.print("Security key: [yellow]not set up for this file[/yellow]")
    rich.print("")

    setup_label = (
        "Remove the security key for this file" if is_set_up else "Set up a security key for this file (YubiKey)"
    )
    needs_key = {} if is_set_up else {"touch-policy": "Set up a security key for this file first"}

    action = questionary.select(
        "What do you want to do?",
        choices=generate_choices(
            {
                setup_label: "setup-key",
                "Change unlock method (passphrase / security key)": "unlock-method",
                "How often to ask for my passphrase": "password-policy",
                "How often to touch my security key": "touch-policy",
                "Check my security key setup (doctor)": "doctor",
                "Back": "back",
            },
            disabled=needs_key,
        ),
        use_shortcuts=True,
        style=generate_custom_style(),
    ).ask()

    match action:
        case "setup-key":
            command_forget_key(filename) if is_set_up else command_enroll(filename)
            _pause()
        case "unlock-method":
            return choose_unlock_method(filename)
        case "password-policy":
            return choose_unlock_policy(filename, "password")
        case "touch-policy":
            return choose_unlock_policy(filename, "yubikey")
        case "doctor":
            command_doctor(filename)
            _pause()
        case "back":
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
    action = questionary.select(
        "What do you want to do?",
        choices=generate_choices(
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
    doctor: bool = typer.Option(
        False, "--doctor", help="Check whether unlocking with a security key can work on this machine."
    ),
    enroll_key: bool = typer.Option(
        False,
        "--setup-key",
        "--enroll",
        help="Set up a security key (YubiKey) to unlock the active .2fas file. "
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

    if doctor:
        return command_doctor(filename)
    elif enroll_key:
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
