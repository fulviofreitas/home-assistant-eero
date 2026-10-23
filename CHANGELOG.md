# Changelog

This file covers two forks:

- **[fulviofreitas/homeassistant-eero](https://github.com/fulviofreitas/homeassistant-eero)**: 2.0.0 and later.
- **[lpleva/home-assistant-eero](https://github.com/lpleva/home-assistant-eero)**: the audited 1.9.x releases this fork is based on.

---

# fulviofreitas/homeassistant-eero

## Unreleased

### Fixes

- With two or more networks configured, setup no longer removes each
  network's eeros, profiles, backup networks and clients from the device
  registry. A device was dropped as soon as one network did not list it; it
  is now dropped only when no configured network wants it. A client one
  network excludes stays while another network includes it. With one
  network nothing changes.
- Actions targeted at a network by its ID now reach it. The ID was turned
  into a number and never matched, so the action did nothing and reported
  no error; naming the network worked. The same applied to `target_profile`
  IDs in `eero.set_blocked_apps`, and to a network or profile whose name is
  only digits.

## [2.2.2](https://github.com/fulviofreitas/homeassistant-eero/compare/v2.2.1...v2.2.2) (2026-10-23)


### Bug Fixes

* point manifest and docs at the renamed repository ([5e32abe](https://github.com/fulviofreitas/homeassistant-eero/commit/5e32abebc35d799b782e14e921ea4e86177519d7))


### Documentation

* **readme:** add My Home Assistant HACS and setup buttons ([2849646](https://github.com/fulviofreitas/homeassistant-eero/commit/28496461835bef247bd6a06e346ea882829934bb))

## [2.2.1](https://github.com/fulviofreitas/home-assistant-eero/compare/v2.2.0...v2.2.1) (2026-10-20)


### Bug Fixes

* **init:** keep devices another configured network still wants ([620ef05](https://github.com/fulviofreitas/home-assistant-eero/commit/620ef052648a98cc8ecf588c48675ba2e9731f0c))
* **services:** match target_network and target_profile IDs as strings ([56a174d](https://github.com/fulviofreitas/home-assistant-eero/commit/56a174d549e91656fc62d15d93c6a649db59d1a7))

## [2.2.0](https://github.com/fulviofreitas/home-assistant-eero/compare/v2.1.2...v2.2.0) (2026-10-20)

### Features

- **WAN download and WAN upload sensors** on the network device: the
  network's live throughput in Mbit/s, two decimals, built on eero's usage
  burst. While one of them is enabled the integration requests a burst once
  a minute and reads the device list about 12 seconds later, then sums the
  live usage of the connected devices (deduplicated by MAC address). A
  reading expires after 90 seconds, after which the sensors are unavailable
  rather than 0; a connected device with no usable usage makes the total
  unknown. Attributes: the next burst the API allows, and the number of
  devices summed. Disabled by default, since they cost two extra requests per
  minute per network; not created on a network in bridge mode. A failed burst
  keeps the last reading until it expires; a network that refuses the burst
  raises a Repairs issue and is not asked again until the integration is
  reloaded.

### Changes

- Requires `eero-api` 8.4.1 (was 8.4.0), where the burst request is
  live-verified and no longer logs a warning.
- The per-client **Download Rate** and **Upload Rate** sensors read the same
  per-device `usage` block the burst refreshes. Until now that block was
  stale or zero, because nothing ever requested a burst; once a network's
  WAN download or WAN upload sensor is enabled, the burst runs every minute
  and these sensors show live values on each fast poll (the next poll after
  a burst, at the polling interval). With the WAN sensors disabled they
  behave as before.

## [2.1.2](https://github.com/fulviofreitas/home-assistant-eero/compare/v2.1.1...v2.1.2) (2026-10-19)

### Changes

- Requires `eero-api` 8.4.0 (was 8.3.0). The client Internet Backup switch,
  the IPv6 Upstream switch, the network and profile Ad Block switches, the
  Block Malware switch and the per-eero data usage read now use eero-api's
  own methods for them; the requests sent to eero are unchanged. The profile
  content filters, Smart Queue Management and Thread switches keep sending
  their own requests until eero-api has verified methods for them.

## [2.1.1](https://github.com/fulviofreitas/home-assistant-eero/compare/v2.1.0...v2.1.1) (2026-10-12)

### Fixes

- The network's Connected Clients and Connected Guest Clients sensors showed
  0 unless a wired or wireless client entity was configured, and each eero's
  Connected Clients sensor had an empty `clients` attribute. The device list
  they count from is now read on every poll, which adds one request per
  network per scan interval. Profile and eero client counts were already
  correct.

## [2.1.0](https://github.com/fulviofreitas/home-assistant-eero/compare/v2.0.1...v2.1.0) (2026-10-12)

### Changes

- Requires `eero-api` 8.3.0 (was 8.0.6). The account read, the Preferred
  Update Time select and the 5 GHz pause switch now use eero-api's own
  methods for them; the requests sent to eero are unchanged.
- After a rate limit, the integration waits at least as long as the eero API
  asks (its `Retry-After` header), up to one hour, before polling again.
  Without the header, the backoff is as before.

### Internal

- A contract test runs every control and the main reads through the real
  eero-api and checks the exact request each one sends, so an eero-api
  upgrade that changes a request is caught before release.

## [2.0.1](https://github.com/fulviofreitas/home-assistant-eero/compare/v2.0.0...v2.0.1) (2026-10-09)

### Fixes

- Setup no longer fails when Home Assistant's device registry holds an eero
  device without a model, for example one registered for a port while its
  eero was unavailable.

### Internal

- The whole integration is type-checked in mypy's strict mode. No behaviour
  change is intended.

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
