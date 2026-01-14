# Changelog

<!--next-version-placeholder-->

## v1.1.1 (2026-01-14)

### Documentation

* Mark support for newer python versions ([`0e10b27`](https://github.com/robinvandernoord/2fas-python/commit/0e10b27ed997e075fd8ba932825fa0638700f062))

## v1.1.0 (2025-05-23)

### Feature

* Allow passing `-1` up to `-4` to bypass first interactive menu ([`4910e90`](https://github.com/robinvandernoord/2fas-python/commit/4910e90025bf65fdd2ff9434265dca29e21ddbcf))

### Fix

* **load_cli_settings:** Prevent configuraptor FailedToLoad ([`01e12aa`](https://github.com/robinvandernoord/2fas-python/commit/01e12aac2d63aada754efab128e6d092be698f93))

## v1.0.5 (2025-02-27)

### Fix

* Bump lib2fas dependency to 0.1.9 ([`5a4a5ab`](https://github.com/robinvandernoord/2fas-python/commit/5a4a5ab5cd9f7a0062fe799a52839c89f3709bad))

## v1.0.4 (2025-01-12)

### Fix

* Don't crash if expected 2fas file is missing, just show an error and disable some options (e.g. generating a TOTP) so you can still access and change settings. ([`3723d4c`](https://github.com/robinvandernoord/2fas-python/commit/3723d4c8d33273e5dca2bbd0f03750d0905dcba2))

### Documentation

* Extended README with 2fas cli config docs ([`01ac3b4`](https://github.com/robinvandernoord/2fas-python/commit/01ac3b4ea0ba6f8724b8ba0b543bff8daf3d54ec))

## v1.0.3 (2024-04-10)

### Fix

* Bump lib2fas version to fix some issues with keyring ([`b093bdc`](https://github.com/robinvandernoord/2fas-python/commit/b093bdc434841ace1dbd526149a2cac5238f0924))
* Don't crash without args (= None instead of []) ([`efa1e69`](https://github.com/robinvandernoord/2fas-python/commit/efa1e69183c9ce1a204a5ac75b1a7d458c92c647))

## v1.0.2 (2024-02-29)

### Fix

* Explicitly add typing-extensions as dependency ([`2f5c7ab`](https://github.com/robinvandernoord/2fas-python/commit/2f5c7ab92a12e0568dad40f29446187895db2e91))

## v1.0.1 (2024-01-29)

### Feature

* --version now also prints lib2fas library version ([`4899a83`](https://github.com/robinvandernoord/2fas-python/commit/4899a836acf216b0584c4f9224d1ec14662b678f))

## v1.0.0 (2024-01-29)

### Fix

* Extracted core funcionality to lib2fas ([`88ca459`](https://github.com/robinvandernoord/2fas-python/commit/88ca459c2b2f2f227b72d2d5722e051cc140f35b))

## v0.1.0 (2024-01-25)

### Feature

* Cli tweaks and more pytests ([`01f8574`](https://github.com/robinvandernoord/2fas-python/commit/01f8574e527a60025e4e7b7bf0416a4e344fde2e))
* Started basic cli functionality ([`f15bbbf`](https://github.com/robinvandernoord/2fas-python/commit/f15bbbfe1d4e79ba644775dd1e4eb638e394dc81))
* TwoFactorStorage is now a recursive data type when using .find() ([`1f4847f`](https://github.com/robinvandernoord/2fas-python/commit/1f4847fa07eecd9c85623e5cb799a34ab3a8714d))
* Added tests and more general functionality ([`be86df5`](https://github.com/robinvandernoord/2fas-python/commit/be86df54cc4616541c6e636e882a1fa444af9d3a))

### Fix

* Improved settings menu + mypy typing + refactor ([`5d08f62`](https://github.com/robinvandernoord/2fas-python/commit/5d08f62daba7873e84766562c07370fa22018868))
* Improved settings tui ([`c0275b5`](https://github.com/robinvandernoord/2fas-python/commit/c0275b5d5e1b77fba77f65f3efdb5d117d9f5715))
* Include rapidfuzz in dependencies (previously only collected via 'dev' extra) ([`d2016e0`](https://github.com/robinvandernoord/2fas-python/commit/d2016e033ff00392032492525a3c4eb14a4432b3))
