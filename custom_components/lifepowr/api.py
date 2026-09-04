"""Client for the LIFEPOWR FlexiO local API.

The FlexiObox exposes an unauthenticated REST API on the local network. The
public documentation describes two different response layouts and is
inconsistent about field spelling (``totaalPVPowerFiltered`` vs
``totalPVPowerFiltered``, ``powetSetpoint`` vs ``powerSetpoint``, ...), so this
client probes the box once and then normalises whatever it finds onto a stable
set of internal keys.
"""

from __future__ import annotations

import asyncio
from enum import StrEnum
from typing import Any, Final

from aiohttp import ClientError, ClientResponseError, ClientSession

from .const import LOGGER, REQUEST_TIMEOUT


class FlexioError(Exception):
    """Base error for the FlexiO API."""


class FlexioConnectionError(FlexioError):
    """Raised when the box cannot be reached."""


class FlexioResponseError(FlexioError):
    """Raised when the box returns something unusable."""


class Layout(StrEnum):
    """Response layout used by this particular firmware."""

    #: A single ``/api/ems`` document holding every measurement.
    AGGREGATE = "aggregate"
    #: One endpoint per measurement, e.g. ``/api/stateOfChargeFiltered``.
    PER_FIELD = "per_field"


# Internal, stable keys. Entities reference these, never the raw field names.
KEY_BATTERY_CURRENT: Final = "battery_current"
KEY_BATTERY_VOLTAGE: Final = "battery_voltage"
KEY_INVERTER_POWER: Final = "inverter_power"
KEY_LOAD_POWER: Final = "load_power"
KEY_GRID_POWER: Final = "grid_power"
KEY_PV_POWER: Final = "pv_power"
KEY_BATTERY_SOC: Final = "battery_soc"
KEY_BATTERY_SOH: Final = "battery_soh"
KEY_POWER_SETPOINT: Final = "power_setpoint"
KEY_ELECTRICITY_PRICE: Final = "electricity_price"
KEY_GENERIC_LOAD_POWER: Final = "generic_load_power"
KEY_GENERIC_LOAD_MAX_PRICE: Final = "generic_load_max_price"

#: Raw field names, as documented, per internal key. Matching is done on a
#: normalised (lowercase, alphanumeric-only) form so casing and separators in
#: the firmware's actual spelling do not matter.
FIELD_ALIASES: Final[dict[str, tuple[str, ...]]] = {
    KEY_BATTERY_CURRENT: ("batteryCurrentInvFiltered",),
    KEY_BATTERY_VOLTAGE: ("batteryVoltageInvFiltered",),
    # Matching is case-insensitive, so only genuinely different spellings need
    # to be listed here.
    KEY_INVERTER_POWER: ("totalInvPowerFiltered",),
    KEY_LOAD_POWER: ("LoadPowerFiltered",),
    KEY_GRID_POWER: ("MeterPowerFiltered",),
    KEY_PV_POWER: ("totalPVPowerFiltered", "totaalPVPowerFiltered"),
    KEY_BATTERY_SOC: ("stateOfChargeFiltered",),
    KEY_BATTERY_SOH: ("stateOfHealthFiltered",),
    KEY_POWER_SETPOINT: ("powerSetpoint", "powetSetpoint"),
    KEY_ELECTRICITY_PRICE: (
        "consumptionElectricityPrice",
        "consumptionElectrictyPrice",
    ),
    KEY_GENERIC_LOAD_POWER: ("powerSetpointGeneric",),
    KEY_GENERIC_LOAD_MAX_PRICE: ("genericLoadMaximumElectricityPrice",),
}

#: Keys that the docs place behind ``/api/ems/load_control`` rather than
#: ``/api/ems``.
LOAD_CONTROL_KEYS: Final = frozenset(
    {KEY_GENERIC_LOAD_POWER, KEY_GENERIC_LOAD_MAX_PRICE}
)

PATH_EMS: Final = "ems"
PATH_LOAD_CONTROL: Final = "ems/load_control"


def _normalise(name: str) -> str:
    """Reduce a field name to a comparable form."""
    return "".join(char for char in name if char.isalnum()).lower()


_ALIAS_LOOKUP: Final[dict[str, str]] = {
    _normalise(alias): key
    for key, aliases in FIELD_ALIASES.items()
    for alias in aliases
}


def _coerce_value(raw: Any) -> float | None:
    """Return a float from the many shapes the box may use for a value.

    Accepts a bare number, a numeric string, or a mapping such as
    ``{"value": 1.23, "unit": "kW"}``.
    """
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        try:
            return float(raw.strip().replace(",", "."))
        except ValueError:
            return None
    if isinstance(raw, dict):
        for candidate in ("value", "val", "data", "result"):
            if candidate in raw:
                return _coerce_value(raw[candidate])
    return None


def parse_payload(payload: Any) -> dict[str, float]:
    """Map an arbitrary API document onto the internal keys.

    Unknown fields are ignored; nested objects are walked one level deep so a
    ``{"ems": {...}}`` style envelope is handled too.
    """
    result: dict[str, float] = {}

    def _walk(node: Any, depth: int) -> None:
        if depth > 3 or not isinstance(node, dict):
            return
        for raw_name, raw_value in node.items():
            key = _ALIAS_LOOKUP.get(_normalise(str(raw_name)))
            if key is not None:
                value = _coerce_value(raw_value)
                if value is not None:
                    result[key] = value
                continue
            if isinstance(raw_value, dict):
                _walk(raw_value, depth + 1)

    _walk(payload, 0)
    return result


class FlexioClient:
    """Talk to a FlexiObox on the local network."""

    def __init__(self, session: ClientSession, host: str) -> None:
        """Initialise the client for a given host or IP address."""
        self._session = session
        self._host = host.strip().rstrip("/")
        self.layout: Layout | None = None
        #: Raw field names discovered on this box, per internal key. Only used
        #: by the per-field layout.
        self._field_paths: dict[str, str] = {}

    @property
    def host(self) -> str:
        """Return the configured host."""
        return self._host

    @property
    def base_url(self) -> str:
        """Return the API root for the configured host."""
        host = self._host
        if not host.startswith(("http://", "https://")):
            host = f"http://{host}"
        return f"{host}/api"

    async def _get(self, path: str) -> Any:
        """Perform a GET and return the decoded body."""
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                response = await self._session.get(url)
                if response.status == 404:
                    raise FlexioResponseError(f"{url} returned 404")
                response.raise_for_status()
                # The box has been observed serving JSON as text/plain.
                return await response.json(content_type=None)
        except ClientResponseError as err:
            raise FlexioResponseError(f"{url} returned {err.status}") from err
        except (ClientError, asyncio.TimeoutError, TimeoutError) as err:
            raise FlexioConnectionError(f"Cannot reach {url}: {err}") from err
        except ValueError as err:
            raise FlexioResponseError(f"{url} returned invalid JSON") from err

    async def async_detect_layout(self) -> Layout:
        """Determine which response layout this box uses.

        Raises FlexioConnectionError when the box is unreachable and
        FlexioResponseError when it responds but exposes nothing recognisable.
        """
        try:
            payload = await self._get(PATH_EMS)
        except FlexioResponseError:
            payload = None

        if payload is not None and parse_payload(payload):
            self.layout = Layout.AGGREGATE
            return self.layout

        # Fall back to probing individual endpoints.
        discovered: dict[str, str] = {}
        for key, aliases in FIELD_ALIASES.items():
            for alias in aliases:
                try:
                    value = _coerce_value(await self._get(alias))
                except FlexioResponseError:
                    continue
                if value is not None:
                    discovered[key] = alias
                    break

        if not discovered:
            raise FlexioResponseError(
                "No recognisable FlexiO measurements found on this host"
            )

        LOGGER.debug("Discovered per-field endpoints: %s", sorted(discovered))
        self._field_paths = discovered
        self.layout = Layout.PER_FIELD
        return self.layout

    async def async_get_data(self) -> dict[str, float]:
        """Return all currently available measurements."""
        if self.layout is None:
            await self.async_detect_layout()

        if self.layout is Layout.AGGREGATE:
            data = parse_payload(await self._get(PATH_EMS))
            try:
                data |= parse_payload(await self._get(PATH_LOAD_CONTROL))
            except FlexioResponseError:
                # Load control is optional; not every box exposes it.
                LOGGER.debug("Load control endpoint unavailable")
            if not data:
                raise FlexioResponseError("Box returned no known measurements")
            return data

        results = await asyncio.gather(
            *(self._get(path) for path in self._field_paths.values()),
            return_exceptions=True,
        )
        data = {}
        for key, result in zip(self._field_paths, results, strict=True):
            if isinstance(result, FlexioConnectionError):
                raise result
            if isinstance(result, BaseException):
                continue
            value = _coerce_value(result)
            if value is not None:
                data[key] = value
        if not data:
            raise FlexioResponseError("Box returned no known measurements")
        return data
