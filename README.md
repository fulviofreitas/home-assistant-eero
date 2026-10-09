## About this fork

This is an audited fork of [schmittx/home-assistant-eero](https://github.com/schmittx/home-assistant-eero), taken at upstream version 1.8.1. The current version is the `version` field in `custom_components/eero/manifest.json`, and CHANGELOG.md lists what each version changed. It exists because, in the Home Assistant install it serves, every integration that holds a login or can act on the home gets a line-by-line audit before it runs, and the fixes live here rather than upstream.

**Why it was forked.** Upstream's device tracker broke on Home Assistant 2026.7 and the project went quiet with the fix sitting in an unmerged pull request, so the only way to run working code was to carry it ourselves.

**What is different.** It merges upstream pull requests #170, #169, #171 and #174 (the 2026.7 device-tracker fix, a Python 3.14 crash fix, a bug-fix bundle, and per-client band, channel and width). A full code audit then found 33 issues and every one is fixed here: the session token is never written to disk or logged, API errors no longer dump response bodies (which carried the wifi password and Thread key) into the log, an expired session raises a re-authentication prompt instead of crashing in a loop, failed polls make entities unavailable instead of freezing on stale data, HTTP calls have timeouts, several crash paths on missing fields are closed, the image platform and its two abandoned dependencies are gone, and a test suite (46 tests at 1.9.3, no Home Assistant needed) was added. An independent review then found and fixed one more defect: a token refresh no longer reloads the whole integration. Fixes are not sent upstream; upstream is unchanged by this fork.

**How it is kept current.** A weekly job merges upstream's new commits onto a branch, runs this fork's tests, reviews the diff, and only then pushes; a merge conflict or a failing test stops it. The fork is installed through HACS as a custom repository, so Home Assistant offers each new version as an update.

**Where the detail is.** CHANGELOG.md records every change by version, and by audit finding for 1.9.0.

---

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)
# Eero Home Assistant Integration
Custom component to allow control of Eero networks in [Home Assistant](https://home-assistant.io).

## Credit
- [@343max's eero-client project](https://github.com/343max/eero-client) - Basic API auth and refresh methods
- [@jrlucier's eero_tracker project](https://github.com/jrlucier/eero_tracker) - Initial Home Assistant idea

## Install
1. Ensure Home Assistant is updated to version 2025.2.0 or newer.
2. Use HACS and add as a [custom repo](https://hacs.xyz/docs/faq/custom_repositories); or download and manually move to the `custom_components` folder.
3. Once the integration is installed follow the standard process to setup via UI and search for `eero`.
4. Follow the prompts.

## Options
- Networks, resources, and activity metrics can be updated via integration options.
- The inclusion method for clients can be toggled between whitelisting (include only selected clients) or blacklisting (exclude only selected clients).
- An Advanced step is always offered at the end of setup and of the options flow: polling interval, request timeout, and response logging, each with a default. Before 1.9.3 this step appeared only when `Advanced Mode` was enabled on the user profile.

## Notes
- This integration does not support login via Amazon account. A workaround is to create a new account without Amazon login and add that account as another network admin. Refer to this [post](https://github.com/schmittx/home-assistant-eero/issues/77#issuecomment-1960875926) for step-by-step instructions.
- The integration is moving to the [`eero-api`](https://pypi.org/project/eero-api/) package on PyPI (import name `eero`) as its API client. That package depends on `keyring`, so installing it also installs `keyring`. The integration creates the client with `use_keyring=False`, so no keyring function is ever called and the session token stays in the config entry as before. On Home Assistant the `keyring` package installs and goes unused.

## Currently Working
- Multiple networks supported
- Control network properties (ex. guest network, Eero Plus features, Eero Labs features)
- Pause access for profiles and/or clients
- Control content filters for profiles
- Device tracker entities for clients and profiles (wireless clients also report `ip`, `mac`, `host_name`, `band`, `channel`, and `channel_width_rx` attributes)
- Sensors for various metrics
- Button entities to control features that require network restarts
- Select and time entities to control nightlight features for Eero Beacon devices
- Sensors for activity data (requires Eero Plus subscription)
- Set blocked apps for profiles (requires Eero Plus subscription)
- Update entities for Eero device firmware management
- Control backup networks (requires Eero Plus subscription)

## Coming Soon
- TBD, feature requests are welcome.
