# Changelog

## 2.0.0

The integration now talks to the eero cloud through the
[`eero-api`](https://pypi.org/project/eero-api/) package instead of the
`requests`-based client vendored under `custom_components/eero/api`. The
property objects the entities read (`EeroNetwork`, `EeroClient`, ...) are kept;
underneath them the HTTP, the session refresh and the error classification are
the SDK's. Polling is split into three tiers so that data the API only changes
hourly or rarely is no longer fetched every poll. Entity unique IDs are
unchanged, so entities, their history and automations carry over.

### Breaking changes and requirements

- Requires the `eero-api==8.0.6` package, listed in the manifest's
  `requirements`; Home Assistant installs it. It depends on `keyring`, which
  therefore also gets installed but is never called: the client is built with
  `use_keyring=False` and an in-memory credential store, and the session token
  stays in the config entry as before.
- Minimum Home Assistant is now 2026.8.0, in `hacs.json` as well. The device
  tracker's `BaseScannerEntity` (Home Assistant 2026.6) and passing
  `via_device_id` to the device registry's `async_get_or_create` (accepted from
  2026.8) have been required since 1.9.1, but `hacs.json` still said 2025.2.0.
- All API I/O is async on Home Assistant's shared aiohttp session. No executor
  threads are used and `requests` is no longer used.
- The request timeout option now has a maximum of 30 seconds, because the SDK
  caps every request at 30 seconds and offers no way to raise that. A stored
  value above 30 is clamped when the entry is set up. The timeout is now the
  total time allowed for each request; in 1.x it was the read timeout of each
  request.

### Polling

- Data is fetched in three tiers, each its own coordinator:
  - fast, at the polling interval option (default 300 seconds): network,
    clients, profiles and eeros;
  - hourly: activity sensors (insights and data usage), which the API
    aggregates hourly, so polling them faster only returned the same numbers
    again;
  - daily, and right after a change made from Home Assistant that touches
    them: Thread, backup networks and backup internet, entitlements, firmware
    updates and release notes.

  Activity sensors, and the Thread, backup network and firmware entities,
  therefore update less often than in 1.x, where everything was re-read every
  poll. A change made in the eero app to one of the daily items shows up in
  Home Assistant within a day, not within one polling interval.
- Fewer requests per poll. The account is no longer re-read every poll (it is
  only read by the config and options flows). Eeros come embedded in the
  network response, so a separate eeros read happens only when they are
  missing from it. Clients and profiles are only read for networks where
  something uses them. Release notes are only fetched when at least one eero is
  configured (1.x fetched them for every network).
  Measured in the test suite on an account with 3 networks and 10 profiles,
  with clients and profiles configured and the default data-usage-week
  activity metric: a fast poll makes 9 requests, where one 1.9.3 poll made 23.
  Activity is read hourly and Thread, backup networks and updates daily, on
  top of that.
- The daily tier reads the network's entitlements and its `updates` resource,
  which 1.x did not read separately.
- Rate limits: each tier backs off on its own. A rate-limited poll doubles that
  tier's interval, up to 15 minutes, and its first successful poll puts it back
  to the normal interval. The Retry-After value is no longer shown in the
  error, because the SDK does not expose it.

### Fixes

- Activity requests sent `start`, `end` and `cadence` as a JSON body on a GET,
  which the API rejects with a 400. They are now query parameters, so activity
  sensors that showed nothing may now report values.
- Profile Ad Blocks, Threat Blocks and Scans sensors read the wrong
  part of the response: they matched entries by `insights_url` in a list that
  is not shaped that way. They now read each profile's own series. Client
  ad-block and threat sensors now read the per-device series (`devices`)
  instead of the network one.
- Selecting `schedule` as the Beacon nightlight mode raised a `TypeError`: the
  schedule setter was called without its on and off times. It now re-sends the
  current schedule.

### Writes that changed on the wire

These follow the request shapes eero-api documents:

- Status light on/off and brightness are form-encoded PUTs to the eero's
  published `led_action` link, the same URL 1.x used; 1.x sent a JSON body
  there. The form-encoded shape is the one eero-api has live-verified.
- Guest network enable/disable is a form-encoded PUT (live-verified in
  eero-api).
- DNS caching is written as `{"dns": {"caching": ...}}` on the network
  settings object; 1.x sent `{"caching": ...}` to `/networks/{id}/dns`. Every
  DNS write makes the eero cloud reboot all eeros on the network a few minutes
  later, so expect a short outage after toggling it.
- Nightlight writes go to the nightlight URL the eero publishes in its own
  data, instead of a hard-coded `/2.2/eeros/{id}/nightlight/settings`. eero-api
  marks this write as not yet confirmed against a live network.

Kept exactly as 1.x sent them, on purpose, through the SDK's raw request verbs
because the SDK has no method for them or its method sends something
different: profile content filters, ad blocking (network and profile),
Advanced Security malware blocking, 5 GHz pause, preferred update hour, client
internet-backup access, IPv6 upstream (the SDK's `set_ipv6` would also change
downstream), SQM (the SDK's `set_sqm` sends the value as a query parameter,
which eero-api has not verified) and the Thread enable path. Band steering,
UPnP, WPA3 and DDNS go through the SDK's methods, which send the same requests
1.x did, to the links the network publishes.

### Behaviour

- Read-compare-skip: a switch, select, time, number or light set to the state
  it already reports sends nothing. Some of these writes reboot every eero on
  the network; repeating one that changes nothing is never free.
- Premium entities are gated on the network's entitlements (a non-empty feature
  list), with `premium_status` as the fallback when entitlements cannot be
  read. A feature the account is not entitled to, or the network lacks, raises
  a Repairs issue instead of failing the poll; the issue clears itself when the
  feature becomes available and is removed when the entry is unloaded.
- An entity action that fails (switch, button, light, number, select, time,
  update), or the `eero.set_blocked_apps` action, raises a readable,
  translated error in the UI instead of an unhandled exception. An expired
  session during one of those actions starts reauthentication. Failed polls
  are reported with translated messages too.
- Session handling: the SDK refreshes the session only when the API answers
  `error.session.refresh`. An invalid or expired session goes straight to
  reauthentication; 1.x attempted one refresh first. The SDK never rotates the
  token; the integration still writes a changed token back to the config entry
  without reloading it.
- `eero.set_blocked_apps` is registered once at startup, whether or not any
  profile is configured, and applies to the configured profiles of every
  loaded eero entry (filtered by `target_network` and `target_profile`).
- Config flow: a new `cannot_connect` abort when the account's networks
  cannot be read after login, in both the config and the options flow. The
  options flow aborts with `not_loaded` when the entry is not loaded.

### New entities and actions

- `switch.<client>_blocked`: blocks or unblocks a client via the SDK's
  `blacklist.add_to_blacklist`/`remove_from_blacklist`. State is read from a
  new daily-tier read of the network's block list (`blacklist.get_blacklist`),
  fetched only for networks with client entities configured; blocking a
  client also refreshes the fast tier, since a blocked device is removed from
  the network's device list, not just flagged.
- `switch.<profile>_bedtime_enabled` and four `time.<profile>_bedtime_*`
  entities (weekday start/end, weekend start/end): read from a new
  daily-tier read of each configured profile's schedules
  (`schedule.get_schedules`), fetched only for networks with profile
  entities configured. The eero API models a bedtime as a named scheduled
  pause rather than a single on/off field, so these are matched by name
  ("Bedtime") and day set; turning the switch off disables the schedule(s)
  rather than deleting them, so times already set survive being turned back
  on. Writes go through `schedule.set_weekday_bedtime`/
  `set_weekend_bedtime`/`update_schedule`, none of which the SDK has
  verified against a live network yet (`warn_uncharacterised_write`).
- `select.<client>_profile`: assigns a client to a different profile, or
  unassigns it. Current/options are read from the already-fetched fast-tier
  profiles (no new request): the profile whose device list includes this
  client, matched by URL or MAC, since the device envelope itself carries no
  profile reference. Writes go through `profiles.set_profile_devices`, which
  replaces a profile's whole device list, so changing the assignment issues
  one write to the previous profile (device removed) and one to the new
  profile (device added). Only offered when at least one profile is
  configured on that network: the fast tier only fetches profiles in that
  case, so without it there is nothing honest to report the assignment from.

### Since 1.9.3, also in this release

- Config entry diagnostics: the API payload, with tokens, secrets and contact
  details redacted.
- Rate-limit backoff: a 429 doubles the polling interval, up to 15 minutes,
  and the next successful poll restores the configured interval. Before, every
  poll hit the limit again at the normal cadence. (In 2.0.0 this applies per
  tier, see Polling.)
- The manifest's `codeowners`, `documentation` and `issue_tracker` point at
  this fork instead of upstream.
- CI and release workflows: lint, hassfest, HACS validation, tests and type
  checks run on every push and pull request, and a `v*` tag builds `eero.zip`
  and attaches it to the GitHub release, which HACS installs (`zip_release` in
  `hacs.json`).

## 1.9.3

- The config and options flows always offer the Advanced options step (polling interval, timeout, save responses; all with defaults). It used to appear only when the Home Assistant user had "advanced mode" on, through `show_advanced_options`, which HA deprecated and removes in 2027.6.

## 1.9.2

- Devices can be deleted from Home Assistant's device page: `async_remove_config_entry_device` allows it for a wired or wireless client the eero does not currently report as connected (it is recreated if the client comes back); never for the network, an eero or a profile. Before this, the delete button was refused and dead clients lingered with all their entities.

## 1.9.1

Two fixes from the first run on Home Assistant 2026.9.1.

- The release-notes host allowlist added in 1.9.0 (**M5**) was too strict: it
  carried `eero.com` and `e2ro.com` only, while the firmware manifest URL in
  the API response points at `eeroassets.com`, Eero's own asset host. Every
  poll logged "Refusing to fetch release notes from unexpected host:
  eeroassets.com" and no release notes were shown. `eeroassets.com` and its
  subdomains are now allowed; the fetch is still https-only and still uses a
  bare request rather than the authenticated session.
- Child devices are linked to their network with `via_device_id` instead of
  `via_device`. Home Assistant deprecated the identifier-tuple `via_device`
  (it is removed in 2027.8) and warned once per platform on every start. The
  network device is now looked up in the device registry and its ID passed
  instead. Eeros, profiles, clients and backup networks sit under their
  network exactly as before.

## 1.9.0

Fixes for the findings in the code audit of this fork (4 critical, 9 high,
11 medium, 9 low). IDs below refer to that audit.

### Security

- **C1** — Saved responses no longer land in `custom_components/eero/api/responses`
  (inside the component source tree, so included in every backup). They go to
  `.storage/eero_responses`, every `/2.2/login*` exchange is skipped outright,
  and `user_token`, `password`, `psk`, `master_key`,
  `commissioning_credential` and `active_operational_dataset` are redacted
  from whatever is written.
- **C2** — `EeroException` no longer logs at WARNING from its constructor and
  no longer carries the response body. An Eero 500 on a network endpoint used
  to dump the WiFi PSK, the guest PSK and the Thread dataset into
  `home-assistant.log` with no option enabled. Error messages now name the URL
  path only, so query strings never reach the log.
- **H8** — The `thread_enabled` switch no longer publishes the Thread master
  key, commissioning credential or active operational dataset as state
  attributes, and the guest network switch no longer publishes the guest WiFi
  password. State attributes are readable by every logged-in user and are
  written to the recorder database.
- **M5** — The firmware manifest URL, which comes from the API response, must
  be https on `eero.com` or `e2ro.com` and is fetched with a bare request
  rather than the session that talks to the auth endpoint.
- **M6** — The login identifier and the one-time verification code are no
  longer written to the debug log, and config-entry migration logs key names
  rather than values.

### Reliability

- **C3** — The session refresh is bounded: at most one refresh per call, and a
  session that cannot be refreshed raises `EeroSessionExpired`. That becomes
  `ConfigEntryAuthFailed`, and a reauth step in the config flow asks for a new
  verification code and stores the new token. Previously a dead session sent
  hundreds of auth POSTs per poll and then crash-looped forever with no way
  out but delete-and-re-add.
- **C4** — API errors are no longer swallowed. `update()` raises, the
  coordinator marks the update failed, and entities become unavailable instead
  of reporting the values they had when the failure started. Presence
  automations now see a failure rather than a frozen `home`.
- **H1** — Every request carries a `(connect, read)` timeout, taking the
  configured polling timeout as the read value. `requests` transport errors
  (`ConnectionError`, `SSLError`, timeouts) all become `EeroException`.
- **H2** — A refreshed session token is written back to the config entry, so a
  restart no longer reloads a token Eero has already rotated.
- **H3** — A resource that disappears from the API is reported as missing
  rather than silently replaced by the network object, which is what produced
  `'EeroNetwork' object has no attribute 'paused'`. Unique IDs are built from
  configured IDs, so an entity can no longer attach itself to the wrong device.
- **H4** — The update loop treats every field of the response as optional: no
  Thread border router, no `backup_access_point` capability, no `updates`
  block and no timezone no longer break setup.
- **H5** — Data usage sensors report unknown instead of raising
  `TypeError: NoneType + NoneType` right after a period rolls over.
- **H6** — Status light brightness handles an eero that reports no
  `led_brightness`, and rounds instead of truncating.
- **H7** — Firmware entities cope with a network that has no release notes.
- **H9** — `EeroProfile.ad_block` no longer raises `TypeError` when
  `premium_dns` is unpopulated, which used to prevent the entire switch
  platform from creating a single entity.
- **M1** — The request retried after a session refresh is checked.
- **M2** — 429 raises `EeroRateLimited` carrying `Retry-After`. Release notes
  are cached per manifest URL instead of refetched every poll. The polling
  floor moves 30s → 60s and the default 120s → 300s.
- **M9** — Entity discovery no longer uses bare `hasattr`, so one broken
  property cannot abort a whole platform's setup and failures are logged.
  (Partial: the audit's declarative `supported_resources` redesign was not
  attempted.)
- **M10** — The `requests.Session` is closed when the entry unloads.
- **L7, L8** — `preferred_update_hour` and `EeroClient.signal` no longer raise
  on unexpected values.

### Behaviour and naming

- **M7** — `has_entity_name` is adopted. Entities are named for what they
  measure ("Signal Strength") and Home Assistant composes the friendly name
  from the device name; the network prefix and wired/wireless suffix moved to
  the device. **This changes generated entity IDs**, which is why it ships
  before first install. Unique IDs are unchanged.
- **Image platform removed.** The two QR-code image entities per network are
  gone, along with the `pypng` and `PyQRCode` requirements (sdist-only, last
  released 2019 and 2016; a requirements install failure takes down the whole
  integration) and the `show_eero_logo` option. This also resolves **M3** (QR
  PNGs re-encoded on the event loop on every state write) and **M4**
  (hardcoded `/config` paths).
- **M8** — Profile clients are constructed with their network, not their
  profile.
- **M11** — `EeroNetwork.update()` is now `install_firmware_update()`: it
  updates every eero on the network, which the old name did not say.
- **L5** — `secondary_wan_deny_access` is now `secondary_wan_allow_access`,
  matching what it returns and what the switch is labelled.
- **L6** — Networks with no geolocation no longer appear as
  "MyNetwork (None, None)".
- **L1, L2, L3, L4, L9** — Real type annotations instead of `str[EntityCategory]`,
  working form prefill in the config flow, consistent entity base-class order,
  dead `camera` translations removed, `quality_scale` dropped, `loggers` set,
  and the coordinator gets `config_entry`.

### Fixes to the PRs merged into this fork

- PR #170's `except (KeyError, ValueError): pass` is now a KeyError-only
  handler that logs and explains the cause (a snapshot of the device registry
  being iterated while entries are removed). It has nothing to do with
  Python 3.14, contrary to the commit message.
- PR #171 dropped the `ip`, `mac` and `host_name` device_tracker attributes
  when it moved to `BaseScannerEntity`. Restored.
- PR #174's unreachable `.strip()` removed; the attribute is named
  `channel_width_rx`, which is the field it reads.
- `light.turn_on` with `brightness: 1` mapped to 0 and turned the light off.
  Clamped to 1.

### Post-review fixes

An independent review of these changes raised one blocking regression and
seven smaller items, all fixed here.

- **B1** — Home Assistant fires an entry's update listeners on any change,
  data included, so the token written back by the H2 fix reloaded the whole
  integration on every session rotation: entities removed and re-added,
  `consider_home` clocks reset, the `requests.Session` closed under an
  executor thread, and a second poll started on top of the one in flight.
  `async_update_listener` now reloads only when the options changed or when
  the entry's token differs from the one the running API object holds, which
  is true of a token from the reauth flow and false of one this integration
  persisted itself.
- **N1** — The asyncio timeout around the whole poll is gone. It gave the
  entire multi-request poll the budget of one request, and cancelling it never
  killed the executor thread, which is what H1's per-request timeout is for.
- **N2** — A failed release-notes fetch logs a warning instead of failing the
  poll. A 404 on the firmware manifest used to take every entity in the house
  unavailable over a decoration on the update entities.
- **N3** — A release-notes URL on an unexpected host is refused once and the
  refusal cached, instead of warning every poll forever.
- **N4** — The reauth step passes `reload_even_if_entry_is_unchanged=False`.
  Asking `async_update_reload_and_abort` to schedule a reload on an entry that
  has an update listener is deprecated and breaks in Home Assistant 2026.12;
  the listener owns the reload.
- **N5** — Reauth fails closed when the verification response carries no
  `log_id`, rather than skipping the wrong-account check and writing the token
  in unverified.
- **N6** — An account response with no `networks` member raises instead of
  building an empty account. On a cold start it used to set the integration up
  successfully with no entities and no reason logged.
- **N7** — The scan interval is clamped to the floor when read, in both the
  setup path and the options form, so a stored value below a raised floor
  cannot make the form unsubmittable. The floor is 60s (the default stays
  300s).
- **N8** — Comment only: `device_info` returning None is permanent, since
  Home Assistant reads it once at registration.

### Tests

`tests/` holds 41 tests for the api package, running without Home Assistant
installed:

```bash
python3 -m venv .venv && .venv/bin/pip install pytest requests
.venv/bin/python -m pytest -q
```

## 1.8.1 and earlier

See the upstream project: https://github.com/schmittx/home-assistant-eero
