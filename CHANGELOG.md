# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/Robbe654321/lifepowr-flexio-ha/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Robbe654321/lifepowr-flexio-ha/releases/tag/v0.1.0
