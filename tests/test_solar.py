"""Tests for the solar geometry and irradiance maths."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from custom_components.lifepowr import solar

# Ghent, Belgium.
LAT, LON = 51.05, 3.72


@pytest.mark.parametrize(
    ("when", "elevation", "azimuth"),
    [
        # Solstice noon stands at 90 - latitude + declination.
        (datetime(2024, 6, 21, 11, 45, tzinfo=UTC), 62.4, 180.0),
        # ... and in December at 90 - latitude - declination.
        (datetime(2024, 12, 21, 11, 45, tzinfo=UTC), 15.5, 180.0),
        # Midsummer morning, well north of east. The bearing follows from
        # cos(A) = (sin d - sin h sin lat) / (cos h cos lat), which puts the
        # sun at 62.9 degrees when it stands 8.5 degrees up.
        (datetime(2024, 6, 21, 4, 45, tzinfo=UTC), 8.5, 62.9),
    ],
)
def test_solar_position_matches_almanac(when, elevation, azimuth) -> None:
    """The sun stands where the textbook says it does."""
    position = solar.solar_position(when, LAT, LON)
    assert position.elevation == pytest.approx(elevation, abs=1.0)
    assert position.azimuth == pytest.approx(azimuth, abs=2.0)


def test_solar_position_south_of_the_equator() -> None:
    """In Sydney the midday sun stands in the north."""
    position = solar.solar_position(
        datetime(2024, 6, 21, 2, 0, tzinfo=UTC), -33.87, 151.21
    )
    assert position.elevation == pytest.approx(32.7, abs=1.0)
    assert position.azimuth == pytest.approx(0.0, abs=5.0) or (
        position.azimuth == pytest.approx(360.0, abs=5.0)
    )


def test_sun_below_the_horizon_delivers_nothing() -> None:
    """A sky is dark when the sun is not in it."""
    position = solar.solar_position(datetime(2024, 12, 21, 0, 0, tzinfo=UTC), LAT, LON)
    assert not position.is_up
    assert solar.clear_sky(position) == solar.DARK
    assert solar.plane_of_array(30.0, 180.0, position, solar.DARK) == 0.0


def test_clear_sky_components_add_up() -> None:
    """The beam projected onto the horizontal plus the diffuse is the total."""
    position = solar.solar_position(datetime(2024, 6, 21, 11, 45, tzinfo=UTC), LAT, LON)
    sky = solar.clear_sky(position, altitude=10.0)
    assert sky.ghi == pytest.approx(sky.dni * position.cos_zenith + sky.dhi, rel=1e-9)
    assert 700 < sky.ghi < 1000


def test_turbidity_dims_the_beam_more_than_the_sky() -> None:
    """Haze moves energy out of the beam and into the diffuse."""
    position = solar.solar_position(datetime(2024, 6, 21, 11, 45, tzinfo=UTC), LAT, LON)
    clean = solar.clear_sky(position, linke=2.5)
    hazy = solar.clear_sky(position, linke=5.0)
    assert hazy.dni < clean.dni
    assert hazy.dhi > clean.dhi


def test_turbidity_climatology_peaks_in_summer() -> None:
    """Northern summers are hazier than northern winters, and vice versa."""
    assert solar.linke_turbidity(197, 51.0) > solar.linke_turbidity(15, 51.0)
    assert solar.linke_turbidity(197, -33.0) < solar.linke_turbidity(15, -33.0)


def test_plane_facing_the_sun_collects_the_most() -> None:
    """At noon a south-facing plane beats an east- or west-facing one."""
    position = solar.solar_position(datetime(2024, 3, 21, 11, 45, tzinfo=UTC), LAT, LON)
    sky = solar.clear_sky(position)
    south = solar.plane_of_array(35.0, 180.0, position, sky)
    assert south > solar.plane_of_array(35.0, 90.0, position, sky)
    assert south > solar.plane_of_array(35.0, 270.0, position, sky)
    assert south > solar.plane_of_array(35.0, 0.0, position, sky)


def test_morning_favours_the_east_and_evening_the_west() -> None:
    """Which is the whole reason the geometry can be recovered at all."""
    sky_and_sun = [
        (position, solar.clear_sky(position))
        for position in (
            solar.solar_position(datetime(2024, 6, 21, 6, 0, tzinfo=UTC), LAT, LON),
            solar.solar_position(datetime(2024, 6, 21, 17, 0, tzinfo=UTC), LAT, LON),
        )
    ]
    morning, evening = sky_and_sun
    assert solar.plane_of_array(35.0, 90.0, *morning) > solar.plane_of_array(
        35.0, 270.0, *morning
    )
    assert solar.plane_of_array(35.0, 270.0, *evening) > solar.plane_of_array(
        35.0, 90.0, *evening
    )


def test_horizon_blocks_the_beam_but_leaves_the_sky() -> None:
    """An obstruction makes a panel go quiet, not dark."""
    position = solar.solar_position(datetime(2024, 6, 21, 5, 0, tzinfo=UTC), LAT, LON)
    sky = solar.clear_sky(position)
    assert position.elevation < 15.0
    open_view = solar.plane_of_array(35.0, 90.0, position, sky)
    blocked = solar.plane_of_array(
        35.0,
        90.0,
        position,
        sky,
        horizon=solar.Horizon((20.0,) * solar.HORIZON_SECTORS),
    )
    assert 0.0 < blocked < open_view


def test_horizon_interpolates_between_sectors() -> None:
    """A skyline is a smooth curve, not twelve steps."""
    horizon = solar.Horizon((0.0, 0.0, 10.0, 20.0) + (0.0,) * 8)
    assert horizon.elevation_at(75.0) == pytest.approx(10.0)
    assert horizon.elevation_at(105.0) == pytest.approx(20.0)
    assert horizon.elevation_at(90.0) == pytest.approx(15.0)
    assert solar.Horizon.flat().is_flat


def test_compass_points_read_the_right_way_round() -> None:
    """North is 0 and east is 90, as every roof owner expects."""
    assert solar.compass_point(0.0) == "N"
    assert solar.compass_point(90.0) == "E"
    assert solar.compass_point(180.0) == "S"
    assert solar.compass_point(270.0) == "W"
    assert solar.compass_point(359.0) == "N"
