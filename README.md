# 2fas Python

2fas-python is an unofficial implementation
of [2FAS - the Internet’s favorite open-source two-factor authenticator](https://2fas.com).
It consists of a core library in Python and a CLI tool.

## Installation

To install this project, use [uvenv](https://github.com/robinvandernoord/uvenv) (recommended), pipx, uv or pip:

```bash
uvenv install 2fas
# or:
uv tool install 2fas
# or:
pipx install 2fas
# or:
pip install 2fas
```

## Usage

To see all available options, you can run:

```bash
2fas --help
```

If you simply run `2fas` or `2fas /path/to/file.2fas`, an interactive menu will show up.
If you only want a specific TOTP code, you can run `2fas <service>` or `2fas /path/to/file.2fas <service>`.
Multiple services can be specified: `2fas <service1> <service2> [/path/to/file.2fas]`.
Fuzzy matching is applied to (hopefully) catch some typos.
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

This can also be done from within the interactive menu.
`2fas` cli settings are stored in `~/.config/2fas/config.toml` and contain the following settings:

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

If your settings file is still at an older location (`~/.config/2fas.toml`), it is moved
into place the first time you run `2fas`. The directory also holds `keys/`, used by the
security key support below.

## Unlocking your vault

Your `.2fas` file is encrypted with a key derived from your passphrase (PBKDF2-HMAC-SHA256,
10 000 iterations - that number is fixed by the 2FAS file format, so a strong passphrase is
what actually protects the file). `2fas` never writes to your `.2fas` file; it only ever
reads it.

An unlock method and two policies control unlocking, and the policies are separate on purpose.

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
rest of that session.

`--all` is always one unlock per invocation, never one per service.

`os-session` caches the derived key, never your passphrase, in your login keyring. It is a
forget-on-reboot mechanism, not access control: while that keyring is unlocked, other
processes running as you can read it. If no keyring is available, it behaves like `process`.

### Unlocking with a security key

Works with FIDO2 authenticators that implement the `hmac-secret` extension, including many
YubiKey, SoloKey, Nitrokey, and Token2 devices. Nothing here is vendor-specific.

```bash
2fas --setup-key         # sets it up: offers to install what is missing, then two touches
2fas                     # from now on: one touch, no passphrase
2fas --password          # skip the key for one run
2fas --forget-key        # remove the security key setup for the active file
```

The same options live under **Settings > Unlocking & security key** in the interactive
menu. In every menu, `Escape` goes back a step and `Ctrl-C` quits. That screen also
reports what 2fas can see of your key: product, firmware, hmac-secret support, and on
Linux whether udev is in the way.

Choosing "security key" as your unlock method is greyed out until one is actually set up for the
active file - otherwise you would be picking a method that silently falls back to your
passphrase on every run.

Security key support needs one extra Python package, `fido2`. `2fas --setup-key` offers a
detects how 2fas was installed and offers the matching install command, always asking
before running it. If you would rather
install it yourself:

```bash
uvenv inject 2fas fido2            # if you installed 2fas with uvenv
uv tool install --with fido2 2fas  # if you installed 2fas as a uv tool
pipx inject 2fas fido2             # if you used pipx
uv pip install fido2               # or pip install fido2, in a plain venv
```

**The security key replaces the normal passphrase prompt; it is not a second factor.**
Setting one up does not re-encrypt your `.2fas` file. It stores a copy of the vault key,
encrypted under a secret only your security key can produce, in `~/.config/2fas/keys/`.
Your file stays passphrase-encrypted, so:

- **the security-key setup cannot lock you out.** Lost key, dead key, forgotten to bring it - your
  passphrase always still works, and `--password` skips the key deliberately.
- **your effective strength is the weaker of the two paths**, which is your passphrase.
  Adding a security key buys you convenience and protection of the *cache*, not a stronger vault.
  If you want a stronger vault, use a stronger passphrase.

Setup takes two touches; subsequent unlocks take one. Setup also requires the key's PIN if
one is configured, but normal unlocking does not. On Linux, you may need libfido2's udev
rules (`70-u2f.rules`) for access to `/dev/hidraw*`.

### About the `code` policy

The vault remains decrypted in RAM for the process lifetime; the extra check happens just
before a code is shown. This provides presence attestation for an unattended open menu, not
protection of key material already loaded into memory.

<details>
<summary>Compatibility and troubleshooting details</summary>

2fas uses a touch-only, non-discoverable FIDO2 credential, so it does not consume resident
credential storage or modify OTP or PIV slots. If you enable `alwaysUv` after setup, the key
will produce a different `hmac-secret` result; set it up again to use that configuration.
Your passphrase remains available throughout.

</details>

### As a Library

Please see the documentation of [lib2fas-python](https://github.com/robinvandernoord/lib2fas-python) for more details on
using this as a Python library.

## License

This project is licensed under the MIT License.
