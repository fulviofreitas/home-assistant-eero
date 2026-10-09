[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)

# eero for Home Assistant

A custom integration that brings eero mesh Wi-Fi networks into [Home Assistant](https://www.home-assistant.io). It reads your networks, eeros, profiles and connected devices from the eero cloud, and lets you control them: pause a profile, block a device, toggle the guest network, change network settings, install firmware, and more.

This page is the integration's user documentation.

## About this fork

This fork carries on [lpleva/home-assistant-eero](https://github.com/lpleva/home-assistant-eero), an audited fork of [schmittx/home-assistant-eero](https://github.com/schmittx/home-assistant-eero) taken at upstream version 1.8.1. Upstream's device tracker broke on Home Assistant 2026.7 with the fix left in an unmerged pull request, so the lpleva fork merged that fix and several other upstream pull requests, then fixed the issues found in a full code audit (secrets kept out of logs and saved responses, re-authentication instead of crash loops, unavailable entities instead of stale data, request timeouts). From 2.0.0 this fork talks to the eero cloud through the [`eero-api`](https://pypi.org/project/eero-api/) package, polls in three tiers, and adds the entities and actions listed below.

[CHANGELOG.md](CHANGELOG.md) records what each version changed, for this fork and for the lpleva fork it builds on. The current version is the `version` field in `custom_components/eero/manifest.json`.

## Contents

- [Supported devices](#supported-devices)
- [Use cases](#use-cases)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Setup parameters](#setup-parameters)
- [Configuration options](#configuration-options)
- [Data updates](#data-updates)
- [Supported functions](#supported-functions)
- [Actions](#actions)
- [Examples](#examples)
- [Known limitations](#known-limitations)
- [Troubleshooting](#troubleshooting)
- [Removing the integration](#removing-the-integration)
- [Credit](#credit)

## Supported devices

The integration works with any eero mesh network on an eero account. It talks to the eero cloud API, not to the hardware, so it does not depend on a particular model:

- **eero and eero Pro units** (gateways and extenders, any generation) appear as eero devices with status, connected-client count, status light, firmware update and, where the API reports them, per-port entities.
- **eero Beacon units** additionally get their nightlight controls (mode, brightness, schedule).
- **eero Plus subscription**: content filters, ad blocking, advanced security, threat and ad-block counters, dynamic DNS, backup networks and backup internet are only offered on a network whose account is entitled to them. Without the subscription those entities are not created, and a Repairs issue explains which feature needs it.

Several networks on one account are supported, and so are several accounts (one config entry each). Accounts that sign in with Amazon are not supported; see [Known limitations](#known-limitations).

## Use cases

- **Presence detection.** Each selected device (phone, watch, laptop) gets a device tracker that reports `home` while it is connected to the eero network. Combine it with other trackers in a Home Assistant person.
- **Parental controls on a schedule.** Pause a profile (all of a child's devices) at bedtime or during homework, or switch content filters on and off from automations and dashboards.
- **Blocking a device.** Block an unknown or misbehaving device from the network, or move a device to a different profile.
- **Network monitoring.** Track connected-client counts, upload and download rates per device, signal strength, the last speed test result, the public IP, and daily, weekly or monthly data usage.
- **Guest access.** Turn the guest network on for a party and off again afterwards, and change its name or password from Home Assistant.
- **Maintenance.** See and install eero firmware updates, choose the preferred update hour, and manage DHCP reservations, port forwards and DNS from automations or scripts.

## Prerequisites

- Home Assistant **2026.8.0** or newer.
- An eero account that signs in with an email address or a phone number (SMS), not with Amazon. Any admin of the network works, so you can create a separate account for Home Assistant and add it as an admin from the eero app.
- Internet access from Home Assistant: all data comes from the eero cloud.

## Installation

### HACS (recommended)

1. In HACS, open the menu and choose **Custom repositories**.
2. Add `https://github.com/fulviofreitas/home-assistant-eero` with the type **Integration**.
3. Search for **eero** in HACS, open it, and select **Download**.
4. Restart Home Assistant.

HACS then offers each new release as an update.

### Manual

1. Download `eero.zip` from the latest release of this repository, or copy the `custom_components/eero` folder from the source.
2. Put the files in `config/custom_components/eero/` of your Home Assistant installation, so that `config/custom_components/eero/manifest.json` exists.
3. Restart Home Assistant.

Home Assistant installs the `eero-api` dependency itself when the integration loads.

### Adding the integration

1. Go to **Settings** > **Devices & services** and select **Add integration**.
2. Search for **eero** and follow the steps described below.

## Setup parameters

Setup asks for the following, in this order. The networks, resources, activity metrics and miscellaneous steps are shown once for each network you select.

### 1. Login

| Parameter | Description |
| --- | --- |
| Login (email or SMS phone number) | The email address or phone number (with country code) you use to sign in to the eero app. eero sends a one-time code to it. |

### 2. Verification code

| Parameter | Description |
| --- | --- |
| Verification code | The one-time code eero emailed or texted to the login above. A wrong code shows "Invalid code". |

The account is identified by its eero account ID, so the same account cannot be added twice.

### 3. Networks

| Parameter | Default | Description |
| --- | --- | --- |
| Networks | All networks on the account | The eero networks to set up. Unselected networks are not added. |

### 4. Network resources (per network)

Every selected resource gets a device in Home Assistant with its entities.

| Parameter | Default | Description |
| --- | --- | --- |
| Eero devices | All eeros | The eero units to create a device and entities for. |
| Profiles | All profiles | The profiles to create a device and entities for. |
| Wired clients | None | Wired devices to create a device and entities for, or to leave out, depending on the filter below. |
| Wired clients filter behavior | Include selected | **Include selected**: only the selected wired clients get entities. **Exclude selected**: every wired client gets entities except the selected ones. |
| Wireless clients | None | Same as wired clients, for wireless devices. |
| Wireless clients filter behavior | Include selected | Same as above, for wireless clients. |
| Backup Networks | All backup networks | Only shown on a network with eero Plus. Other networks on the account that can back this one up over the internet. |

With the default include filter and no clients selected, no client gets entities. To track every device on the network, set the filter to **Exclude selected** and select nothing; new devices then get entities as they join.

### 5. Activity metrics (per network)

Each selected metric adds a sensor (or, for app events, an event entity) and one extra API request per hour. All are off by default. Selecting many metrics can lead to timeouts.

| Parameter | Shown when | Options |
| --- | --- | --- |
| Network | Always | Network-wide metrics. |
| Eero devices | At least one eero is selected | Per-eero data usage: week; with eero Plus also day and month. |
| Profiles | At least one profile is selected | Per-profile metrics. |
| Clients | At least one client is selected | Per-client metrics. |

Options offered for network, profiles and clients:

- Without eero Plus: Data Usage (Week), Unprofiled Data Usage Day, Eeros Data Usage Summary Day, App Events, Unread Notifications.
- With eero Plus, additionally: Data Usage (Day, Month), Ad Blocks (Day, Week, Month), Threat Blocks (Day, Week, Month), Scans (Day, Week, Month).

Unprofiled data usage, the eeros data usage summary, app events and unread notifications only produce an entity on the network device.

### 6. Miscellaneous options (per network)

| Parameter | Default | Limits | Description |
| --- | --- | --- | --- |
| Consider home interval | 0 minutes | 0 to 30 minutes | How long a device tracker stays `home` after the device stops being reported as connected. Only useful when it is longer than the polling interval; 0 turns it off. |
| Add network name as a prefix for all non-network entities | On | | Puts the network name in front of every device name except the network's own, e.g. `Home Kids` for the Kids profile on network Home. Helps when several networks are configured. |
| Add connection type as a suffix for all client devices and entities | On | | Adds `(Wired)` or `(Wireless)` to client device names, e.g. `Home Alex Phone (Wireless)`. |

These two naming options shape entity IDs, such as `device_tracker.home_alex_phone_wireless`.

### 7. Advanced options

| Parameter | Default | Limits | Description |
| --- | --- | --- | --- |
| Save redacted server responses to .storage/eero_responses | Off | | Writes each API response, with tokens, passwords and keys redacted, to `config/.storage/eero_responses/`. For troubleshooting and bug reports. Login exchanges are never saved. |
| Polling interval | 300 seconds | 60 to 600 seconds, in steps of 30 | How often the fast tier (network, clients, profiles, eeros) is polled. See [Data updates](#data-updates). |
| Polling timeout | 30 seconds | 10 to 30 seconds, in steps of 5 | How long to wait for the eero API before giving up on a request. Must be shorter than the polling interval. |

## Configuration options

After setup, the same choices can be changed in two places.

### Configure (options flow)

Go to **Settings** > **Devices & services** > **eero**, and select **Configure**. It walks through the same steps as setup, except login, pre-filled with the current values:

1. **Networks**: which networks are set up.
2. **Network resources** (per network): eeros, profiles, wired and wireless clients with their filter behavior, and backup networks. Deselecting a resource removes its device and entities; with an exclude filter, selecting a client removes it.
3. **Activity metrics** (per network). Deselecting a metric removes its entity.
4. **Miscellaneous options** (per network): consider home interval, network name prefix, connection type suffix.
5. **Advanced options**: saved responses, polling interval, polling timeout.

All parameters, defaults and limits are those listed under [Setup parameters](#setup-parameters). Saving reloads the integration. Configure also works when the integration failed to load, so a network that no longer exists can be deselected.

### Reconfigure

From the integration's menu (three dots), **Reconfigure** changes only the polling interval, polling timeout and saved responses, with the same defaults and limits as the advanced options, then reloads the integration.

## Data updates

The integration polls the eero cloud (`cloud_polling`); eero does not push changes. Polling is split into three tiers, each on its own schedule:

| Tier | Interval | What it refreshes |
| --- | --- | --- |
| Fast | The polling interval (default 300 seconds, 60 to 600) | The network itself, its clients, its profiles and its eeros: device trackers, connected state, IP addresses, rates, signal, counts, most switches and selects. |
| Hourly | Every hour | The selected activity metrics: data usage, ad blocks, threat blocks, scans, app events, unread notifications. The eero API aggregates these hourly, so polling faster would return the same numbers. |
| Daily | Every 24 hours | Client block list, profile bedtime schedules, DHCP reservations and port forwards, 802.11r fast transition, eero ports, Thread, eero Plus entitlements, backup networks and backup internet, firmware updates and their release notes. |

- **After a change made from Home Assistant**, the tier holding that data is refreshed right away, so the new state shows without waiting for the next poll. A few writes (Local DNS Caching, IPv6 Enabled, MLO mode) are not followed by an immediate refresh; DNS caching and possibly MLO mode reboot the mesh. Their state updates on the next scheduled poll.
- **A change that already matches the current state is not sent.** Some eero writes reboot every eero on the network, so repeated writes are skipped.
- **Rate limiting.** When the eero API rate-limits a request, that tier's interval doubles on each limited poll, up to 15 minutes (never shorter than the tier's normal interval), and returns to normal after the next successful poll. The error says when the next poll is.
- **Setup.** Only the fast tier has to succeed for the integration to load. If the hourly or daily tier fails, only its own entities are unavailable until its next successful poll.
- **Failures.** A failed poll makes the affected entities unavailable rather than showing stale values. An expired session starts re-authentication.
- **New devices.** A client that joins the network gets its entities on the next fast poll, without a reload, if the client filter allows it. New eero ports appear after the next daily poll.

## Supported functions

Entities are created per device. Entity names below are the English names; with the default options, a device is named after the network plus the resource (e.g. `Home Kids`) and entity IDs follow from that, e.g. `switch.home_kids_paused`.

Legend:

- **Plus**: only created when the network has an eero Plus subscription.
- **Activity**: only created when selected in the activity metrics step.
- **Disabled**: created disabled; enable it on the entity's settings page.

An entity is only created when the network reports the feature it reads, so not every network has all of them.

### Network

| Entity | Platform | Description | Notes |
| --- | --- | --- | --- |
| Guest Network | switch | Turns the guest network on or off. Attributes: guest network name, connected guest clients. | |
| Guest network name | text | The guest network's name. | |
| Guest network password | text | Sets the guest password. Write-only: its state is never shown. Changing it disconnects guest clients. | |
| Band Steering | switch | Band steering. | |
| Smart Queue Management | switch | SQM. | |
| UPnP | switch | UPnP. | |
| WPA3 | switch | WPA3. | |
| IPv6 Enabled | switch | IPv6 upstream. | |
| Local DNS Caching | switch | Local DNS caching. Changing it reboots every eero a few minutes later. | |
| 5 GHz Band Paused | switch | Pauses the 5 GHz band. Attribute: expiration. | |
| Power saving | switch | Power saving. | |
| 802.11r fast transition | switch | 802.11r fast transition. | Daily tier |
| Thread Enabled | switch | Thread. Attributes when on: network name, channel, PAN ID, extended PAN ID (no keys). | Daily tier |
| Ad Blocking | switch | Network-wide ad blocking. | Plus |
| Advanced Security | switch | Blocks malware and phishing. | Plus |
| Dynamic DNS | switch | eero's dynamic DNS. Attribute: domain. | Plus |
| Backup Internet Enabled | switch | Backup internet through another network. | Plus |
| MLO mode | select | Multi-Link Operation mode: disabled, single or multi. | Only where the network reports it |
| Preferred Update Time | select | The hour in which eero installs firmware updates. | |
| Connected Clients | sensor | Number of connected clients, with per-category counts as attributes. | |
| Connected Guest Clients | sensor | Number of connected guest clients. | |
| Download Speed, Upload Speed | sensor | Result of the last speed test. Attribute: last updated. | |
| Public IP | sensor | Public IP address. | |
| Gateway IP | sensor | Gateway eero's IP. Attributes: MAC address, name. | |
| WAN Router IP | sensor | Upstream router IP. Attribute: subnet mask. | |
| Status | sensor | Network status. | |
| DNS mode | sensor | `automatic` or `custom`. | |
| Reboot | button | Reboots every eero on the network. | |
| Run Speed Test | button | Starts a speed test; the result appears in Download Speed and Upload Speed about a minute later. | |
| Run Internet Backup Test | button | Checks the internet backup connection. | eero Plus |
| Reservations | sensor | Number of DHCP reservations. | Daily tier |
| Port forwards | sensor | Number of port forwards. | Daily tier |
| Ad Blocking Status | sensor | Whether ad blocking is off, on for the network, or on per profile. | Plus |
| Data Usage Day / Week / Month | sensor | Download plus upload bytes; download and upload as attributes. | Activity (day and month need Plus) |
| Unprofiled data usage | sensor | Today's data usage of devices without a profile. | Activity |
| Eeros data usage summary | sensor | Today's data usage across all eeros. | Activity |
| Ad Blocks, Threat Blocks, Scans (Day / Week / Month) | sensor | Counters from eero Plus. | Activity, Plus |
| Unread notifications | binary_sensor | Whether the eero app has unread notifications. | Activity |
| App events | event | Fires `app_event` for each new event in the eero app's activity feed, with the event's data as attributes. | Activity |

### eero (gateway or extender)

| Entity | Platform | Description | Notes |
| --- | --- | --- | --- |
| Status Light | light | The eero's status LED: on, off and brightness. | |
| Reboot | button | Reboots this eero. | |
| Firmware | update | Installed and latest firmware, with release notes. Installing updates every eero on the network at once. | Latest version from the daily tier |
| Status | sensor | The eero's status. | |
| Connected Clients | sensor | Clients connected to this eero; their names in the `clients` attribute. | |
| Data Usage Day / Week / Month | sensor | This eero's data usage. | Activity (day and month need Plus) |
| Port N connection status | sensor | Connection status of each wired port. | Daily tier |
| Port N negotiated speed | sensor | Negotiated link speed of each wired port, in Mbit/s. | Daily tier |
| Enable/Disable port N, port N data, port N PoE, port N security; Restart port N power | button | Port actions, one per action the port offers. | Disabled, daily tier |

### eero Beacon

A Beacon has the eero entities above, plus:

| Entity | Platform | Description |
| --- | --- | --- |
| Nightlight Mode | select | `disabled`, `ambient` or `schedule`. |
| Nightlight Brightness | number | Nightlight brightness, in percent. |
| Nightlight On, Nightlight Off | time | Start and end of the nightlight schedule. |

### Profile

| Entity | Platform | Description | Notes |
| --- | --- | --- | --- |
| (profile name) | device_tracker | `home` while any device in the profile is connected. | |
| Connected | binary_sensor | Whether any device in the profile is connected. | |
| Paused | switch | Pauses internet access for every device in the profile. | |
| Bedtime | switch | Turns the profile's bedtime schedule on or off. | Daily tier |
| Bedtime weekday start / end, Bedtime weekend start / end | time | The bedtime schedule's times. | Daily tier |
| Block Apps | binary_sensor | Whether any apps are blocked; the list in the `blocked_apps` attribute. Set it with [`eero.set_blocked_apps`](#action-eeroset_blocked_apps). | |
| Connected Clients | sensor | Devices of the profile that are connected; their names in the `clients` attribute. | |
| Last Active | sensor | When a device of the profile was last active. | |
| Ad Blocking | switch | Ad blocking for this profile. | Plus |
| Adult, Chat and Messaging, Gaming, Illegal or Criminal, Shopping, Social Media, Streaming, Violent Content Filter | switch | eero Plus content filters. | Plus |
| SafeSearch Content Filter | switch | Enforces SafeSearch. | Plus |
| YouTube Restricted Content Filter | switch | YouTube restricted mode. | Plus |
| Data Usage, Ad Blocks, Threat Blocks, Scans (Day / Week / Month) | sensor | Per-profile activity. | Activity (all but data usage week need Plus) |

### Client (wired or wireless device)

| Entity | Platform | Description | Notes |
| --- | --- | --- | --- |
| (device name) | device_tracker | `home` while connected (see consider home). Attributes when connected: `connected_to`, `connection_type`, `ip`, `mac`, `host_name`, `manufacturer`, `network_name`; wireless clients also `band`, `channel`, `channel_width_rx`. | |
| Connected | binary_sensor | Whether the device is connected. Wireless clients add band, channel and bandwidth attributes. | |
| Paused | switch | Pauses the device's internet access. | |
| Blocked | switch | Blocks the device from the network, or unblocks it. | Daily tier |
| Profile | select | Moves the device to a profile, or to none. | Only on networks with at least one profile selected |
| IP Address | sensor | The device's IP address. | |
| Last Active | sensor | When the device was last active. | |
| Signal Strength | sensor | Wi-Fi signal, in dBm. | Wireless only |
| Download Rate, Upload Rate | sensor | Current throughput, in Mbit/s. | |
| Allow Internet Backup | switch | Whether the device may use backup internet. | Plus |
| Data Usage, Ad Blocks, Threat Blocks, Scans (Day / Week / Month) | sensor | Per-device activity. | Activity (all but data usage week need Plus) |

### Backup network

| Entity | Platform | Description | Notes |
| --- | --- | --- | --- |
| Status | sensor | Result of the last backup check; attributes `checked` and, on failure, `failure_reason`. | Daily tier |
| Auto-Join Enabled | switch | Whether this network joins the backup network automatically. | Plus, daily tier |

Backup networks only exist on networks with eero Plus.

## Actions

The integration registers these actions. They are available as soon as the integration is installed, and act on every loaded eero entry. If one target network fails, the others still run, and the errors are reported together at the end. `target_network` takes a network's name or its ID, or a list of them.

### Action: `eero.set_blocked_apps`

Sets the list of blocked apps for one or more profiles. Requires eero Plus. Only profiles selected in the integration's resources are affected.

| Field | Required | Description |
| --- | --- | --- |
| `blocked_apps` | Yes | List of apps to block. An empty list unblocks all apps. Valid values: `activision_blizzard`, `alibaba`, `amazon`, `amazon_video`, `apple`, `apple_itunes`, `audible`, `badoo`, `blizzard`, `bytedance`, `cbs`, `clash_of_clans`, `clash_royale`, `costco`, `craigslist`, `discord`, `disney`, `disney_plus`, `disqus`, `ebay`, `electronic_arts`, `epic_games`, `etsy`, `facebook`, `facebook_messenger`, `gmail`, `google_hangouts`, `google_voice`, `hbo`, `hulu`, `iheartradio`, `instagram`, `kik`, `last.fm`, `linkedin`, `microsoft_outlook`, `microsoft_teams`, `minecraft`, `netflix`, `nintendo`, `okcupid`, `pandora`, `pinterest`, `playstation`, `plex`, `reddit`, `roblox`, `signal`, `skype`, `slack`, `snapchat`, `soundcloud`, `spotify`, `steam`, `stream`, `target`, `ticketmaster`, `tiktok`, `tinder`, `tumblr`, `twitch`, `twitter`, `ubisoft`, `vimeo`, `walmart`, `wechat`, `whatsapp`, `xbox`, `xbox_live`, `yahoo_mail`, `youtube`, `zoom_video`. |
| `target_profile` | No | Profile name(s) or ID(s). Default: all configured profiles. |
| `target_network` | No | Network name(s) or ID(s). Default: all networks. |

```yaml
action: eero.set_blocked_apps
data:
  blocked_apps:
    - tiktok
    - roblox
  target_profile: Kids
  target_network: Home
```

### Action: `eero.create_reservation`

Creates a DHCP reservation. Nothing is sent if an identical reservation (same IP and MAC) already exists.

| Field | Required | Description |
| --- | --- | --- |
| `target_network` | Yes | Network name(s) or ID(s). |
| `ip` | Yes | The reserved IP address. |
| `mac` | Yes | The device's MAC address. |
| `description` | No | A label for the reservation. |
| `public_static_ip` | No | Whether the reservation also has a public static IP. |

```yaml
action: eero.create_reservation
data:
  target_network: Home
  ip: 192.168.4.100
  mac: "aa:bb:cc:dd:ee:ff"
  description: Office printer
```

### Action: `eero.delete_reservation`

Deletes a DHCP reservation.

| Field | Required | Description |
| --- | --- | --- |
| `target_network` | Yes | Network name(s) or ID(s). |
| `reservation` | Yes | The reservation's ID, as reported by the eero API. The IDs are listed under the network's `reservations` in the integration's diagnostics download. |
| `delete_forwards` | No | Also delete port forwards that point at this reservation's IP. |

```yaml
action: eero.delete_reservation
data:
  target_network: Home
  reservation: "1234567"
  delete_forwards: true
```

### Action: `eero.create_port_forward`

Creates a port forward. Nothing is sent if a forward with the same IP, ports and protocol already exists.

| Field | Required | Description |
| --- | --- | --- |
| `target_network` | Yes | Network name(s) or ID(s). |
| `ip` | Yes | The internal IP address to forward to. |
| `client_port` | Yes | The internal port. |
| `gateway_port` | Yes | The external port. |
| `protocol` | Yes | The protocol, e.g. `tcp` or `udp`. |
| `description` | No | A label for the forward. |
| `enabled` | No | Whether the forward is active. Default: `true`. |

```yaml
action: eero.create_port_forward
data:
  target_network: Home
  ip: 192.168.4.100
  client_port: 8080
  gateway_port: 8080
  protocol: tcp
  description: Home server
```

### Action: `eero.delete_port_forward`

Deletes a port forward.

| Field | Required | Description |
| --- | --- | --- |
| `target_network` | Yes | Network name(s) or ID(s). |
| `forward` | Yes | The forward's ID, as reported by the eero API. The IDs are listed under the network's `forwards` in the integration's diagnostics download. |

```yaml
action: eero.delete_port_forward
data:
  target_network: Home
  forward: "7654321"
```

### Action: `eero.set_custom_dns`

Sets custom DNS servers for a network, or switches it back to automatic (ISP-provided) DNS.

> **Warning:** every DNS change reboots the whole mesh a few minutes later, and devices lose their connection while the eeros restart. The action only writes the address families that actually change, in a single write, and sends nothing when the network already has the requested settings.

| Field | Required | Description |
| --- | --- | --- |
| `target_network` | Yes | Network name(s) or ID(s). |
| `ipv4` | No | IPv4 DNS server addresses. A family not supplied is left as it is. |
| `ipv6` | No | IPv6 DNS server addresses. A family not supplied is left as it is. |
| `automatic` | No | Switch both families back to automatic DNS, ignoring `ipv4` and `ipv6`. Default: `false`. |

```yaml
action: eero.set_custom_dns
data:
  target_network: Home
  ipv4:
    - 1.1.1.1
    - 1.0.0.1
  ipv6:
    - "2606:4700:4700::1111"
```

## Examples

The examples assume a network named `Home`, a profile named `Kids` and devices named `Alex Phone` and `Game Console`, with the default naming options.

### Pause a profile at night

```yaml
automation:
  - alias: "Pause the Kids profile at night"
    triggers:
      - trigger: time
        at: "21:30:00"
    actions:
      - action: switch.turn_on
        target:
          entity_id: switch.home_kids_paused
  - alias: "Resume the Kids profile in the morning"
    triggers:
      - trigger: time
        at: "07:00:00"
    actions:
      - action: switch.turn_off
        target:
          entity_id: switch.home_kids_paused
```

For a fixed nightly schedule, the profile's own **Bedtime** switch and times do the same thing on the eero side.

### Notify when a device connects

```yaml
automation:
  - alias: "Alex is home"
    triggers:
      - trigger: state
        entity_id: device_tracker.home_alex_phone_wireless
        from: not_home
        to: home
    actions:
      - action: notify.notify
        data:
          message: "Alex's phone joined the Wi-Fi."
```

The tracker changes state on the next fast poll after the phone connects, so expect a delay of up to the polling interval.

### Block a device while homework mode is on

```yaml
automation:
  - alias: "Block the game console during homework"
    triggers:
      - trigger: state
        entity_id: input_boolean.homework_mode
        to:
          - "on"
          - "off"
    actions:
      - action: "switch.turn_{{ trigger.to_state.state }}"
        target:
          entity_id: switch.home_game_console_wired_blocked
```

## Known limitations

- **Amazon login is not supported.** Accounts that sign in to eero with Amazon cannot be used. Workaround: create a separate eero account with an email address or phone number and add it as an admin of the network in the eero app ([step-by-step instructions](https://github.com/schmittx/home-assistant-eero/issues/77#issuecomment-1960875926)).
- **Cloud polling only.** There is no local API and no push. Changes made in the eero app show up on the next poll of the tier that holds them, which for daily-tier data (bedtime schedules, block list, reservations, port forwards, Thread, firmware) can be up to a day.
- **App events arrive up to an hour late,** because the hourly tier fetches them. Events that happened before Home Assistant started, or while it was stopped, are not replayed.
- **DNS changes reboot the mesh.** The Local DNS Caching switch and the `eero.set_custom_dns` action cause every eero to reboot a few minutes later.
- **Firmware updates are network-wide.** Installing from any eero's update entity updates every eero on the network; a specific version cannot be chosen.
- **Some response formats are not verified against a real network.** The MLO mode, port, power saving, unprofiled data usage, eeros data usage summary and app event entities read API fields whose shape has not yet been confirmed on live hardware; they may show unknown values or be missing on some networks.
- **Passpoint is not supported,** because the API offers no way to read its current state.
- **The guest password is write-only,** but Home Assistant itself records the data of the `text.set_value` call that sets it, for example in automation traces.
- **eero Plus features** (content filters, ad blocking, advanced security, dynamic DNS, backup networks, most activity metrics) need the subscription.
- **The polling timeout is at most 30 seconds,** which is the limit of the `eero-api` client.
- **With the include filter, new devices are not added.** Only clients selected in the options get entities; use the exclude filter to pick up new devices automatically.

## Troubleshooting

### The integration asks to re-authenticate

**Symptom:** a "Reauthenticate eero account" notice appears, and entities are unavailable.

**Description:** the eero session expired or was revoked (for example after signing out of all sessions in the eero app).

**Resolution:** open the notice (or **Settings** > **Devices & services** > **eero**), start the re-authentication, and enter the login and the code eero sends. It must be the same account the entry was set up with; another account is refused with "The verified account is not the account this entry was set up with".

### A Repairs issue appears

Go to **Settings** > **System** > **Repairs**. The integration raises three kinds of issue, all of which clear themselves:

| Issue | Meaning | What to do |
| --- | --- | --- |
| eero Plus required for *feature* | The network is not entitled to a feature that needs eero Plus. The entities that depend on it are not created. | Subscribe to eero Plus, or ignore the issue. It clears once the subscription is active. |
| *feature* is not available | The hardware or the account does not support the feature. | Nothing; it clears if the feature becomes available. |
| Network *network* is unavailable | A configured network is no longer found: it was removed from the account, or the account lost access. Its entities are unavailable; other networks keep working. | Deselect the network in **Configure**, or restore access in the eero app. |

### Entities are unavailable or the log mentions rate limiting

**Symptom:** entities become unavailable and the log shows "Rate limited by the eero API; the next poll is in N seconds", "Timed out talking to the eero API" or "The eero API rejected the request".

**Resolution:** the integration backs off by itself on rate limits (see [Data updates](#data-updates)) and recovers on the next successful poll. If it happens often, raise the polling interval and select fewer activity metrics, since each one is an extra request per hour.

### A device tracker flips between home and away

Wi-Fi devices that sleep drop off the network briefly. Set **Consider home interval** in **Configure** > **Miscellaneous options** to a value longer than the polling interval, for example 10 minutes with the default 300-second interval.

### A device is missing

Check the client filter in **Configure** > **Network resources**: with **Include selected** only the selected devices get entities. eero Plus entities are not created without the subscription, and activity sensors only when selected in the activity metrics step.

### A device that is gone stays listed

A client device that the eero no longer reports as connected can be deleted from its device page in Home Assistant (**Delete**). It is added back if it reconnects and the client filter allows it.

### Enable debug logging

Enable debug logging from the integration page (**Enable debug logging**), reproduce the problem, then disable it to download the log. Or add this to `configuration.yaml` and restart:

```yaml
logger:
  default: warning
  logs:
    custom_components.eero: debug
    eero: debug
```

`custom_components.eero` is the integration, `eero` is the `eero-api` client. Tokens, passwords and verification codes are not logged.

### Download diagnostics

On the integration page, open the menu and select **Download diagnostics**. The file contains the configuration and the latest API data, with tokens, passwords, keys, email addresses and phone numbers redacted. Attach it to bug reports.

### Save API responses

For problems with a particular API response, turn on **Save redacted server responses** in **Reconfigure** or the advanced options. Responses are written to `config/.storage/eero_responses/`, with secrets redacted and login exchanges left out. Turn it off again when done.

Report problems at the [issue tracker](https://github.com/fulviofreitas/home-assistant-eero/issues).

## Removing the integration

This integration follows standard integration removal:

1. Go to **Settings** > **Devices & services** and select **eero**.
2. Open the menu (three dots) of the entry and select **Delete**. Repeat for each eero entry.
3. To remove the files as well, open HACS, find **eero**, and select **Remove** (or, for a manual install, delete `config/custom_components/eero`), then restart Home Assistant.

If you turned on saved responses, also delete `config/.storage/eero_responses/`. If you created an eero account just for Home Assistant, remove it as an admin in the eero app.

## Credit

- [schmittx/home-assistant-eero](https://github.com/schmittx/home-assistant-eero) - the original integration
- [@343max's eero-client project](https://github.com/343max/eero-client) - Basic API auth and refresh methods
- [@jrlucier's eero_tracker project](https://github.com/jrlucier/eero_tracker) - Initial Home Assistant idea
