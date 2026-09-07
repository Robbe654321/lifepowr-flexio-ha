# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- The hourly series is published on `Solar forecast now` as the `forecast`
  attribute, so it can be charted with a card of your own rather than only on
  the Energy dashboard. The README has an apexcharts-card example and the
  recorder exclusion to go with it.

### Fixed

- `Solar forecast now` no longer holds perfectly still for an hour and then
  jumps. It was returning the mean of whichever hour contained the moment,
  which is defensible and reads as a sensor that has stopped updating. An
  hourly mean is near enough the instantaneous value at that hour's midpoint,
  so the value between two midpoints is now interpolated: it follows the sun,
  and mid-hour it is closer to the truth than either neighbour. The energy
  totals still come from the hourly means and are unchanged.

### Changed

- The diagnostic sensor and the README no longer present the learned planes as
  a survey of the roof. They are the effective plane of each measured *source*,
  which is a weaker claim: one inverter often carries panels from more than one
  roof plane, and the single plane that best explains such a mixture comes out
  steeper and turned further from south than anything up there. Measured on a
  real installation whose owner knew the answer, a fitted plane read 32° where
  the roof is 14°, and forecast that inverter distinctly *better* than the true
  angle did (held-out R² 0.76 against 0.57) because it also absorbs the
  shading. On the site total the two were indistinguishable, 0.6636 against
  0.6628.

  So panel counts must not be derived from how the capacity splits between the
  planes: that assumes each plane is one orientation carrying its own honest
  share of the losses, which a mixture is not. The total capacity remains the
  solid number — on that installation within a few percent of both PVGIS and
  the measured energy.

  Also noted: a shallow plane barely has a bearing to find. At 14° of tilt
  every bearing from east to west lands within 14% of due south, against 29%
  at 45°, so a confident bearing on a plane the fit believes is steep may be
  neither.

## [0.3.0] — 2026-09-06

### Added

- **A solar forecast that works the roof out for itself.** Tilt, compass
  bearing and peak power per plane of panels are what every solar forecast
  asks for and almost nobody knows, and an installation that grew over time
  faces several directions at once. These are now recovered from the hourly
  production statistics the recorder already holds, by asking which
  combination of candidate orientations reproduces the measured history — a
  non-negative least squares problem, whose solution is naturally sparse, so
  only the orientations really on the roof survive.

  Shading is learned alongside the panels: one skyline height per compass
  direction, because a fit denied a skyline explains a missing evening by
  turning the panels east instead. The skyline is held continuous, since a
  plane's capacity and the trees in front of it are partly interchangeable
  and an unconstrained search cuts a notch exactly where an array faces.

  How many planes a roof gets, and whether a skyline earns its place, are
  decided on days held out of the fit rather than on how well they flatter the
  days they were fitted on.

- Six sensors: expected production now, today, the rest of today, tomorrow,
  when today should peak, and a diagnostic that shows the learned roof with
  the quality of the fit.
- The roof can be learned from any sensor with a longer record than the
  FlexiObox has, including an old inverter's kWh counter: an energy statistic
  is read through the recorder's own per-hour `change`, which is safer than
  differencing a running total by hand. For many installations that is the
  difference between forecasting today and forecasting next year. Several can
  be given: a site with two inverters is described twice rather than once, and
  each meter is fitted its own planes before they are pooled, which recovers
  noticeably sharper geometry than their sum. A meter that only re-reads what
  the others already saw — the one that replaced two string inverters, say —
  is detected where the records overlap and left out rather than counted
  twice; where they do not overlap it cannot be detected, and the log says so.
- The forecast can be picked as the solar forecast source on the Energy
  dashboard, where Home Assistant draws it behind the production bars — so it
  is checked against reality every day on the same chart.
- `lifepowr.learn_solar_model`, to redo the fit immediately after adding
  panels rather than waiting for the nightly run.
- Irradiance from [Open-Meteo](https://open-meteo.com/), free and without an
  API key. It is the only part of the integration that leaves the local
  network, it is opt-in with the forecast, and it sends nothing but the
  site's coordinates. Without it the fit falls back on its own cloudless-sky
  model, which works offline and scores measurably worse.

### Fixed

- A modelled sky and a measured one are never mixed in the same fit. They
  disagree about how a cloudless sky splits into direct beam and diffuse
  glow, and a fit shown both reads that disagreement as geometry: on a
  synthetic roof of one south-facing plane, five percent of mismatched hours
  were enough to return a north-facing plane and a vertical one, and 43% too
  much capacity. The window now uses one kind of sky throughout.
- A few hours without measured irradiance no longer discard the rest. The
  reanalysis archive trails real time by several days, so the most recent
  hours routinely arrive bare, and an all-or-nothing test would have dropped a
  whole year of measured irradiance because the last two days of it were not
  published yet. The gap is now filled from the forecast endpoint's record of
  the recent past, and any remainder is simply left out.

- Whether a source counts watts or kilowatt-hours is decided by what the
  sensor says it measures, not by which statistic field happens to exist. An
  energy counter recorded as a plain measurement also keeps an hourly mean,
  and that mean is the average reading of a rising counter — low in the
  morning, highest just before it resets at midnight. Read as watts it is the
  exact shape of a west-facing roof, and the fit would have reported one. Such
  a source is now skipped with an explanation instead. Where the entity is
  gone entirely — the inverter replaced, its integration removed, its
  statistics still in the database — the statistic's own recorded unit
  answers instead.

### Changed

- Service actions are registered in `async_setup`, so `learn_solar_model`
  exists whether or not a FlexiObox is loaded and can say why it cannot run,
  rather than leaving an automation with "unknown service".
- Diagnostics carry the learned roof, so a bug report arrives with the
  geometry that produced it.

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

[Unreleased]: https://github.com/Robbe654321/lifepowr-flexio-ha/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/Robbe654321/lifepowr-flexio-ha/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/Robbe654321/lifepowr-flexio-ha/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/Robbe654321/lifepowr-flexio-ha/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Robbe654321/lifepowr-flexio-ha/releases/tag/v0.1.0
