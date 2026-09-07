"""Learn a roof's geometry from its own production history.

Nobody knows their roof to the degree. Tilt is guessed from the pitch of the
ceiling, azimuth from a map, and the panel rating from a label in the attic --
and installations that grew over time have several planes at once. A forecast
built on those guesses inherits them.

The measurements know better. Every orientation leaves a distinctive
fingerprint in the daily and seasonal shape of a production curve: an
east-facing plane peaks before solar noon and fades early, a west-facing one
does the opposite, a steep plane earns its keep in December and loses in June.
A roof with several planes produces the *sum* of those fingerprints, so the
geometry can be recovered by asking which combination of orientations, weighted
by capacity, reproduces the measured history.

That is the problem this module solves:

    minimise  || P - A w ||²   subject to  w >= 0

where each column of ``A`` is the irradiance one candidate orientation would
have collected in each measured interval, ``P`` is what the inverter actually
produced, and ``w`` is the capacity to attribute to each orientation. The
non-negativity constraint is what makes it work: capacity cannot be negative,
and a non-negative least squares solution is naturally sparse, so out of
hundreds of candidate orientations only the handful that are really on the roof
survive. :func:`nnls` is the Lawson-Hanson active set algorithm; the surviving
orientations are then merged into planes and polished by a continuous search.

The sky the panels saw is not known either. :func:`select_clear_intervals`
recovers it without any external data by comparing each interval only against
other intervals at the same time of day and year, and keeping the brightest --
those are the cloudless ones, whatever the geometry turns out to be. The whole
fit then iterates: better geometry sharpens the clear-sky selection, and a
sharper selection improves the geometry.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
import math
from operator import mul
from typing import Any, Final

from .const import LOGGER
from .solar import (
    DEFAULT_ALBEDO,
    HORIZON_SECTORS,
    HORIZON_SOFTNESS,
    Horizon,
    Irradiance,
    SolarPosition,
    beam_on_plane,
    clear_sky,
    compass_point,
    linke_turbidity,
    plane_of_array,
    sector_weights,
    solar_position,
)

#: Sub-samples taken inside every measured interval. A measurement is an
#: average over an hour, and the sun moves 15 degrees in that time, so the
#: model has to be averaged the same way or east and west planes are both
#: mis-modelled at exactly the hours that distinguish them.
SUBSAMPLES: Final = 4

#: Intervals longer than this are dropped rather than averaged over. A gap
#: usually means the recorder missed samples, and the shape inside it is
#: unknown.
MAX_INTERVAL: Final = timedelta(hours=3)

#: Candidate tilts, degrees from horizontal. Dense where roofs actually are.
COARSE_TILTS: Final = (0.0, 10.0, 20.0, 27.5, 35.0, 45.0, 55.0, 65.0)

#: Candidate azimuths, compass degrees. Panels facing within 45 degrees of
#: north are not a thing anyone installs, so the dictionary does not carry them.
COARSE_AZIMUTHS: Final = tuple(float(a) for a in range(45, 316, 15))

#: Two dictionary entries closer than this are the same roof plane seen twice.
MERGE_TILT: Final = 22.0
MERGE_AZIMUTH: Final = 35.0

#: An unobstructed skyline, shared because it is immutable.
NO_HORIZON: Final = Horizon.flat()

#: A plane this shallow points nowhere in particular, so only its tilt decides
#: whether it is the same roof as another.
FLAT_TILT: Final = 8.0

#: Planes smaller than this share of the total are noise, not roofs.
MIN_SHARE: Final = 0.04

#: Never report more planes than this. Beyond a handful the fit is describing
#: shading and soiling, not geometry.
MAX_ARRAYS: Final = 5

#: Quantile of the like-for-like comparison group taken as "as bright as it
#: gets here". Not the maximum, which would be one freak cloud-edge reading.
CLEAR_QUANTILE: Final = 0.9

#: How close to that brightest value an interval has to come to count as
#: cloudless. Loose enough to keep thin high cloud, which is still geometry.
KEEP_RATIO: Final = 0.85

#: A comparison group smaller than this cannot support a quantile.
MIN_GROUP: Final = 4

#: Share of a measured sky arriving as direct beam above which the hour counts
#: as genuinely cloudless. Overcast drives this to zero; a clear sky sits near
#: 0.75. Used only to decide which hours a model is *judged* on, never which
#: hours it learns from.
CLEAR_BEAM_FRACTION: Final = 0.6

#: Below this there is too little light for the ratio above to mean anything.
MIN_JUDGING_GHI: Final = 100.0

#: Alternating rounds of "select the clear intervals, then refit".
REFINEMENT_ROUNDS: Final = 3

#: The pattern search starts stepping this many degrees and halves until it is
#: finer than any roof is built or measured to.
SEARCH_STEP: Final = 8.0
SEARCH_LIMIT: Final = 0.5

#: Coefficients below this are numerically zero and leave the passive set.
_ZERO: Final = 1e-12

#: Ridge added to the normal equations. Neighbouring orientations are nearly
#: identical columns, so the Gram matrix is badly conditioned by construction.
RIDGE: Final = 1e-9

#: Power temperature coefficient of ordinary crystalline silicon, per Kelvin.
DEFAULT_TEMPERATURE_COEFFICIENT: Final = -0.004

#: Cell temperature rise per W/m² of plane-of-array irradiance, for panels
#: mounted parallel to a roof with limited air behind them.
_CELL_HEATING: Final = 0.030

#: Standard test condition cell temperature, °C.
_STC_TEMPERATURE: Final = 25.0

#: Intervals within this fraction of the highest ever seen are treated as
#: possibly clipped by the inverter and left out of the fit.
_CLIP_BAND: Final = 0.98


@dataclass(frozen=True, slots=True)
class PowerSample:
    """Average AC power over one measured interval.

    ``source`` distinguishes inverters when a site has more than one. Every
    source is fitted its own planes, but they share one sky, which is what
    makes the clear-interval selection agree between them.
    """

    start: datetime
    end: datetime
    power: float
    source: str = ""
    #: The sky actually measured over this interval, when a weather service
    #: can supply it. Without it the fit falls back on its own cloudless-sky
    #: model and keeps only the intervals that look cloudless.
    sky: Irradiance | None = None
    #: Outside air temperature, °C, when known.
    temperature: float | None = None

    @property
    def span(self) -> timedelta:
        """Return how long the interval lasted."""
        return self.end - self.start


@dataclass(frozen=True, slots=True)
class Array:
    """One roof plane, as the fit sees it."""

    #: Degrees from horizontal.
    tilt: float
    #: Compass degrees: 90 east, 180 south, 270 west.
    azimuth: float
    #: AC watts this plane makes at 1000 W/m² on its own surface, at 25 °C.
    #: This is a *delivered* rating: module losses, wiring, inverter efficiency
    #: and any permanent shading are already inside it, so it reads a little
    #: below the number on the panel labels.
    peak_power: float
    #: Which measured source it belongs to.
    source: str = ""

    @property
    def orientation(self) -> str:
        """Return a human-readable description of the plane."""
        return (
            f"{compass_point(self.azimuth)} {self.azimuth:.0f}° / {self.tilt:.0f}° tilt"
        )

    def as_dict(self) -> dict[str, Any]:
        """Return the plane as plain data for storage and attributes."""
        return {
            "tilt": round(self.tilt, 1),
            "azimuth": round(self.azimuth, 1),
            "peak_power": round(self.peak_power, 1),
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Array:
        """Rebuild a plane from stored data."""
        return cls(
            tilt=float(data["tilt"]),
            azimuth=float(data["azimuth"]),
            peak_power=float(data["peak_power"]),
            source=str(data.get("source", "")),
        )


@dataclass(frozen=True, slots=True)
class FitQuality:
    """How well the learned planes reproduce the history they came from."""

    #: Intervals the fit was scored on.
    samples: int
    #: Distinct days those intervals came from.
    days: int
    #: Root mean square error against cloudless intervals, W.
    rmse: float
    #: Mean absolute error against cloudless intervals, W.
    mae: float
    #: Share of the variance explained, on cloudless intervals.
    r2: float
    #: Same, on intervals held out of the fit.
    holdout_r2: float

    def as_dict(self) -> dict[str, Any]:
        """Return the metrics as plain data."""
        return {
            "samples": self.samples,
            "days": self.days,
            "rmse": round(self.rmse, 1),
            "mae": round(self.mae, 1),
            "r2": round(self.r2, 4),
            "holdout_r2": round(self.holdout_r2, 4),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FitQuality:
        """Rebuild the metrics from stored data."""
        return cls(
            samples=int(data["samples"]),
            days=int(data["days"]),
            rmse=float(data["rmse"]),
            mae=float(data["mae"]),
            r2=float(data["r2"]),
            holdout_r2=float(data.get("holdout_r2", data["r2"])),
        )


@dataclass(frozen=True, slots=True)
class SolarModel:
    """A learned installation: its planes, its ceiling, and how good the fit is."""

    arrays: tuple[Array, ...]
    latitude: float
    longitude: float
    altitude: float
    quality: FitQuality
    created: datetime
    #: Highest AC power ever measured, W. Used as the inverter ceiling, because
    #: no forecast should predict more than the hardware can deliver.
    ac_limit: float | None = None
    temperature_coefficient: float = DEFAULT_TEMPERATURE_COEFFICIENT
    albedo: float = DEFAULT_ALBEDO
    #: Learned skyline: how high trees and neighbouring roofs stand in each
    #: compass direction. Flat when nothing was found, or nothing was needed.
    horizon: Horizon = NO_HORIZON
    #: Everything the planes make, scaled by this. Geometry needs a year of
    #: seasons to pin down; how much the hardware behind it currently delivers
    #: needs only a few bright days, and the two change on different clocks --
    #: replace an inverter and the roof is the same while the yield is not.
    gain: float = 1.0

    @property
    def peak_power(self) -> float:
        """Return the capacity the planes were fitted to, W."""
        return sum(array.peak_power for array in self.arrays)

    @property
    def rated_power(self) -> float:
        """Return the capacity the roof is currently delivering, W.

        The fitted capacity times the gain: what the model actually predicts
        today, which is the number worth showing.
        """
        return self.peak_power * self.gain

    def power(
        self,
        start: datetime,
        end: datetime,
        sky: Irradiance,
        temperature: float | None = None,
    ) -> float:
        """Return the average AC power expected over one interval, W."""
        if not self.arrays or sky.ghi <= 0.0:
            return 0.0
        total = 0.0
        for when, weight in _subsample(start, end):
            position = solar_position(when, self.latitude, self.longitude)
            if not position.is_up:
                continue
            total += weight * self._instant_power(position, sky, temperature)
        total *= self.gain
        if self.ac_limit is not None:
            total = min(total, self.ac_limit)
        return total

    def _instant_power(
        self,
        position: SolarPosition,
        sky: Irradiance,
        temperature: float | None,
    ) -> float:
        """Return the AC power at one instant, W."""
        total = 0.0
        for array in self.arrays:
            poa = plane_of_array(
                array.tilt,
                array.azimuth,
                position,
                sky,
                albedo=self.albedo,
                horizon=self.horizon,
            )
            total += (
                array.peak_power
                * poa
                / 1000.0
                * _derate(poa, temperature, self.temperature_coefficient)
            )
        return total

    def as_dict(self) -> dict[str, Any]:
        """Return the model as plain data for storage."""
        return {
            "arrays": [array.as_dict() for array in self.arrays],
            "latitude": self.latitude,
            "longitude": self.longitude,
            "altitude": self.altitude,
            "quality": self.quality.as_dict(),
            "created": self.created.isoformat(),
            "ac_limit": self.ac_limit,
            "temperature_coefficient": self.temperature_coefficient,
            "albedo": self.albedo,
            "horizon": self.horizon.as_list(),
            "gain": round(self.gain, 4),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SolarModel:
        """Rebuild a model from stored data."""
        return cls(
            arrays=tuple(Array.from_dict(item) for item in data["arrays"]),
            latitude=float(data["latitude"]),
            longitude=float(data["longitude"]),
            altitude=float(data["altitude"]),
            quality=FitQuality.from_dict(data["quality"]),
            created=datetime.fromisoformat(data["created"]),
            ac_limit=(
                None if data.get("ac_limit") is None else float(data["ac_limit"])
            ),
            temperature_coefficient=float(
                data.get("temperature_coefficient", DEFAULT_TEMPERATURE_COEFFICIENT)
            ),
            albedo=float(data.get("albedo", DEFAULT_ALBEDO)),
            horizon=(
                Horizon(tuple(float(value) for value in stored))
                if (stored := data.get("horizon")) and len(stored) == HORIZON_SECTORS
                else NO_HORIZON
            ),
            gain=float(data.get("gain", 1.0)),
        )


def _derate(poa: float, temperature: float | None, coefficient: float) -> float:
    """Return the temperature correction for one plane's output."""
    if temperature is None:
        return 1.0
    cell = temperature + _CELL_HEATING * poa
    return max(1.0 + coefficient * (cell - _STC_TEMPERATURE), 0.0)


def _subsample(start: datetime, end: datetime) -> list[tuple[datetime, float]]:
    """Return evenly spaced instants inside an interval, with equal weights."""
    span = (end - start).total_seconds()
    weight = 1.0 / SUBSAMPLES
    return [
        (start + timedelta(seconds=span * (index + 0.5) / SUBSAMPLES), weight)
        for index in range(SUBSAMPLES)
    ]


# --------------------------------------------------------------------------
# Non-negative least squares
# --------------------------------------------------------------------------


def _solve(matrix: list[list[float]], rhs: list[float]) -> list[float] | None:
    """Solve a small dense system by Gaussian elimination with partial pivoting."""
    size = len(rhs)
    rows = [[*row, value] for row, value in zip(matrix, rhs, strict=True)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda r: abs(rows[r][column]))
        if abs(rows[pivot][column]) < _ZERO:
            return None
        rows[column], rows[pivot] = rows[pivot], rows[column]
        pivot_row = rows[column]
        inverse = 1.0 / pivot_row[column]
        for other in range(column + 1, size):
            factor = rows[other][column] * inverse
            if factor:
                target = rows[other]
                for index in range(column, size + 1):
                    target[index] -= factor * pivot_row[index]
    result = [0.0] * size
    for column in reversed(range(size)):
        row = rows[column]
        total = row[size] - sum(row[k] * result[k] for k in range(column + 1, size))
        result[column] = total / row[column]
    return result


def nnls(
    columns: Sequence[Sequence[float]],
    target: Sequence[float],
    max_iterations: int | None = None,
) -> list[float]:
    """Return the non-negative least squares solution of ``columns @ w = target``.

    Lawson and Hanson's active set method, working on the normal equations
    because the design matrix is tall and thin and the passive set stays small.
    ``columns`` is column-major: each entry is one candidate's value in every
    interval, which is both how the design matrix is built and the layout that
    makes the Gram matrix cheap to accumulate.
    """
    count = len(columns)
    if count == 0:
        return []

    gram = [[0.0] * count for _ in range(count)]
    for j in range(count):
        column = columns[j]
        for k in range(j, count):
            value = sum(map(mul, column, columns[k]))
            gram[j][k] = gram[k][j] = value
    trace = sum(gram[j][j] for j in range(count)) or 1.0
    for j in range(count):
        gram[j][j] += RIDGE * trace

    correlation = [sum(map(mul, column, target)) for column in columns]

    weights = [0.0] * count
    passive: list[int] = []
    tolerance = 1e-10 * (max(map(abs, correlation)) or 1.0)
    max_iterations = max_iterations or 3 * count

    for _ in range(max_iterations):
        gradient = [
            correlation[j] - sum(gram[j][k] * weights[k] for k in range(count))
            for j in range(count)
        ]
        candidate, best = -1, tolerance
        for j in range(count):
            if j not in passive and gradient[j] > best:
                candidate, best = j, gradient[j]
        if candidate < 0:
            break
        passive.append(candidate)

        for _ in range(count):
            trial = _solve(
                [[gram[j][k] for k in passive] for j in passive],
                [correlation[j] for j in passive],
            )
            if trial is None:
                passive.pop()
                break
            if all(value > 0.0 for value in trial):
                for index, j in enumerate(passive):
                    weights[j] = trial[index]
                break
            # Step only as far as the first coefficient that would go negative.
            alpha = min(
                weights[j] / (weights[j] - trial[index])
                for index, j in enumerate(passive)
                if trial[index] <= 0.0
            )
            for index, j in enumerate(passive):
                weights[j] += alpha * (trial[index] - weights[j])
            passive = [j for j in passive if weights[j] > _ZERO]
            for j in range(count):
                if j not in passive:
                    weights[j] = 0.0
        else:
            break

    return weights


# --------------------------------------------------------------------------
# Fitting
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Interval:
    """One measured interval with everything the fit needs precomputed."""

    sample: PowerSample
    #: Sun position, sky and weight at each sub-sample inside the interval.
    points: tuple[tuple[SolarPosition, Irradiance, float], ...]
    #: What a cloudless sky would have put on the horizontal here, W/m².
    clear_ghi: float
    #: Group used to compare like with like when no measured sky is available.
    group: tuple[int, int]
    #: Share of the measured sky that arrived as direct beam, or None when the
    #: sky was modelled rather than measured.
    beam_fraction: float | None


def _prepare(
    samples: Iterable[PowerSample],
    latitude: float,
    longitude: float,
    altitude: float,
    linke: float | None,
    *,
    use_measured: bool = True,
) -> list[_Interval]:
    """Precompute sun positions and skies for every usable interval.

    With ``use_measured`` false the skies carried by the samples are ignored
    and every interval gets a modelled one, so the whole fit sees one kind of
    sky rather than two.
    """
    prepared: list[_Interval] = []
    for sample in samples:
        span = sample.span
        if span <= timedelta(0) or span > MAX_INTERVAL or sample.power < 0.0:
            continue
        points: list[tuple[SolarPosition, Irradiance, float]] = []
        clear_ghi = 0.0
        for when, weight in _subsample(sample.start, sample.end):
            position = solar_position(when, latitude, longitude)
            if not position.is_up:
                continue
            turbidity = (
                linke_turbidity(position.day_of_year, latitude)
                if linke is None
                else linke
            )
            modelled = clear_sky(position, altitude, turbidity)
            clear_ghi += weight * modelled.ghi
            points.append(
                (
                    position,
                    sample.sky if use_measured and sample.sky else modelled,
                    weight,
                )
            )
        if not points or clear_ghi <= 1.0:
            continue
        middle = sample.start + span / 2
        measured = sample.sky if use_measured else None
        prepared.append(
            _Interval(
                sample=sample,
                points=tuple(points),
                clear_ghi=clear_ghi,
                group=(middle.month, middle.hour),
                beam_fraction=(
                    (measured.ghi - measured.dhi) / measured.ghi
                    if measured is not None and measured.ghi > MIN_JUDGING_GHI
                    else None
                ),
            )
        )
    return prepared


def _column(
    tilt: float,
    azimuth: float,
    intervals: Sequence[_Interval],
    albedo: float,
    coefficient: float,
    *,
    horizon: Horizon | None = None,
) -> list[float]:
    """Return one candidate orientation's yield per watt-peak, per interval."""
    column: list[float] = []
    for interval in intervals:
        total = 0.0
        temperature = interval.sample.temperature
        for position, sky, weight in interval.points:
            poa = plane_of_array(
                tilt, azimuth, position, sky, albedo=albedo, horizon=horizon
            )
            total += weight * poa * _derate(poa, temperature, coefficient)
        column.append(total / 1000.0)
    return column


def _quantile(values: Sequence[float], fraction: float) -> float:
    """Return a linearly interpolated quantile of an unsorted sequence."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def select_clear_intervals(
    intervals: Sequence[_Interval],
    quantile: float = CLEAR_QUANTILE,
    keep_ratio: float = KEEP_RATIO,
) -> list[int]:
    """Return the indices of the intervals that look cloudless.

    An interval was cloudless when it produced nearly as much as the brightest
    *comparable* interval, and "comparable" here means another interval at the
    same hour of the same month. That comparison never consults the model, and
    deliberately so. Selecting instead on how well a model already explains an
    interval reads as a refinement and behaves as a trap: it keeps whatever the
    model under-predicts, discards what it over-predicts, and confirms the
    model's own bias. Measured against held-out days that loop makes the fit
    steadily worse, so the sky is judged on the measurements alone.

    Comparing within a month matters for the same reason. A single threshold
    across the year quietly keeps whichever season the sky model happens to
    flatter, and a fit fed mostly midwinter intervals answers with a roof far
    steeper than the real one. Stratifying keeps the clearest days of every
    month, which is the seasonal spread the tilt is read from.
    """
    scores = [interval.sample.power / interval.clear_ghi for interval in intervals]
    grouped: dict[tuple[int, int], list[float]] = {}
    for interval, score in zip(intervals, scores, strict=True):
        grouped.setdefault(interval.group, []).append(score)
    thresholds = {
        group: keep_ratio * _quantile(values, quantile)
        for group, values in grouped.items()
        if len(values) >= MIN_GROUP
    }
    return [
        index
        for index, (interval, score) in enumerate(zip(intervals, scores, strict=True))
        if score >= thresholds.get(interval.group, 0.0)
    ]


def _cluster(
    weights: Sequence[float],
    orientations: Sequence[tuple[float, float]],
    max_arrays: int,
) -> list[tuple[float, float, float]]:
    """Merge neighbouring dictionary entries into distinct roof planes.

    The dictionary is deliberately finer than any roof, so a single plane
    usually lights up two or three adjacent candidates. Merging them by
    capacity-weighted average recovers an angle between the grid points, which
    is why the answer is not restricted to the dictionary's resolution.
    """
    found = [
        (weight, *orientation)
        for weight, orientation in zip(weights, orientations, strict=True)
        if weight > 0.0
    ]
    found.sort(reverse=True)

    planes: list[list[float]] = []  # capacity, sum(w*tilt), sum(w*sin), sum(w*cos)
    for weight, tilt, azimuth in found:
        azimuth_rad = math.radians(azimuth)
        for plane in planes:
            mean_tilt = plane[1] / plane[0]
            mean_azimuth = math.degrees(math.atan2(plane[2], plane[3]))
            # A nearly flat plane has no meaningful azimuth, so only its tilt
            # decides whether it is the same roof.
            near_flat = mean_tilt < FLAT_TILT and tilt < FLAT_TILT
            if abs(tilt - mean_tilt) <= MERGE_TILT and (
                near_flat
                or abs((azimuth - mean_azimuth + 180.0) % 360.0 - 180.0)
                <= MERGE_AZIMUTH
            ):
                plane[0] += weight
                plane[1] += weight * tilt
                plane[2] += weight * math.sin(azimuth_rad)
                plane[3] += weight * math.cos(azimuth_rad)
                break
        else:
            planes.append(
                [
                    weight,
                    weight * tilt,
                    weight * math.sin(azimuth_rad),
                    weight * math.cos(azimuth_rad),
                ]
            )

    total = sum(plane[0] for plane in planes) or 1.0
    planes = [plane for plane in planes if plane[0] / total >= MIN_SHARE]
    planes.sort(reverse=True)
    return [
        (
            plane[1] / plane[0],
            math.degrees(math.atan2(plane[2], plane[3])) % 360.0,
            plane[0],
        )
        for plane in planes[:max_arrays]
    ]


def _residual(
    columns: Sequence[Sequence[float]],
    weights: Sequence[float],
    target: Sequence[float],
) -> float:
    """Return the sum of squared errors of a weighted column combination."""
    total = 0.0
    for index, measured in enumerate(target):
        estimate = sum(
            weight * column[index]
            for weight, column in zip(weights, columns, strict=True)
        )
        total += (measured - estimate) ** 2
    return total


def _refine(
    planes: Sequence[tuple[float, float, float]],
    intervals: Sequence[_Interval],
    target: Sequence[float],
    albedo: float,
    coefficient: float,
    *,
    horizon: Horizon | None = None,
) -> tuple[list[tuple[float, float]], list[float], float]:
    """Polish the plane angles off the dictionary grid by pattern search.

    The dictionary answers "roughly which orientations", to the nearest
    15 degrees. This walks each plane's tilt and azimuth downhill from there in
    shrinking steps, re-solving the capacities exactly at every trial, and
    settles on angles no grid could have produced.
    """
    angles = [(tilt, azimuth) for tilt, azimuth, _ in planes]
    if not angles:
        return [], [], 0.0

    cache: dict[tuple[float, float], list[float]] = {}

    def column_for(tilt: float, azimuth: float) -> list[float]:
        key = (round(tilt, 2), round(azimuth, 2) % 360.0)
        if key not in cache:
            cache[key] = _column(
                key[0], key[1], intervals, albedo, coefficient, horizon=horizon
            )
        return cache[key]

    def score(trial: Sequence[tuple[float, float]]) -> tuple[float, list[float]]:
        columns = [column_for(tilt, azimuth) for tilt, azimuth in trial]
        weights = nnls(columns, target)
        return _residual(columns, weights, target), weights

    best, weights = score(angles)
    step = SEARCH_STEP
    while step >= SEARCH_LIMIT:
        improved = False
        for index in range(len(angles)):
            for delta_tilt, delta_azimuth in (
                (step, 0.0),
                (-step, 0.0),
                (0.0, step),
                (0.0, -step),
            ):
                trial = list(angles)
                tilt = min(max(trial[index][0] + delta_tilt, 0.0), 90.0)
                azimuth = (trial[index][1] + delta_azimuth) % 360.0
                trial[index] = (tilt, azimuth)
                candidate, trial_weights = score(trial)
                if candidate < best * (1.0 - 1e-9):
                    angles, best, weights, improved = (
                        trial,
                        candidate,
                        trial_weights,
                        True,
                    )
        if not improved:
            step /= 2.0

    return angles, weights, best


#: Below this many cloudless intervals a source has not shown enough of the
#: year to pin its geometry down, and no model is produced for it.
MIN_FIT_SAMPLES: Final = 60

#: With one meter there is nothing to compare it against.
MIN_SOURCES_TO_COMPARE: Final = 2

#: A source whose output over the hours it shares with the others comes this
#: close to their sum is not measuring more panels -- it is measuring the same
#: panels again, further down the wiring.
COMBINED_TOLERANCE: Final = 0.15

#: Share of intervals that must carry a measured sky before the fit works in
#: measured mode at all. A reanalysis trails real time by a few days, so the
#: most recent hours routinely arrive bare; without this an all-or-nothing
#: test would drop a whole year of measured irradiance over the last two days
#: of it, and quietly fall back on the weaker modelled sky.
MEASURED_SHARE: Final = 0.8

#: Most intervals one source's fit will use. Two years of history is tens of
#: thousands of hours and the geometry stops sharpening long before that,
#: while the search cost keeps climbing -- this runs nightly on whatever
#: hardware Home Assistant is installed on.
MAX_FIT_INTERVALS: Final = 1600

#: Headroom over the highest average ever measured, before a forecast is
#: called impossible. Enough to cover a brighter day than the history holds.
_CEILING_HEADROOM: Final = 1.1


def _orientations(
    tilts: Sequence[float], azimuths: Sequence[float]
) -> list[tuple[float, float]]:
    """Return the candidate dictionary, without repeating flat orientations."""
    candidates: list[tuple[float, float]] = []
    for tilt in tilts:
        if tilt <= 0.0:
            candidates.append((0.0, 180.0))
            continue
        candidates.extend((tilt, azimuth) for azimuth in azimuths)
    return candidates


def _drop_clipped(intervals: Sequence[_Interval]) -> list[int]:
    """Return the indices to keep, leaving out intervals the inverter capped.

    An inverter that has hit its AC ceiling reports its ceiling, not what the
    roof offered. Fitting to those hours would quietly shrink the learned
    capacity to whatever the inverter allows, so the brightest band of each
    source is set aside.
    """
    ceilings: dict[str, float] = {}
    for interval in intervals:
        source = interval.sample.source
        ceilings[source] = max(ceilings.get(source, 0.0), interval.sample.power)
    return [
        index
        for index, interval in enumerate(intervals)
        if ceilings[interval.sample.source] <= 0.0
        or interval.sample.power < _CLIP_BAND * ceilings[interval.sample.source]
    ]


def _score(
    intervals: Sequence[_Interval],
    angles: Sequence[tuple[float, float]],
    capacities: Sequence[float],
    albedo: float,
    coefficient: float,
    *,
    horizon: Horizon | None = None,
) -> tuple[float, float, float]:
    """Return RMSE, MAE and R² of one set of planes over some intervals."""
    if not intervals:
        return 0.0, 0.0, 0.0
    estimate = [0.0] * len(intervals)
    for (tilt, azimuth), capacity in zip(angles, capacities, strict=True):
        for index, value in enumerate(
            _column(tilt, azimuth, intervals, albedo, coefficient, horizon=horizon)
        ):
            estimate[index] += capacity * value
    measured = [interval.sample.power for interval in intervals]
    errors = [value - guess for value, guess in zip(measured, estimate, strict=True)]
    mean = sum(measured) / len(measured)
    variance = sum((value - mean) ** 2 for value in measured)
    squared = sum(error**2 for error in errors)
    return (
        math.sqrt(squared / len(errors)),
        sum(map(abs, errors)) / len(errors),
        1.0 - squared / variance if variance > 0.0 else 0.0,
    )


def _pooled_score(
    intervals: Sequence[_Interval],
    arrays: Sequence[Array],
    albedo: float,
    coefficient: float,
    *,
    horizon: Horizon | None = None,
) -> tuple[float, float, float]:
    """Return RMSE, MAE and R² of a whole model over intervals of any source.

    Each interval is only ever compared against the planes of the source that
    measured it; a site's inverters each see their own roof, not the sum.
    """
    if not intervals:
        return 0.0, 0.0, 0.0
    estimate = [0.0] * len(intervals)
    grouped: dict[str, list[int]] = {}
    for index, interval in enumerate(intervals):
        grouped.setdefault(interval.sample.source, []).append(index)
    for source, indices in grouped.items():
        subset = [intervals[index] for index in indices]
        for array in arrays:
            if array.source != source:
                continue
            column = _column(
                array.tilt,
                array.azimuth,
                subset,
                albedo,
                coefficient,
                horizon=horizon,
            )
            for offset, index in enumerate(indices):
                estimate[index] += array.peak_power * column[offset]
    measured = [interval.sample.power for interval in intervals]
    errors = [value - guess for value, guess in zip(measured, estimate, strict=True)]
    mean = sum(measured) / len(measured)
    variance = sum((value - mean) ** 2 for value in measured)
    squared = sum(error**2 for error in errors)
    return (
        math.sqrt(squared / len(errors)),
        sum(map(abs, errors)) / len(errors),
        1.0 - squared / variance if variance > 0.0 else 0.0,
    )


#: Skyline heights the search tries, in degrees of elevation. Coarse on
#: purpose: an hourly average cannot resolve a treeline to better than this,
#: and a finer grid only fits noise.
HORIZON_STEPS: Final = (0.0, 2.0, 4.0, 6.0, 8.0, 11.0, 14.0, 18.0, 23.0)

#: A skyline has to buy at least this much held-out R² to be believed.
MIN_HORIZON_GAIN: Final = 0.002

#: How strongly neighbouring sectors are pulled towards each other, as a share
#: of the unobstructed residual per squared degree of disagreement. Skylines
#: are continuous -- a treeline does not stop dead and resume 30 degrees
#: later -- while a plane's capacity and the skyline in front of it are partly
#: interchangeable, so without this the search will happily cut a notch in the
#: skyline exactly where an array faces and pay for it with capacity.
HORIZON_SMOOTHNESS: Final = 2e-5


@dataclass(frozen=True, slots=True)
class _Plan:
    """One source's learned planes and the intervals they were learned from."""

    source: str
    angles: list[tuple[float, float]]
    intervals: list[_Interval]


@dataclass(frozen=True, slots=True)
class _Shaded:
    """One plane's irradiance, split so candidate skylines are cheap to try.

    Everything that does not depend on the skyline -- sun positions, the
    diffuse and reflected shares, the temperature derate -- is worked out once.
    Trying a skyline then costs one multiply per sub-sample instead of a full
    transposition, which is what makes searching twelve directions feasible.
    """

    #: Index into the flat arrays where each interval's sub-samples begin.
    bounds: tuple[int, ...]
    #: Direct beam, per watt-peak, before any obstruction.
    beam: tuple[float, ...]
    #: Diffuse and ground-reflected share, which an obstruction leaves alone.
    rest: tuple[float, ...]
    sector: tuple[int, ...]
    fraction: tuple[float, ...]
    elevation: tuple[float, ...]


def _split(
    tilt: float,
    azimuth: float,
    intervals: Sequence[_Interval],
    albedo: float,
    coefficient: float,
) -> _Shaded:
    """Precompute one candidate plane, ready for any skyline."""
    beam: list[float] = []
    rest: list[float] = []
    sector: list[int] = []
    fraction: list[float] = []
    elevation: list[float] = []
    bounds = [0]
    for interval in intervals:
        temperature = interval.sample.temperature
        for position, sky, weight in interval.points:
            total = plane_of_array(tilt, azimuth, position, sky, albedo=albedo)
            direct = beam_on_plane(tilt, azimuth, position, sky)
            # The derate is taken from the unshaded irradiance: a panel in
            # shadow runs cooler, but by then it is barely producing anyway.
            scale = weight * _derate(total, temperature, coefficient) / 1000.0
            beam.append(direct * scale)
            rest.append((total - direct) * scale)
            index, offset = sector_weights(position.azimuth)
            sector.append(index)
            fraction.append(offset)
            elevation.append(position.elevation)
        bounds.append(len(beam))
    return _Shaded(
        bounds=tuple(bounds),
        beam=tuple(beam),
        rest=tuple(rest),
        sector=tuple(sector),
        fraction=tuple(fraction),
        elevation=tuple(elevation),
    )


def _shaded_column(split: _Shaded, skyline: Sequence[float]) -> list[float]:
    """Return a precomputed plane's yield under one candidate skyline."""
    column: list[float] = []
    for start, end in zip(split.bounds, split.bounds[1:], strict=False):
        total = 0.0
        for index in range(start, end):
            lower = split.sector[index]
            offset = split.fraction[index]
            height = (
                skyline[lower] * (1.0 - offset)
                + skyline[(lower + 1) % HORIZON_SECTORS] * offset
            )
            clearance = (split.elevation[index] - height) / HORIZON_SOFTNESS
            total += split.beam[index] * min(max(clearance, 0.0), 1.0)
            total += split.rest[index]
        column.append(total)
    return column


def _fit_horizon(
    plans: Sequence[_Plan],
    albedo: float,
    coefficient: float,
    smoothness: float = HORIZON_SMOOTHNESS,
) -> Horizon:
    """Work out how high the skyline stands in each compass direction.

    Trees and a neighbour's gable take the first and last hour of production
    away, and no tilt or azimuth can express that -- a fit denied a skyline
    explains the missing evening by turning the panels east instead. Each
    direction is searched in turn, re-solving the capacities at every trial so
    that raising the skyline cannot be paid for by simply inflating the roof.

    One skyline serves the whole site: the inverters stand under the same trees,
    so every source votes on it, each against its own planes.
    """
    prepared = [
        (
            [
                _split(tilt, azimuth, plan.intervals, albedo, coefficient)
                for tilt, azimuth in plan.angles
            ],
            [interval.sample.power for interval in plan.intervals],
        )
        for plan in plans
        if plan.angles and plan.intervals
    ]
    if not prepared:
        return NO_HORIZON

    def fit_residual(skyline: Sequence[float]) -> float:
        total = 0.0
        for splits, target in prepared:
            columns = [_shaded_column(split, skyline) for split in splits]
            total += _residual(columns, nnls(columns, target), target)
        return total

    open_sky = [0.0] * HORIZON_SECTORS
    scale = fit_residual(open_sky) * smoothness

    def residual(skyline: Sequence[float]) -> float:
        roughness = sum(
            (skyline[index] - skyline[(index + 1) % HORIZON_SECTORS]) ** 2
            for index in range(HORIZON_SECTORS)
        )
        return fit_residual(skyline) + scale * roughness

    skyline = open_sky
    best = residual(skyline)
    for _ in range(2):
        improved = False
        for index in range(HORIZON_SECTORS):
            for height in HORIZON_STEPS:
                if height == skyline[index]:
                    continue
                trial = list(skyline)
                trial[index] = height
                score = residual(trial)
                if score < best * (1.0 - 1e-6):
                    best, skyline, improved = score, trial, True
        if not improved:
            break
    return Horizon(tuple(skyline))


#: A plane has to buy at least this much held-out R² to be worth adding.
#: Without it the search keeps splitting one roof into ever more near-vertical
#: slivers that fit the training days a fraction better and the rest no better
#: at all.
MIN_HOLDOUT_GAIN: Final = 0.002


def _drop_combined_sources(intervals: list[_Interval]) -> list[_Interval]:
    """Remove a meter that is only re-measuring what the others already saw.

    Capacities from different sources are added together, which is right when
    each meter watches its own array and badly wrong when one of them watches
    all of them. That configuration is easy to arrive at honestly -- point the
    fit at two old string inverters and the new one that replaced them, and
    the roof doubles.

    A combined meter gives itself away wherever it overlaps the others: its
    output over those hours is their sum. The finer-grained meters are the
    ones worth keeping, since a roof read through several is described better
    than through one.
    """
    grouped: dict[str, dict[datetime, float]] = {}
    for interval in intervals:
        grouped.setdefault(interval.sample.source, {})[interval.sample.start] = (
            interval.sample.power
        )
    if len(grouped) < MIN_SOURCES_TO_COMPARE:
        return intervals

    redundant = set()
    for source, series in grouped.items():
        others = [
            other for name, other in grouped.items() if name not in {source, *redundant}
        ]
        shared = [
            when
            for when in series
            if all(when in other for other in others) and series[when] > 0.0
        ]
        if len(shared) < MIN_GROUP:
            continue
        mine = sum(series[when] for when in shared)
        theirs = sum(sum(other[when] for other in others) for when in shared)
        if theirs > 0.0 and abs(mine - theirs) <= COMBINED_TOLERANCE * theirs:
            LOGGER.warning(
                "%s reads the same panels as %s put together, so it is being "
                "left out of the fit rather than counted twice",
                source,
                " and ".join(name for name in grouped if name != source),
            )
            redundant.add(source)

    if not redundant:
        starts = {
            source: (min(series), max(series)) for source, series in grouped.items()
        }
        latest_start = max(first for first, _ in starts.values())
        earliest_end = min(last for _, last in starts.values())
        if latest_start > earliest_end:
            LOGGER.warning(
                "The sources to learn from cover different periods (%s), so "
                "whether they measure different panels cannot be checked. "
                "Their capacities are being added up; if one of them replaced "
                "the others rather than joining them, learn from only one",
                ", ".join(
                    f"{source}: {first:%Y-%m-%d} to {last:%Y-%m-%d}"
                    for source, (first, last) in starts.items()
                ),
            )
        return intervals

    return [
        interval for interval in intervals if interval.sample.source not in redundant
    ]


#: Ratios outside this band are not a rescaled roof, they are a broken
#: measurement -- a sensor in the wrong unit, or one that is not the panels at
#: all -- and following them would wreck a model that took a year to learn.
GAIN_LIMITS: Final = (0.4, 2.5)

#: Hours below this share of the learned capacity carry too little signal:
#: their ratio is dominated by the inverter's own poor efficiency down there.
MIN_GAIN_HOUR: Final = 0.15

#: Below this the rescaling is not worth mentioning in the log.
GAIN_WORTH_SAYING: Final = 0.02

#: Fewer than this and the ratio is an anecdote.
MIN_GAIN_HOURS: Final = 24


def calibrate(
    model: SolarModel,
    samples: Iterable[PowerSample],
    *,
    linke: float | None = None,
) -> SolarModel:
    """Return the model rescaled to what a meter is reporting now.

    Geometry and yield move on different clocks. Which way the panels face
    takes a year of seasons to establish and then never changes; how much the
    hardware behind them delivers can change overnight, when an inverter is
    replaced or a string is rewired. A model that has to relearn its geometry
    before it can notice that is a model that is wrong for a year.

    So the shape is kept and only the scale is refitted, from the ratio
    between what a meter reports and what the planes predict. That needs a few
    bright days rather than a season, which is exactly what is available after
    a change. The median is taken, so a single freak hour cannot move it, and
    the result is refused outright if it lands somewhere no rescaled roof
    could be -- a ratio of five is a broken sensor, not a better inverter.
    """
    if not model.arrays:
        return model
    intervals = [
        interval
        for interval in _prepare(
            samples, model.latitude, model.longitude, model.altitude, linke
        )
        # Only against a sky that was measured. Compared with a *modelled*
        # cloudless sky the ratio is the clear-sky index, which is below one
        # almost always -- calibrating on that would scale a perfectly good
        # roof down by however cloudy the fortnight happened to be.
        if interval.sample.sky is not None
    ]
    columns = [
        _column(
            array.tilt,
            array.azimuth,
            intervals,
            model.albedo,
            model.temperature_coefficient,
            horizon=model.horizon,
        )
        for array in model.arrays
    ]
    floor = model.peak_power * MIN_GAIN_HOUR
    ratios: list[float] = []
    for index, interval in enumerate(intervals):
        expected = sum(
            array.peak_power * column[index]
            for array, column in zip(model.arrays, columns, strict=True)
        )
        if expected >= floor and interval.sample.power > 0.0:
            ratios.append(interval.sample.power / expected)

    if len(ratios) < MIN_GAIN_HOURS:
        LOGGER.debug(
            "Only %d bright hours with a measured sky to calibrate against; "
            "leaving the scale alone",
            len(ratios),
        )
        return model

    gain = _quantile(ratios, 0.5)
    lowest, highest = GAIN_LIMITS
    if not lowest <= gain <= highest:
        LOGGER.warning(
            "Measured production is %.1fx what the learned roof predicts, which "
            "is too far out to be a rescaled roof; leaving the scale alone and "
            "assuming the meter is not measuring the panels",
            gain,
        )
        return model
    if abs(gain - 1.0) > GAIN_WORTH_SAYING:
        LOGGER.info(
            "Rescaling the learned roof by %.2f against %d recent bright hours: "
            "the panels are the same, what is behind them delivers differently",
            gain,
            len(ratios),
        )
    # The ceiling was read off the old hardware's own output, so it has to
    # travel with the scale. Left where it was it would clip the rescaled
    # curve back to the old inverter's midday plateau -- exactly the hours the
    # rescaling exists to fix.
    ceiling = None if model.ac_limit is None else model.ac_limit * gain / model.gain
    return replace(model, gain=gain, ac_limit=ceiling)


def _gather(
    samples: Sequence[PowerSample],
    latitude: float,
    longitude: float,
    altitude: float,
    linke: float | None,
) -> list[_Interval]:
    """Prepare the usable intervals, all under one kind of sky.

    Either every interval carries a measured sky or none of them does. The two
    kinds are not comparable -- a modelled sky and a measured one disagree
    about how a cloudless sky splits into hard beam and soft glow -- and a fit
    shown both reads that disagreement as geometry, answering with a
    north-facing plane and a vertical one. So when most skies were measured
    the bare handful is dropped, and when only a handful were, they are set
    aside and the whole window is modelled instead.
    """

    def prepared(use_measured: bool) -> list[_Interval]:
        intervals = _prepare(
            samples, latitude, longitude, altitude, linke, use_measured=use_measured
        )
        return [intervals[index] for index in _drop_clipped(intervals)]

    intervals = _drop_combined_sources(prepared(use_measured=True))
    measured = [
        index
        for index, interval in enumerate(intervals)
        if interval.sample.sky is not None
    ]
    if not measured:
        return intervals
    if len(measured) >= MEASURED_SHARE * len(intervals):
        return [intervals[index] for index in measured]
    return _drop_combined_sources(prepared(use_measured=False))


def _thin(
    indices: Sequence[int],
    intervals: Sequence[_Interval],
    limit: int = MAX_FIT_INTERVALS,
) -> list[int]:
    """Return at most ``limit`` intervals, spread evenly over the year.

    Thinning by taking every n-th interval would be simpler and wrong: the
    hours march in a daily cycle, so a stride can quietly line up with it and
    hand the fit only afternoons. Sampling proportionally from every
    month-and-hour bucket keeps the shape of the year, which is the very thing
    the tilt is read from.
    """
    if len(indices) <= limit:
        return list(indices)
    buckets: dict[tuple[int, int], list[int]] = {}
    for index in indices:
        buckets.setdefault(intervals[index].group, []).append(index)
    share = limit / len(indices)
    kept: list[int] = []
    for bucket in buckets.values():
        take = max(1, round(len(bucket) * share))
        step = len(bucket) / take
        kept.extend(bucket[int(position * step)] for position in range(take))
    return sorted(kept)


def _split_days(
    intervals: Sequence[_Interval],
) -> tuple[set[int], set[int]]:
    """Return the intervals to learn from, and the ones to be judged on.

    Every fifth day is held out of every fit. What differs between the two
    sets is how permissive they are.

    Learning wants evidence. Selecting cloudless intervals is a workaround for
    not knowing the sky, and when every interval carries a measured one there
    is nothing to work around: every hour becomes usable, cloud and all. That
    is far more evidence, and free of the quiet bias in "the brightest hours
    available" -- in a cloudy climate those are hazy rather than clear, and a
    fit scaled to them comes out short.

    Judging wants reliability, which is not the same thing. A reanalysis grid
    square is a poor account of the sky over one particular roof when that sky
    is broken cloud, so scoring a model on those hours largely measures the
    weather service. Under a clear sky the grid and the roof agree. So the
    model is judged -- how many planes it gets, whether a skyline earns its
    place -- only on hours whose sky is known to have been clear.
    """
    measured = all(interval.sample.sky is not None for interval in intervals)
    if measured:
        usable = set(range(len(intervals)))
        trusted = {
            index
            for index, interval in enumerate(intervals)
            if (interval.beam_fraction or 0.0) >= CLEAR_BEAM_FRACTION
        }
    else:
        usable = set(select_clear_intervals(intervals))
        trusted = usable

    training = {
        index for index in usable if intervals[index].sample.start.toordinal() % 5 != 0
    }
    judging = {
        index for index in trusted if intervals[index].sample.start.toordinal() % 5 == 0
    }
    return training, judging


def _add_horizon(
    plans: Sequence[_Plan],
    arrays: tuple[Array, ...],
    checking: Sequence[_Interval],
    holdout_r2: float,
    *,
    albedo: float,
    coefficient: float,
) -> tuple[tuple[Array, ...], Horizon, float]:
    """Learn what stands in front of the roof, and keep it only if it pays.

    The planes settle again with the skyline in place, because the two explain
    some of the same missing evening and have to share it out. Held-out days
    decide: a skyline is twelve more numbers to fit, and twelve numbers can
    always be made to flatter the days they were fitted on.
    """
    candidate = _fit_horizon(plans, albedo, coefficient)
    if candidate.is_flat:
        return arrays, NO_HORIZON, holdout_r2

    shaded: list[Array] = []
    for plan in plans:
        target = [interval.sample.power for interval in plan.intervals]
        settled, capacities, _ = _refine(
            [(tilt, azimuth, 0.0) for tilt, azimuth in plan.angles],
            plan.intervals,
            target,
            albedo,
            coefficient,
            horizon=candidate,
        )
        shaded.extend(
            Array(tilt=tilt, azimuth=azimuth, peak_power=capacity, source=plan.source)
            for (tilt, azimuth), capacity in zip(settled, capacities, strict=True)
            if capacity > 0.0
        )
    if not shaded:
        return arrays, NO_HORIZON, holdout_r2

    improved = tuple(sorted(shaded, key=lambda array: array.peak_power, reverse=True))
    score = _pooled_score(checking, improved, albedo, coefficient, horizon=candidate)[2]
    if score > holdout_r2 + MIN_HORIZON_GAIN:
        return improved, candidate, score
    return arrays, NO_HORIZON, holdout_r2


def fit(
    samples: Iterable[PowerSample],
    latitude: float,
    longitude: float,
    altitude: float = 0.0,
    *,
    tilts: Sequence[float] = COARSE_TILTS,
    azimuths: Sequence[float] = COARSE_AZIMUTHS,
    max_arrays: int = MAX_ARRAYS,
    linke: float | None = None,
    albedo: float = DEFAULT_ALBEDO,
    now: datetime | None = None,
) -> SolarModel | None:
    """Learn a site's roof planes from its production history.

    Returns None when the history is too thin to say anything honest about the
    geometry. Otherwise the model names every plane it found, with the tilt,
    the compass bearing and the capacity that together best explain what the
    inverters actually did.

    Sources are fitted one at a time. When a site has two inverters the sum of
    their output is a strictly poorer measurement than the pair -- the same
    roof read through one number instead of two -- and fitting them separately
    recovers noticeably sharper geometry. The planes are pooled afterwards, so
    the model still answers for the site as a whole, which is what a forecast
    and a single combined meter both need.
    """
    intervals = _gather(list(samples), latitude, longitude, altitude, linke)
    if len(intervals) < MIN_FIT_SAMPLES:
        return None
    orientations = _orientations(tilts, azimuths)

    # The temperature correction is only applied when every interval knows its
    # temperature. Applying it to some and not others would bake the average
    # summer derate into the capacity of whichever planes happened to lack it.
    coefficient = (
        DEFAULT_TEMPERATURE_COEFFICIENT
        if all(interval.sample.temperature is not None for interval in intervals)
        else 0.0
    )

    by_source: dict[str, list[int]] = {}
    for index, interval in enumerate(intervals):
        by_source.setdefault(interval.sample.source, []).append(index)

    # Selecting cloudless intervals is a workaround for not knowing the sky.
    # When every interval carries a measured one there is nothing to work
    # around: every hour becomes usable, cloud and all, which is both far more
    # evidence and free of the quiet bias in "the brightest hours available" --
    # in a cloudy climate those are hazy rather than clear, and a fit scaled to
    # them comes out short.
    training_days, held_out = _split_days(intervals)

    plans: list[_Plan] = []
    found: list[Array] = []
    for source, source_indices in by_source.items():
        training = [
            intervals[index]
            for index in _thin(
                sorted(training_days.intersection(source_indices)), intervals
            )
        ]
        checking = [
            intervals[index] for index in sorted(held_out.intersection(source_indices))
        ]
        if len(training) < MIN_FIT_SAMPLES:
            continue
        target = [interval.sample.power for interval in training]
        weights = nnls(
            [
                _column(tilt, azimuth, training, albedo, coefficient)
                for tilt, azimuth in orientations
            ],
            target,
        )

        best: tuple[float, list[tuple[float, float]], list[float]] | None = None
        for count in range(1, max_arrays + 1):
            planes = _cluster(weights, orientations, count)
            if not planes or (best is not None and len(planes) <= len(best[1])):
                break
            angles, capacities, _ = _refine(
                planes, training, target, albedo, coefficient
            )
            if checking:
                score = _score(checking, angles, capacities, albedo, coefficient)[2]
            else:
                # Too short a history to judge: trust the sparsity of the
                # decomposition and stop at the first answer it gives.
                score = 0.0 if best is None else best[0]
            if best is None or score > best[0] + MIN_HOLDOUT_GAIN:
                best = (score, angles, capacities)
            else:
                break

        if best is None:
            continue
        plans.append(_Plan(source=source, angles=best[1], intervals=training))
        found.extend(
            Array(tilt=tilt, azimuth=azimuth, peak_power=capacity, source=source)
            for (tilt, azimuth), capacity in zip(best[1], best[2], strict=True)
            if capacity > 0.0
        )

    if not found:
        return None

    fitted = sorted(training_days)
    evaluated = sorted(held_out)
    training_intervals = [intervals[index] for index in fitted]
    checking_intervals = [intervals[index] for index in evaluated]

    arrays = tuple(sorted(found, key=lambda array: array.peak_power, reverse=True))
    horizon = NO_HORIZON
    holdout_r2 = _pooled_score(
        checking_intervals, arrays, albedo, coefficient, horizon=horizon
    )[2]

    arrays, horizon, holdout_r2 = _add_horizon(
        plans,
        arrays,
        checking_intervals,
        holdout_r2,
        albedo=albedo,
        coefficient=coefficient,
    )

    rmse, mae, r2 = _pooled_score(
        training_intervals, arrays, albedo, coefficient, horizon=horizon
    )

    ceiling = sum(
        max((intervals[index].sample.power for index in source_indices), default=0.0)
        for source_indices in by_source.values()
    )

    return SolarModel(
        arrays=arrays,
        latitude=latitude,
        longitude=longitude,
        altitude=altitude,
        quality=FitQuality(
            samples=len(fitted),
            days=len({intervals[index].sample.start.date() for index in fitted}),
            rmse=rmse,
            mae=mae,
            r2=r2,
            holdout_r2=holdout_r2,
        ),
        created=now or datetime.now(tz=UTC),
        ac_limit=ceiling * _CEILING_HEADROOM if ceiling > 0.0 else None,
        temperature_coefficient=coefficient,
        albedo=albedo,
        horizon=horizon,
    )
