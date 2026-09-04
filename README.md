<h1 align="center">LIFEPOWR FlexiO for Home Assistant</h1>

<p align="center">
  Local-polling integration for the <a href="https://www.lifepowr.io">LIFEPOWR</a>
  <strong>FlexiObox</strong> home energy management system.<br>
  No cloud, no account, no API key — everything stays on your own network.
</p>

<p align="center">
  <a href="https://github.com/hacs/integration"><img alt="HACS custom repository" src="https://img.shields.io/badge/HACS-custom-41BDF5.svg"></a>
  <a href="https://github.com/Robbe654321/lifepowr-flexio-ha/actions/workflows/validate.yml"><img alt="Validation status" src="https://github.com/Robbe654321/lifepowr-flexio-ha/actions/workflows/validate.yml/badge.svg"></a>
  <a href="https://github.com/Robbe654321/lifepowr-flexio-ha/releases"><img alt="Latest release" src="https://img.shields.io/github/v/release/Robbe654321/lifepowr-flexio-ha?sort=semver"></a>
  <img alt="Home Assistant 2025.2+" src="https://img.shields.io/badge/Home%20Assistant-2025.2%2B-41BDF5.svg">
  <a href="LICENSE"><img alt="MIT licence" src="https://img.shields.io/badge/licence-MIT-blue.svg"></a>
</p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/architecture-dark.svg">
    <img alt="The FlexiObox serves a local API; the integration polls it every 15 seconds, normalises units and signs, and exposes 12 sensors and one number in Home Assistant." src="docs/architecture-light.svg" width="100%">
  </picture>
</p>

---

## Why this exists

The FlexiObox has a perfectly good local API and no Home Assistant integration.
It also has documentation that disagrees with the box itself on six separate
points — including the unit of every power reading, which is off by a factor of
1000. This integration is written against the real hardware, and
[`docs/api-notes.md`](docs/api-notes.md) records every discrepancy so the next
person does not have to rediscover them.

## Supported devices

Any FlexiObox serving the *FlexiO Device API* on your local network. Verified
against **firmware 1.148.10** driving a **Goodwe GW12K-ET-20**. Its on-device
API documentation lives at `http://myio.local/api/docs`.

Older firmware exposing `/api/ems`, `/api/ems/load_control`, or one endpoint
per measurement is detected automatically and handled read-only.

## Installation

### HACS

1. HACS → three-dot menu → **Custom repositories**.
2. Add `https://github.com/Robbe654321/lifepowr-flexio-ha`, category
   **Integration**.
3. Install **LIFEPOWR FlexiO**, then restart Home Assistant.
4. **Settings → Devices & services → Add integration → LIFEPOWR FlexiO**.

### Manual

Copy `custom_components/lifepowr` into your `config/custom_components/`
directory and restart Home Assistant.

## Configuration

One setting: the host. `myio.local` is the default and works on most networks.
If mDNS is not resolving — common with VLANs, guest networks, or some routers —
enter the box's IP address instead; your router's DHCP lease table has it. Both
a bare host and a full `http://…` URL are accepted.

If the box's address changes later, use **Reconfigure** on the integration
rather than deleting and re-adding it, so entity history survives.

## Entities

One device, with entities created only for the measurements your box actually
reports — nothing shows up permanently unknown.

| Entity | Unit | Notes |
| --- | --- | --- |
| Solar production | W | Total PV production |
| Household consumption | W | Positive while consuming |
| Grid power | W | Positive importing, negative exporting |
| Inverter power | W | Positive discharging, negative charging |
| Battery state of charge | % | |
| Battery state of health | % | |
| Battery voltage | V | |
| Battery current | A | Negative while charging |
| Electricity price | €/kWh | Current consumption price |
| Generic load available power | W | Generic Load Controller |
| Inverter setpoint | W | Only on firmware reporting `powerSetpoint` |
| Last measurement | timestamp | Diagnostic, disabled by default |
| Converter | — | Diagnostic; the paired inverter |
| **Generic load maximum price** | €/kWh | **Writable** `number` |

## Units and sign convention

Two things the vendor documentation gets wrong, both confirmed against real
hardware. If you only read one section, read this one.

**The API reports watts, not kilowatts.** The website's table says kW for every
power field. A box reporting `-5341.34` for grid power is drawing 5.3 kW — as
kilowatts that would be 5.3 megawatts.

**Consumption is negative.** The API uses a load convention: importing from the
grid, consuming in the house and charging the battery are all negative. Solar
production is positive. Home Assistant expects the opposite for grid and
consumption, so the integration negates those two. Battery flow keeps its raw
sign, where positive already means discharging.

<details>
<summary>The measurement that settles it</summary>

```
totalPVPowerFiltered       1160.6   TotalInvPowerFiltered     -2456.2
LoadPowerFiltered         -3002.1   MeterPowerFiltered        -5341.3
batteryVoltageInvFiltered   421.4   batteryCurrentInvFiltered    -8.31
```

Two independent identities, both closing within 3%:

| Identity | Computed | Reported | Gap |
| --- | --- | --- | --- |
| `grid ≈ load + inverter` | −5458 W | −5341 W | 2.2% — filter lag |
| `battery DC ≈ inverter − PV` | −3617 W | −3500 W | 3.3% — conversion loss |

421.4 V × −8.31 A is 3.5 kW going into the battery, while the inverter pulls
2456 W from the grid plus 1161 W of solar. The 117 W difference is the
conversion loss, and it appears in both identities. That is only consistent in
watts, with this sign convention.

Home Assistant then shows: grid **5341 W importing**, consumption **3002 W**,
solar **1161 W**, battery **−2456 W charging**.

</details>

## Verify against your own box

`scripts/check_box.py` checks the field mapping on real hardware without
installing anything — standard library only, no Home Assistant, no pip:

```console
$ python3 scripts/check_box.py              # or: check_box.py 192.168.1.20
```

It reports which endpoints answer, which fields are recognised, warns about any
field it does not know yet, re-runs both energy balances against your live
readings, and checks that the timestamp resolves to roughly now. It writes
nothing unless you pass `--set-max-price 0.30`, which exercises the one write
endpoint.

**If it flags an unmapped field, please [open an issue][new-issue]** with the
name and value — that is exactly how this integration learns about firmware
variants.

## Energy dashboard

The box reports live power only, so cumulative energy has to be derived.
[`packages/lifepowr_energy.yaml`](packages/lifepowr_energy.yaml) splits the
bidirectional grid and battery power into directions and integrates each into a
`total_increasing` kWh sensor.

Copy it into `config/packages/`, add this to `configuration.yaml`:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

restart, then map the sensors in **Settings → Dashboards → Energy**:

| Energy dashboard slot | Entity |
| --- | --- |
| Grid consumption | `sensor.flexio_grid_import_energy` |
| Return to grid | `sensor.flexio_grid_export_energy` |
| Solar production | `sensor.flexio_solar_production_energy` |
| Battery: energy in | `sensor.flexio_battery_charge_energy` |
| Battery: energy out | `sensor.flexio_battery_discharge_energy` |

Set `sensor.flexio_electricity_price` as the grid consumption source's *"use an
entity with current price"* option for live cost tracking.

The package reads the integration's already-normalised entities, so nothing in
it needs adjusting.

## Endpoints used

| Endpoint | Purpose |
| --- | --- |
| `GET /api/ems/measurements` | Every live measurement |
| `GET /api/ems/generic-load` | Generic load state and price cap |
| `POST /api/ems/generic-load` | Sets the price cap — `{"newMaxPrice": …}` |
| `GET /api/info/version` | Firmware version, shown on the device page |
| `GET /api/info/converter` | Paired converter, exposed as a sensor |

That is the entire API. See [`docs/api-notes.md`](docs/api-notes.md) for how
this differs from the published documentation.

## Data updates

Polled every 15 seconds. The API exposes filtered, instantaneous values only —
there is no history to backfill, so long-term statistics start the moment you
install the integration.

## Troubleshooting

<details>
<summary><strong>"Failed to connect"</strong></summary>

Ping the host from the machine running Home Assistant. If `myio.local` fails
but the IP address works, mDNS is not crossing your network — use the IP.

Home Assistant in Docker with a custom network, or on a different VLAN from the
box, will not resolve `.local` names at all.

</details>

<details>
<summary><strong>"That host responded, but it does not look like a FlexiObox"</strong></summary>

Something is answering on that address but serving no recognisable
measurements. Open `http://<host>/api/docs` in a browser to confirm you have
the right device, then run `scripts/check_box.py <host>` and
[open an issue][new-issue] with its output.

</details>

<details>
<summary><strong>Entities are missing</strong></summary>

Only measurements the box actually reports become entities. Download
diagnostics from the integration page to see exactly which fields were found
and which layout was detected.

</details>

<details>
<summary><strong>Power readings look wrong by a factor of 1000</strong></summary>

If your firmware genuinely reports kilowatts, `scripts/check_box.py` will say
so. Please [open an issue][new-issue] with its output and your firmware
version — the unit would then need to be detected rather than assumed.

</details>

## Known limitations

- **Local network only.** The API is unreachable from outside your home
  network, and this integration does not work around that. Put Home Assistant
  on the same network, or the same VPN subnet as the box.
- **No authentication.** The API is unauthenticated by design — anyone on your
  LAN can read it, and write the price cap. Segment your network accordingly.
- **One writable value.** Only the generic load's price cap can be set. The
  inverter itself cannot be commanded through this API. On firmware without
  `/api/ems/measurements` the `number` entity is not created at all, because
  the write endpoint does not exist there either.
- **No history, no per-phase or per-string detail.**

## Removal

Delete the integration from **Settings → Devices & services**. If you installed
the energy package, also remove `packages/lifepowr_energy.yaml` and restart.

## Contributing

Field mappings from other firmware versions are especially welcome — see
[CONTRIBUTING.md](CONTRIBUTING.md). The integration is written to Home
Assistant core standards; `custom_components/lifepowr/quality_scale.yaml`
tracks what is still missing for a core submission.

## Disclaimer

Not affiliated with, endorsed by, or supported by LIFEPOWR. LIFEPOWR and
FlexiO are their trademarks; this project just talks to the box.

[new-issue]: https://github.com/Robbe654321/lifepowr-flexio-ha/issues/new/choose
