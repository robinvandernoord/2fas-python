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

### As a Library

Please see the documentation of [lib2fas-python](https://github.com/robinvandernoord/lib2fas-python) for more details on
using this as a Python library.

## License

This project is licensed under the MIT License.
