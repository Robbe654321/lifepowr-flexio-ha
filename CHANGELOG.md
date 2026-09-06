# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.1] — 2026-09-06

### Fixed

- The brand icons moved from `brand/` in the repository root to
  `custom_components/lifepowr/brand/`, which is where the HACS action looks
  for them. Found there, its brands check passes without waiting for the
  separate pull request against `home-assistant/brands`; the validation
  workflow no longer has to ignore that check. The icons now ship with the
  integration, so Home Assistant has them locally.

## [0.2.0] — 2026-09-06

### Fixed

- **Battery energy was wildly overstated.** `TotalInvPowerFiltered` is the
  inverter's total AC power with solar included, not the battery's own flow, so
  every sunny hour was recorded as a battery discharge. One real installation
  showed 77 kWh discharged against 10 kWh charged on a battery of roughly
  34 kWh usable. The integration now derives `battery_power` as
  `inverter − PV` and exposes it as its own sensor; the battery charge and
  discharge totals are integrated from it instead of the inverter reading.

  Existing installations must delete the statistics of their battery charge and
  discharge sensors, which hold the bad history.

### Added

- **Battery power** sensor, derived rather than reported.
- A ready-made four-view Lovelace dashboard, in English and Dutch, under
  `dashboards/`. Live power with sparklines, the Energy dashboard's own cards,
  a battery view, and the inverter-versus-battery distinction spelled out.
  Core cards only — nothing extra to install.
- Six cumulative kWh sensors, so the Energy dashboard can be configured
  straight from the integration: solar production, household consumption, grid
  import, grid export, battery charge and battery discharge energy. Each is a
  trapezoidal Riemann sum over the box's live power, `total_increasing`, and
  restored across restarts. The bidirectional grid and battery flows are split
  into two positive-only directions so importing and exporting do not cancel
  out, and gaps longer than five minutes are skipped rather than guessed at.
- Configurable poll interval, 2 to 300 seconds, via **Configure** on the
  integration. The box is local and answers in milliseconds, so the vendor
  app's few-second refresh rate is reachable.

### Changed

- Default poll interval lowered from 15 to 10 seconds.
- Inverter power is now named "Inverter power (total AC)", to make clear it is
  not the battery.

### Removed

- `packages/lifepowr_energy.yaml`. The integration now creates those totals
  itself, with the same entity IDs and no YAML, `configuration.yaml` edit or
  restart. Anyone using the package should delete it and remove its leftover
  entities, otherwise the built-in sensors fall back to `…_energy_2` entity IDs
  because the old ones are still registered.

## [0.1.0] — 2026-09-04

First release. Verified against firmware 1.148.10 driving a Goodwe
GW12K-ET-20.

### Added

- Config flow with host entry, connection test and reconfigure support.
- Twelve sensors: solar production, household consumption, grid power,
  inverter power, battery state of charge, state of health, voltage and
  current, electricity price, generic load available power, inverter setpoint,
  and a diagnostic measurement timestamp.
- A `number` entity for the generic load's maximum electricity price, written
  with `POST /api/ems/generic-load`.
- A diagnostic sensor for the paired converter, and the firmware version on the
  device page.
- Diagnostics download listing the detected layout and every parsed field.
- English and Dutch translations.
- `packages/lifepowr_energy.yaml`, deriving six kWh totals for the Energy
  dashboard from the box's instantaneous power readings.
- `scripts/check_box.py`, which verifies the field mapping against real
  hardware using only the standard library.
- `docs/api-notes.md`, recording every discrepancy between the vendor
  documentation and the box.

### Notes on the API

The published documentation is wrong about six things, all worked around here:
the measurements endpoint path, the generic load endpoint path, the write
method, the capitalisation of `TotalInvPowerFiltered`, the spelling of
`consumptionElectricityPrice`, and — most consequentially — the unit of every
power field, which is watts rather than the documented kilowatts.

The API also signs consumption negative. Grid power and household consumption
are negated so they read positively in Home Assistant; battery flow keeps its
raw sign, where positive already means discharging.

[Unreleased]: https://github.com/Robbe654321/lifepowr-flexio-ha/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/Robbe654321/lifepowr-flexio-ha/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/Robbe654321/lifepowr-flexio-ha/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Robbe654321/lifepowr-flexio-ha/releases/tag/v0.1.0
