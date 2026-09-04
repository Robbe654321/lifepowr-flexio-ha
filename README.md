# LIFEPOWR FlexiO for Home Assistant

Home Assistant integration for the [LIFEPOWR](https://www.lifepowr.io) **FlexiObox**
home energy management system, using its local REST API. No cloud, no account,
no polling of anyone's servers — everything stays on your own network.

[![hacs][hacs-badge]][hacs]

## Supported devices

Any FlexiObox serving the *FlexiO Device API* on the local network, verified
against firmware 1.148.3. The box must be on the same network as your Home
Assistant instance; its on-device API documentation is at
`http://myio.local/api/docs`.

## Features

- **Local polling** every 15 seconds over HTTP, no authentication required.
- **Automatic schema detection.** LIFEPOWR's website documentation disagrees
  with the on-device OpenAPI spec about endpoint paths, the write method, and
  the spelling of several fields. The integration probes the box on first setup
  and adapts to whichever layout and spelling your firmware actually uses.
- **Writable price cap** for the generic load, when the box exposes it.
- **Only real entities.** Measurements your box does not report are not created,
  rather than showing up as permanently unknown.
- **Energy dashboard ready** via the included package (see below).

### Entities

| Entity | Unit | Notes |
| --- | --- | --- |
| Solar production | kW | Total PV production |
| Household consumption | kW | Load power |
| Grid power | kW | Bidirectional; sign convention depends on firmware |
| Inverter power | kW | Bidirectional battery flow |
| Inverter setpoint | kW | Only on firmware that reports `powerSetpoint` |
| Generic load available power | kW | Generic Load Controller |
| Battery state of charge | % | |
| Battery state of health | % | |
| Battery voltage | V | Disabled by default |
| Battery current | A | Disabled by default |
| Electricity price | €/kWh | Current consumption price |
| Last measurement | timestamp | Diagnostic, disabled by default |
| Converter | — | Diagnostic; the paired inverter, from `/api/info/converter` |

One writable entity:

| Entity | Unit | Notes |
| --- | --- | --- |
| Generic load maximum price | €/kWh | `number`; posts to `/api/ems/generic-load` |

## Installation

### HACS (recommended)

1. In HACS, open the three-dot menu → **Custom repositories**.
2. Add `https://github.com/robbewillemsens/lifepowr-flexio-ha` with category
   **Integration**.
3. Install **LIFEPOWR FlexiO** and restart Home Assistant.
4. **Settings → Devices & services → Add integration → LIFEPOWR FlexiO**.

### Manual

Copy `custom_components/lifepowr` into your `config/custom_components/`
directory and restart Home Assistant.

## Configuration

The only setting is the host. `myio.local` is the default and works on most
networks; if mDNS is not resolving (common with VLANs or some routers), enter
the box's IP address instead — you can find it in your router's DHCP lease
table. Both a bare host and a full `http://…` URL are accepted.

If the box's address changes later, use **Reconfigure** on the integration
rather than deleting and re-adding it, so entity history is preserved.

## Energy dashboard

The FlexiObox reports live power only, so cumulative energy has to be derived.
[`packages/lifepowr_energy.yaml`](packages/lifepowr_energy.yaml) does this:
it splits the bidirectional grid and battery power into directional sensors and
integrates each one into a `total_increasing` kWh sensor, ready to be selected
in **Settings → Dashboards → Energy**.

Copy it into `config/packages/`, add

```yaml
homeassistant:
  packages: !include_dir_named packages
```

to `configuration.yaml`, restart, and map the sensors as described in the
comments at the bottom of that file.

> **Check the sign convention once.** The package assumes positive grid power
> means import and positive inverter power means discharge. Watch both sensors
> on a sunny moment; if your box is the other way round, swap the `max`/`min`
> expressions in the template sensors.

## Endpoints used

| Endpoint | Purpose |
| --- | --- |
| `GET /api/ems/measurements` | All live measurements |
| `GET /api/ems/generic-load` | Generic load state and price cap |
| `POST /api/ems/generic-load` | Sets the price cap (`{"newMaxPrice": …}`) |
| `GET /api/info/version` | Firmware version, shown on the device page |
| `GET /api/info/converter` | Paired converter, exposed as a sensor |

Older firmware serving `/api/ems`, `/api/ems/load_control`, or one endpoint per
measurement is detected automatically and handled read-only.

## Data updates

The integration polls the box every 15 seconds. The API exposes filtered,
instantaneous values only — there is no historical data to backfill, so
long-term statistics start from the moment you install the integration.

## Known limitations

- **Local network only.** The API is not reachable from outside your home
  network, and this integration makes no attempt to work around that. If your
  Home Assistant instance runs elsewhere, put it on the same network (or the
  same Tailscale/VPN subnet as the box).
- **No authentication.** The API is unauthenticated by design; anyone on your
  LAN can read it. Segment your network accordingly.
- **One writable value.** Only the generic load's price cap can be set; the
  inverter itself cannot be commanded through this API. On firmware that does
  not expose `/api/ems/measurements`, the `number` entity is not created at all,
  because the write endpoint does not exist there either.
- **No historical data**, and no per-phase or per-string detail. Long-term
  statistics start when you install the integration.

## Troubleshooting

**"Failed to connect"** — ping the host from the machine running Home
Assistant. If `myio.local` fails but the IP works, mDNS is not crossing your
network; use the IP address.

**"That host responded, but it does not look like a FlexiObox"** — something is
answering on that address but serving no recognisable measurements. Open
`http://<host>/api/docs` in a browser to confirm you have the right device, and
open an issue with the output of `curl http://<host>/api/ems/measurements` so
the field mapping can be extended.

**Entities are missing** — only measurements the box actually reports become
entities. Download diagnostics from the integration page to see exactly which
fields were found.

## Removal

Delete the integration from **Settings → Devices & services**. If you installed
the energy package, also remove `packages/lifepowr_energy.yaml` and restart.

## Contributing

This integration is written to Home Assistant core standards
(`quality_scale.yaml` tracks the remaining gaps) with the intention of
submitting it to `home-assistant/core`. Field mappings from other firmware
versions are especially welcome — attach a raw
`curl http://myio.local/api/ems/measurements` response to an issue.

## Disclaimer

Not affiliated with or endorsed by LIFEPOWR.

[hacs]: https://github.com/hacs/integration
[hacs-badge]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg
