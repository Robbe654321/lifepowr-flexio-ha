"""Tests for recovering a roof's geometry from its production history."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import random

import pytest

from custom_components.lifepowr import solar
from custom_components.lifepowr.learning import (
    Array,
    FitQuality,
    PowerSample,
    SolarModel,
    _prepare,
    fit,
    nnls,
    select_clear_intervals,
)

LAT, LON, ALT = 51.05, 3.72, 10.0


def synthesise(
    arrays: list[tuple[float, float, float]],
    days: int = 300,
    seed: int = 7,
    cloudiness: float = 0.55,
    noise: float = 0.02,
    ac_limit: float | None = None,
    horizon: solar.Horizon | None = None,
) -> list[PowerSample]:
    """Return a year of hourly production from a roof we choose ourselves.

    Cloud is a single factor applied to the whole sky for a whole day, which
    is what makes the fit's job hard: it never sees the clear-sky curve
    directly, only a randomly dimmed version of it.
    """
    rng = random.Random(seed)
    model = SolarModel(
        arrays=tuple(
            Array(tilt=tilt, azimuth=azimuth, peak_power=peak)
            for tilt, azimuth, peak in arrays
        ),
        latitude=LAT,
        longitude=LON,
        altitude=ALT,
        quality=FitQuality(0, 0, 0.0, 0.0, 0.0, 0.0),
        created=datetime(2024, 1, 1, tzinfo=UTC),
        temperature_coefficient=0.0,
        horizon=horizon or solar.Horizon.flat(),
    )
    samples: list[PowerSample] = []
    start = datetime(2024, 1, 1, tzinfo=UTC)
    for day in range(days):
        # Most days lose something to cloud; a few are properly clear.
        clarity = 1.0 if rng.random() < 0.18 else rng.uniform(cloudiness, 1.0)
        for hour in range(24):
            begin = start + timedelta(days=day, hours=hour)
            end = begin + timedelta(hours=1)
            sky = _mean_clear_sky(begin, end)
            if sky.ghi <= 0.0:
                continue
            power = model.power(begin, end, sky.scaled(clarity))
            power *= 1.0 + rng.gauss(0.0, noise)
            if ac_limit is not None:
                power = min(power, ac_limit)
            samples.append(PowerSample(start=begin, end=end, power=max(power, 0.0)))
    return samples


def _mean_clear_sky(begin: datetime, end: datetime) -> solar.Irradiance:
    """Return the cloudless sky averaged over one interval."""
    total = [0.0, 0.0, 0.0]
    for index in range(4):
        when = begin + (end - begin) * ((index + 0.5) / 4)
        sky = solar.clear_sky(
            solar.solar_position(when, LAT, LON),
            ALT,
            solar.linke_turbidity(when.timetuple().tm_yday, LAT),
        )
        total[0] += sky.ghi / 4
        total[1] += sky.dni / 4
        total[2] += sky.dhi / 4
    return solar.Irradiance(*total)


def test_nnls_recovers_a_non_negative_combination() -> None:
    """The solver finds the exact weights when they exist."""
    rng = random.Random(1)
    columns = [[rng.random() for _ in range(40)] for _ in range(5)]
    truth = [2.0, 0.0, 1.5, 0.0, 3.0]
    target = [
        sum(column[row] * weight for column, weight in zip(columns, truth, strict=True))
        for row in range(40)
    ]
    assert nnls(columns, target) == pytest.approx(truth, abs=1e-6)


def test_nnls_never_returns_a_negative_weight() -> None:
    """Capacity cannot be negative, and that is the whole point."""
    rng = random.Random(2)
    columns = [[rng.random() for _ in range(40)] for _ in range(5)]
    truth = [2.0, -3.0, 1.0, 0.0, 1.0]
    target = [
        sum(column[row] * weight for column, weight in zip(columns, truth, strict=True))
        for row in range(40)
    ]
    assert all(weight >= 0.0 for weight in nnls(columns, target))


def test_nnls_handles_an_empty_problem() -> None:
    """No candidates means no weights, not a crash."""
    assert nnls([], []) == []


def test_recovers_a_single_south_facing_roof() -> None:
    """The plainest case: one plane, and the fit has to name it."""
    model = fit(synthesise([(35.0, 180.0, 5000.0)]), LAT, LON, ALT)
    assert model is not None
    assert len(model.arrays) == 1
    array = model.arrays[0]
    assert array.azimuth == pytest.approx(180.0, abs=6.0)
    assert array.tilt == pytest.approx(35.0, abs=7.0)
    assert array.peak_power == pytest.approx(5000.0, rel=0.12)
    assert model.quality.holdout_r2 > 0.9


def test_separates_an_east_west_split_roof() -> None:
    """Two planes facing opposite ways, told apart by the shape of the day."""
    model = fit(
        synthesise([(30.0, 100.0, 3000.0), (30.0, 260.0, 4000.0)]), LAT, LON, ALT
    )
    assert model is not None
    assert len(model.arrays) == 2
    east, west = sorted(model.arrays, key=lambda array: array.azimuth)
    assert east.azimuth == pytest.approx(100.0, abs=15.0)
    assert west.azimuth == pytest.approx(260.0, abs=15.0)
    assert east.peak_power < west.peak_power
    assert model.peak_power == pytest.approx(7000.0, rel=0.15)


def test_reports_capacity_below_the_inverter_ceiling() -> None:
    """A clipped inverter must not shrink the roof it is attached to.

    The brightest hours are censored by the hardware, so they are left out of
    the fit; counting them would teach it that the roof stops at the ceiling.
    """
    limit = 3000.0
    model = fit(synthesise([(35.0, 180.0, 5000.0)], ac_limit=limit), LAT, LON, ALT)
    assert model is not None
    assert model.peak_power > limit * 1.2
    assert model.ac_limit is not None
    assert model.ac_limit == pytest.approx(limit, rel=0.15)


def test_too_little_history_yields_no_model() -> None:
    """Better to say nothing than to invent a roof from a fortnight."""
    assert fit(synthesise([(35.0, 180.0, 5000.0)], days=3), LAT, LON, ALT) is None
    assert fit([], LAT, LON, ALT) is None


def test_clear_interval_selection_keeps_the_brightest_of_each_month() -> None:
    """Selection is stratified, so no season can dominate the fit."""
    samples = synthesise([(35.0, 180.0, 5000.0)])
    intervals = _prepare(samples, LAT, LON, ALT, None)
    chosen = select_clear_intervals(intervals)
    assert 0 < len(chosen) < len(intervals)
    months = {intervals[index].sample.start.month for index in chosen}
    # Every month the synthetic year covers is represented.
    assert months == {interval.sample.start.month for interval in intervals}


def test_model_survives_a_round_trip_through_storage() -> None:
    """A learned roof has to outlive a restart."""
    model = fit(synthesise([(35.0, 180.0, 5000.0)]), LAT, LON, ALT)
    assert model is not None
    stored = model.as_dict()
    restored = SolarModel.from_dict(stored)
    # Storage rounds to a tenth of a degree and a tenth of a watt, which is
    # far finer than the fit can resolve, so it has to survive re-saving
    # unchanged even though it is not bit-identical to the fitted model.
    assert restored.as_dict() == stored
    assert len(restored.arrays) == len(model.arrays)
    for saved, original in zip(restored.arrays, model.arrays, strict=True):
        assert saved.tilt == pytest.approx(original.tilt, abs=0.05)
        assert saved.azimuth == pytest.approx(original.azimuth, abs=0.05)
        assert saved.peak_power == pytest.approx(original.peak_power, abs=0.05)
    assert restored.created == model.created
    assert restored.ac_limit == pytest.approx(model.ac_limit)


def test_model_predicts_nothing_from_a_dark_sky() -> None:
    """No sun, no power, whatever the roof looks like."""
    model = fit(synthesise([(35.0, 180.0, 5000.0)]), LAT, LON, ALT)
    assert model is not None
    midnight = datetime(2024, 6, 21, 0, 0, tzinfo=UTC)
    assert model.power(midnight, midnight + timedelta(hours=1), solar.DARK) == 0.0


def test_orientation_reads_as_a_compass_bearing() -> None:
    """The description is for humans reading a dashboard."""
    assert "S" in Array(tilt=35.0, azimuth=180.0, peak_power=1.0).orientation
    assert "W" in Array(tilt=35.0, azimuth=270.0, peak_power=1.0).orientation


def test_finds_the_trees_in_front_of_the_panels() -> None:
    """A skyline the panels cannot see past has to be recovered too.

    Shading is invisible to tilt and azimuth: a fit denied a skyline explains
    a missing evening by turning the panels east. So the obstruction has to be
    found on its own, in the direction it actually stands.
    """
    # A stand of trees due west, and nothing anywhere else.
    blocked = solar.Horizon((0.0,) * 8 + (25.0, 25.0) + (0.0,) * 2)
    model = fit(
        synthesise([(30.0, 180.0, 6000.0)], horizon=blocked, cloudiness=0.8),
        LAT,
        LON,
        ALT,
    )
    assert model is not None
    assert not model.horizon.is_flat
    # The west is blocked and the east and south are not.
    assert model.horizon.elevation_at(265.0) > 12.0
    assert model.horizon.elevation_at(95.0) < 10.0
    assert model.horizon.elevation_at(180.0) < 10.0


def test_an_open_site_is_not_given_an_imaginary_skyline() -> None:
    """Twelve free numbers can always flatter the days they were fitted on.

    Held-out days are what stop them: an unobstructed roof has to come back
    unobstructed, or every forecast inherits a hedge it did not earn.
    """
    model = fit(synthesise([(30.0, 180.0, 6000.0)], cloudiness=0.8), LAT, LON, ALT)
    assert model is not None
    assert max(model.horizon.elevations) < 10.0


def test_a_skyline_survives_storage() -> None:
    """It is part of the model, so it has to outlive a restart with it."""
    blocked = solar.Horizon((0.0,) * 8 + (25.0, 25.0) + (0.0,) * 2)
    model = fit(
        synthesise([(30.0, 180.0, 6000.0)], horizon=blocked, cloudiness=0.8),
        LAT,
        LON,
        ALT,
    )
    assert model is not None
    restored = SolarModel.from_dict(model.as_dict())
    assert restored.horizon.elevations == pytest.approx(
        model.horizon.elevations, abs=0.05
    )


def test_a_few_missing_skies_do_not_lose_the_measured_ones() -> None:
    """The reanalysis trails real time, so recent hours arrive bare.

    An all-or-nothing test would drop a whole year of measured irradiance
    because the last two days of it were not published yet. To show which path
    was taken, the measured skies here are deliberately twice the truth: a fit
    that used them must come back with half the capacity, and one that quietly
    fell back on its own cloudless-sky model would not.
    """
    samples = synthesise([(30.0, 180.0, 6000.0)], cloudiness=0.9)
    doubled = [
        PowerSample(
            start=sample.start,
            end=sample.end,
            power=sample.power,
            # Every twentieth hour has no sky, as if the archive stopped short.
            sky=(
                None
                if index % 20 == 0
                else _mean_clear_sky(sample.start, sample.end).scaled(2.0)
            ),
        )
        for index, sample in enumerate(samples)
    ]
    model = fit(doubled, LAT, LON, ALT)
    assert model is not None
    assert model.peak_power == pytest.approx(3000.0, rel=0.2)


def test_mostly_missing_skies_fall_back_to_the_modelled_one() -> None:
    """Below the threshold the measured handful is not worth the mixing."""
    samples = synthesise([(30.0, 180.0, 6000.0)], cloudiness=0.9)
    sparse = [
        PowerSample(
            start=sample.start,
            end=sample.end,
            power=sample.power,
            sky=(
                _mean_clear_sky(sample.start, sample.end).scaled(2.0)
                if index % 20 == 0
                else None
            ),
        )
        for index, sample in enumerate(samples)
    ]
    model = fit(sparse, LAT, LON, ALT)
    assert model is not None
    assert model.peak_power == pytest.approx(6000.0, rel=0.2)


def test_a_learned_skyline_is_continuous() -> None:
    """A treeline does not stop dead and resume thirty degrees later.

    A plane's capacity and the skyline in front of it are partly
    interchangeable, so an unconstrained search will cut a notch in the
    skyline exactly where an array faces and pay for it with capacity. The
    smoothness prior earns its place on held-out days as well as looking
    right: on the installation this was tuned against it lifted held-out R²
    from 0.812 to 0.814 while halving the roughness.
    """
    blocked = solar.Horizon((0.0,) * 8 + (25.0, 25.0) + (0.0,) * 2)
    model = fit(
        synthesise([(30.0, 180.0, 6000.0)], horizon=blocked, cloudiness=0.8),
        LAT,
        LON,
        ALT,
    )
    assert model is not None
    heights = model.horizon.elevations
    steps = [
        abs(heights[index] - heights[(index + 1) % len(heights)])
        for index in range(len(heights))
    ]
    assert max(steps) <= 25.0
