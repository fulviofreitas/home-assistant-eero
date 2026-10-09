# Changelog

This file covers two forks:

- **[fulviofreitas/home-assistant-eero](https://github.com/fulviofreitas/home-assistant-eero)**: 2.0.0 and later.
- **[lpleva/home-assistant-eero](https://github.com/lpleva/home-assistant-eero)**: the audited 1.9.x releases this fork is based on.

---

# fulviofreitas/home-assistant-eero

## [2.0.0](https://github.com/fulviofreitas/home-assistant-eero/releases/tag/v2.0.0) (2026-10-09)

The integration now uses the [`eero-api`](https://pypi.org/project/eero-api/)
package instead of its own `requests` client, and splits polling into three
tiers. Entity unique IDs are unchanged, so entities, history and automations
carry over.

### Breaking changes

- Requires Home Assistant **2026.8.0** or later. Releases since 1.9.1 already
  needed it, but `hacs.json` still said 2025.2.0.
- Requires `eero-api==8.0.6`, which Home Assistant installs. It pulls in
  `keyring`, which is never used: the session token stays in the config entry.
- The request timeout option is capped at 30 seconds, the SDK's own limit.
  Higher stored values are clamped.
- Activity sensors refresh hourly. Thread, backup network and firmware data
  refresh daily, and right after you change them from Home Assistant.

### Polling

- Three tiers:
  - **Fast**, at your polling interval: network, clients, profiles, eeros.
  - **Hourly**: insights and data usage.
  - **Daily**: Thread, backup networks, entitlements, firmware updates.
- Fewer requests. With 3 networks and 10 profiles, a fast poll makes 9
  requests, where a 1.9.3 poll made 23.
- On a rate limit, each tier doubles its interval, up to 15 minutes, and goes
  back to normal after the next successful poll.
- Only the fast tier has to succeed for the integration to load. A failing
  hourly or daily tier makes only its own entities unavailable, and retries
  within 5 to 15 minutes instead of waiting for its next hourly or daily poll.
- A configured network that no longer exists, or that the account lost access
  to, is skipped with a Repairs issue. The other networks keep working.
- All I/O is async on Home Assistant's shared HTTP session, with no executor
  threads.

### Fixes

- Activity sensors now send their time window as query parameters. The old
  request was rejected by the API, so sensors that showed nothing may now show
  values.
- Profile ad-block, threat and scan sensors read the profile's own data.
- Choosing "schedule" as the Beacon nightlight mode no longer crashes.
- On a Sunday, the weekly activity sensors no longer report the previous week.
- The status light and guest network switches use the request format the SDK
  has verified against a real network.
- DNS caching uses the network's DNS settings object.

### Behaviour

- Setting an entity to the state it already has sends nothing. Some eero
  writes reboot every eero on the network, so repeats are skipped.
- **Changing DNS reboots every eero a few minutes later.** This applies to the
  DNS caching switch and to the custom DNS action.
- Premium entities follow the network's eero Plus entitlements. A feature the
  account can't use raises a Repairs issue instead of failing the poll.
- A failed action shows a readable, translated error. An expired session
  starts re-authentication.
- An unknown switch state shows as unknown, not off.
- The options flow works even when the integration failed to load, so you can
  deselect a network that is gone.
- New config flow error: `cannot_connect`, when the account's networks can't
  be read after login.
- `eero.set_blocked_apps` is always available and applies to every loaded
  eero entry.

### New entities

- **Clients**: block/unblock switch, and a select to move the client to a
  profile. The select is only offered where profiles are configured.
- **New clients** get their entities as they join, without reloading. The
  include/exclude filter is respected.
- **Profiles**: bedtime switch, plus weekday and weekend start and end times.
- **Guest network**: name text entity, and a write-only password text entity.
  The password is never shown as state.
- **Network**: power saving and fast transition switches, and an MLO mode
  select where the network supports it.
- **Network diagnostics**: reservation count, port forward count and DNS mode
  sensors.
- **Eero ports**: connection status and speed sensors per port, and port
  action buttons. The buttons are disabled by default.
- **Optional activity metrics**, off by default:
  - unprofiled-device and per-eero daily data usage;
  - an app events entity;
  - an unread-notifications sensor.

  Events appear up to an hour late. Past events are not replayed after a
  restart.
- Passpoint is not supported: there is no way to read its current state.
- The MLO, port and power saving entities use response formats that haven't
  been checked against a real network yet.

### New actions

- `eero.create_reservation` and `eero.delete_reservation`.
- `eero.create_port_forward` and `eero.delete_port_forward`.
- `eero.set_custom_dns`. This reboots the mesh. It sends at most one write,
  and only for address families that actually change.

### Configuration and translations

- **Reconfigure** changes the polling interval, request timeout and response
  logging directly.
- Every config flow field has a description.
- Entity names come from translations. Brazilian Portuguese (`pt-BR`) is
  added. English names and existing entity IDs are unchanged.

### Also in this release

- Config entry diagnostics, with tokens, passwords, keys and contact details
  redacted.
- The integration ships its own icon, so Home Assistant and HACS show it.
- The README documents setup, every option, entity and action, examples,
  limitations and troubleshooting.
- The manifest's code owner, documentation and issue tracker point at this
  fork.
- CI checks every change with lint, hassfest, HACS validation, tests and type
  checks. Tests run on Home Assistant 2026.8 and 2026.10.
- Releases, including the `eero.zip` that HACS installs, are cut by
  release-please from conventional commits.

---

# lpleva/home-assistant-eero

## 1.9.3

- The Advanced options step is always offered: polling interval, timeout and
  saved responses. It used to need Home Assistant's "advanced mode".

## 1.9.2

- Wired or wireless clients that the eero no longer reports as connected can
  be deleted from the device page. A deleted client comes back if it
  reconnects.

## 1.9.1

- Release notes load again. The allowed hosts now include `eeroassets.com`,
  where the firmware manifest lives.
- Child devices link to their network with `via_device_id` instead of the
  deprecated `via_device`.

## 1.9.0

A security and reliability release from a full code audit of the integration.

### Security

- Saved responses go to `.storage/eero_responses`. Login exchanges are never
  saved, and tokens, Wi-Fi passwords and Thread keys are redacted.
- API errors no longer write response bodies to the log. Those bodies
  contained the Wi-Fi password and Thread credentials.
- The Thread switch no longer exposes the Thread keys as attributes, and the
  guest network switch no longer exposes the guest password.
- Release notes are only fetched over https from eero's own hosts.
- The login identifier and verification code are no longer logged.

### Reliability

- An expired session starts re-authentication instead of looping on refresh
  requests. A refreshed token is saved to the config entry, and saving it
  does not reload the integration.
- A failed poll makes entities unavailable instead of freezing their last
  values.
- Every request has a timeout.
- Missing fields in API responses no longer break setup: no Thread, no backup
  capability, no updates block, no timezone.
- A resource that disappears is reported as missing. It no longer attaches to
  the wrong device.
- Data usage, status light, firmware, signal and update-hour entities cope
  with missing or unexpected values.
- An empty account response counts as a failed poll, not an account with no
  networks.
- Rate limits are reported. Release notes are cached.
- The polling floor is 60 seconds and the default 300 seconds.

### Behaviour and naming

- Entities use `has_entity_name`. Friendly names are built from the device
  name; this changes generated entity IDs for new installs.
- The QR-code image entities and their two unmaintained dependencies are
  removed.
- Device tracker attributes `ip`, `mac` and `host_name` are restored. Wireless
  clients also report band, channel and channel width.
- `light.turn_on` with the lowest brightness no longer turns the light off.
- Re-authentication refuses a different account.
