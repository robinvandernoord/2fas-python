# 2fas Python

2fas-python is an unofficial implementation
of [2FAS - the Internet’s favorite open-source two-factor authenticator](https://2fas.com).
It consists of a core library in Python and a CLI tool.

## Installation

To install this project, use pip or pipx:

```bash
pip install 2fas
# or:
pipx install 2fas
```

## Usage

To see all available options, you can run:

```bash
2fas --help
```

If you simply run `2fas` or `2fas /path/to/file.2fas`, an interactive menu will show up.
If you only want a specific TOTP code, you can run `2fas <service>` or `2fas /path/to/file.2fas <service>`.
Multiple services can be specified: `2fas <service1> <service2> [/path/to/file.2fas]`.
Fuzzy matching is applied to (hopefully) catch some typo's.
You can run `2fas --all` to generate codes for all TOTP in your `.2fas` file.

### Settings

```bash
# see all settings:
2fas --settings # shortcut: -s
# see a specific setting:
2fas --setting key
# update a setting:
2fas --setting key value
```

The `--settings`, `--setting` or `-s` flag can be used to read/write settings.
This can also be done from within the interactive menu.
`2fas` cli settings are stored in `~/.config/2fas/2fas.toml` and contain the following settings:

```toml
[tool.2fas]
files = [
    "/some/path/to/file.2fas",
    ... # list of known files, used by 'set default file' in the settings menu
]
default_file = "/some/path/to/file.2fas" # which file to use when no .2fas file was explicitly passed?
auto_verbose = true # run every command as if --verbose was passed?

unlock_method = "password" # or "security-key"
password_unlock_policy = "os-session" # how often to ask for your passphrase
security_key_unlock_policy = "process" # how often to ask for a touch

```

If you still have a settings file at the old location (`~/.config/2fas.toml`), it is moved
into the new directory the first time you run `2fas`. The directory also holds
`keys/`, used by the security key support below.

## Unlocking your vault

Your `.2fas` file is encrypted with a key derived from your passphrase (PBKDF2-HMAC-SHA256,
10 000 iterations - that number is fixed by the 2FAS file format, so a strong passphrase is
what actually protects the file). `2fas` never writes to your `.2fas` file; it only ever
reads it.

Two settings control unlocking, and they are separate on purpose.

**`unlock-method`** is how you unlock: `password` (the default) or `security-key`.

**`password-unlock-policy`** and **`security-key-unlock-policy`** are how often you are asked:

| policy       | passphrase path                     | security key path   |
|--------------|-------------------------------------|---------------------|
| `os-session` | type it once per boot *(default)*   | one touch per boot  |
| `process`    | type it once per run of `2fas`      | one touch per run *(default)* |
| `code`       | type it for every single code       | one touch per code  |

They are two settings because a tighter policy does not cost the same on both paths: on the
security key it is a one-second touch, on the passphrase path it is your full master
passphrase. Most people will want to leave the passphrase on `os-session`.

The policy follows the path you actually took, not the method you configured. If your key
is not plugged in and you fall back to your passphrase, the passphrase policy governs the
rest of that session - a passphrase you typed because the key was missing is not then
demanded again for every code.

`--all` is always one unlock per invocation, never one per service.

What gets cached is the derived key, never your passphrase, so a stolen cache does not
reveal a password you may have reused elsewhere. Under `os-session` the cached key lives in
your login keyring under a service name that is regenerated every boot; that is a
forget-on-reboot mechanism, not an access-control one - while your login keyring is
unlocked, any process running as you can read it.

### Unlocking with a security key

Works with any FIDO2 authenticator that implements the `hmac-secret` extension - a YubiKey,
SoloKey, Nitrokey, Token2, and most keys made since about 2018. Nothing here is
vendor-specific.

```bash
2fas --setup-key         # sets it up: offers to install what is missing, then two touches
2fas                     # from now on: one touch, no passphrase
2fas --password          # skip the key for one run
2fas --forget-key        # remove the security key setup for the active file
```

The same options live under **Settings > Unlocking & security key** in the interactive
menu, grouped together because they only make sense in relation to each other. That screen
also reports what 2fas can see of your key - product, firmware, whether hmac-secret is
supported, and on Linux whether udev is in the way - so there is no separate diagnostics
command to remember.

Choosing "security key" as your unlock method is greyed out until one is actually set up for the
active file - otherwise you would be picking a method that silently falls back to your
passphrase on every run.

Security key support needs one extra Python package, `fido2`. You do not have to work out
how to install it: `2fas --setup-key` detects how 2fas itself was installed (uv tool, pipx,
a plain venv) and offers to run the right command, preferring `uv` when it is available. It
always asks first and never installs anything behind your back. If you would rather do it
yourself:

```bash
uv tool install --with fido2 2fas   # if you installed 2fas as a uv tool
pipx inject 2fas fido2             # if you used pipx
uv pip install fido2               # or pip install fido2, in a plain venv
```

**The key replaces your passphrase, it is not a second factor.** Setting one up does not
re-encrypt your `.2fas` file; it stores an extra copy of the vault key, encrypted under a
secret only your security key can produce, in `~/.config/2fas/keys/`. Your file stays
passphrase-encrypted, which has two consequences worth being explicit about:

- **you can not lock yourself out.** Lost key, dead key, forgotten to bring it - your
  passphrase always still works, and `--password` skips the key deliberately.
- **your effective strength is the weaker of the two paths**, which is your passphrase.
  Adding a security key buys you convenience and protection of the *cache*, not a stronger vault.
  If you want a stronger vault, use a stronger passphrase.

Under the hood this uses the FIDO2 `hmac-secret` extension with a non-discoverable
credential, touch only. That was chosen because it programs *nothing* on your key: no OTP
slot overwritten, no PIV slot occupied, no resident-credential storage consumed, and no PIN
needed for day-to-day use. Unplug the key and there is no trace of 2fas on it.

Two things to know:

- **Setup takes two touches, every unlock afterwards takes one.** The first touch creates
  the credential, the second reads the secret it derives. (CTAP 2.2 can do both in one
  step, but not every key supports it.)
- **Setup needs your key's PIN if you have one set.** CTAP2 requires it to create a
  credential. Unlocking afterwards never does.
- **Do not enable `alwaysUv` on your key after setting it up.** User verification changes the
  hmac-secret output, so a key set up without it stops unwrapping. The setup screen warns
  about this; your passphrase still works, and running `--setup-key` again fixes it.

Before installing anything, you can check whether your key and machine are up to it:

```bash
pip install fido2
python scripts/probe_security_key.py
```

On Linux, the most common failure is not the key but udev: without the `libfido2` rules
(`70-u2f.rules`) the `/dev/hidraw*` nodes are not accessible to your user. Both the probe
and the setup screen will tell you if that is what is wrong.

### What the `code` policy does and does not do

Under `code`, the vault is still decrypted once and stays in RAM for the lifetime of the
process; the check happens just before a code is shown. So it buys presence attestation -
somebody at your unattended terminal with the menu open can not pull a code - and not
protection of the key material. That trade-off is deliberate: keeping the vault encrypted
and re-deriving per code would turn milliseconds of exposure into seconds, which is not
worth the complexity.

### As a Library

Please see the documentation of [lib2fas-python](https://github.com/robinvandernoord/lib2fas-python) for more details on
using this as a Python library.

## License

This project is licensed under the MIT License.
