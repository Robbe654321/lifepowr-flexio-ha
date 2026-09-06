"""Client for the LIFEPOWR FlexiO local API.

The field mapping lives in :mod:`parsing`, which has no third-party
dependencies; this module only adds the HTTP layer and endpoint selection.
"""

from __future__ import annotations

import asyncio
from enum import StrEnum

from aiohttp import ClientError, ClientResponseError, ClientSession

from .const import LOGGER, REQUEST_TIMEOUT
from .parsing import (  # noqa: F401  (re-exported for entity platforms)
    ALIAS_LOOKUP,
    FIELD_ALIASES,
    FIELD_NEW_MAX_PRICE,
    KEY_BATTERY_CURRENT,
    KEY_BATTERY_POWER,
    KEY_BATTERY_SOC,
    KEY_BATTERY_SOH,
    KEY_BATTERY_VOLTAGE,
    KEY_ELECTRICITY_PRICE,
    KEY_GENERIC_LOAD_MAX_PRICE,
    KEY_GENERIC_LOAD_POWER,
    KEY_GRID_POWER,
    KEY_INVERTER_POWER,
    KEY_LOAD_POWER,
    KEY_POWER_SETPOINT,
    KEY_PV_POWER,
    KEY_TIMESTAMP,
    PATH_CONVERTER,
    PATH_GENERIC_LOAD,
    PATH_LEGACY_EMS,
    PATH_LEGACY_LOAD_CONTROL,
    PATH_MEASUREMENTS,
    PATH_VERSION,
    apply_derived,
    coerce_value,
    normalise_name,
    normalise_timestamp,
    parse_payload,
)


class FlexioError(Exception):
    """Base error for the FlexiO API."""


class FlexioConnectionError(FlexioError):
    """Raised when the box cannot be reached."""


class FlexioResponseError(FlexioError):
    """Raised when the box returns something unusable."""


class FlexioValueError(FlexioError):
    """Raised when the box rejects a value we tried to write."""


class Layout(StrEnum):
    """Response layout used by this particular firmware."""

    #: Documented by the on-device OpenAPI spec: /api/ems/measurements.
    MEASUREMENTS = "measurements"
    #: Older/alternative layout described by the public web docs: /api/ems.
    LEGACY_EMS = "legacy_ems"
    #: One endpoint per measurement, e.g. /api/stateOfChargeFiltered.
    PER_FIELD = "per_field"


class FlexioClient:
    """Talk to a FlexiObox on the local network."""

    def __init__(self, session: ClientSession, host: str) -> None:
        """Initialise the client for a given host or IP address."""
        self._session = session
        self._host = host.strip().rstrip("/")
        self.layout: Layout | None = None
        self.version: str | None = None
        self.converter: str | None = None
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

    @property
    def supports_write(self) -> bool:
        """Return True when this box exposes the generic load POST endpoint."""
        return self.layout is Layout.MEASUREMENTS

    async def _request(
        self, method: str, path: str, json: dict[str, float] | None = None
    ) -> object:
        """Perform a request and return the decoded body."""
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                response = await self._session.request(method, url, json=json)
                if response.status == 400:
                    raise FlexioValueError(f"{url} rejected the value")
                if response.status in (404, 500):
                    raise FlexioResponseError(f"{url} returned {response.status}")
                response.raise_for_status()
                # The box has been observed serving JSON as text/plain, and
                # serves HTML error pages via nginx/Express on failures.
                return await response.json(content_type=None)
        except ClientResponseError as err:
            raise FlexioResponseError(f"{url} returned {err.status}") from err
        except (ClientError, TimeoutError) as err:
            raise FlexioConnectionError(f"Cannot reach {url}: {err}") from err
        except ValueError as err:
            raise FlexioResponseError(f"{url} did not return JSON") from err

    async def _get(self, path: str) -> object:
        """Perform a GET and return the decoded body."""
        return await self._request("GET", path)

    async def _try_get(self, path: str) -> object | None:
        """GET a path, returning None instead of raising on a bad response."""
        try:
            return await self._get(path)
        except FlexioResponseError:
            return None

    async def async_setup(self) -> Layout:
        """Determine the layout and collect device information.

        Raises FlexioConnectionError when the box is unreachable and
        FlexioResponseError when it responds but exposes nothing recognisable.
        """
        layout = await self._async_detect_layout()
        await self._async_fetch_device_info()
        return layout

    async def _async_detect_layout(self) -> Layout:
        """Work out which response layout this box uses."""
        for path, layout in (
            (PATH_MEASUREMENTS, Layout.MEASUREMENTS),
            (PATH_LEGACY_EMS, Layout.LEGACY_EMS),
        ):
            payload = await self._try_get(path)
            if payload is not None and parse_payload(payload):
                LOGGER.debug("Detected %s layout at %s", layout, path)
                self.layout = layout
                return layout

        # Last resort: probe one endpoint per documented field.
        discovered: dict[str, str] = {}
        for key, aliases in FIELD_ALIASES.items():
            if key == KEY_TIMESTAMP:
                continue
            for alias in aliases:
                if coerce_value(await self._try_get(alias)) is not None:
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

    async def _async_fetch_device_info(self) -> None:
        """Collect software version and converter type, if exposed."""
        if isinstance(payload := await self._try_get(PATH_VERSION), dict):
            if version := payload.get("version"):
                self.version = str(version)
        if isinstance(payload := await self._try_get(PATH_CONVERTER), dict):
            if converter := payload.get("converter"):
                self.converter = str(converter)

    async def async_get_data(self) -> dict[str, float]:
        """Return all currently available measurements."""
        if self.layout is None:
            await self.async_setup()

        if self.layout is Layout.PER_FIELD:
            return await self._async_get_data_per_field()

        if self.layout is Layout.MEASUREMENTS:
            measurements_path = PATH_MEASUREMENTS
            load_path = PATH_GENERIC_LOAD
        else:
            measurements_path = PATH_LEGACY_EMS
            load_path = PATH_LEGACY_LOAD_CONTROL

        data = parse_payload(await self._get(measurements_path))

        # The generic load endpoint is optional and carries its own timestamp,
        # which must not overwrite the measurement timestamp.
        if (payload := await self._try_get(load_path)) is not None:
            load_data = parse_payload(payload)
            load_data.pop(KEY_TIMESTAMP, None)
            data |= load_data
        else:
            LOGGER.debug("Generic load endpoint unavailable")

        if not data:
            raise FlexioResponseError("Box returned no known measurements")
        return apply_derived(data)

    async def _async_get_data_per_field(self) -> dict[str, float]:
        """Fetch every measurement from its own endpoint."""
        results = await asyncio.gather(
            *(self._get(path) for path in self._field_paths.values()),
            return_exceptions=True,
        )
        data: dict[str, float] = {}
        for key, result in zip(self._field_paths, results, strict=True):
            if isinstance(result, FlexioConnectionError):
                raise result
            if isinstance(result, BaseException):
                continue
            if (value := coerce_value(result)) is not None:
                data[key] = value
        if not data:
            raise FlexioResponseError("Box returned no known measurements")
        return apply_derived(data)

    async def async_set_generic_load_max_price(self, price: float) -> float | None:
        """Set the generic load's maximum electricity price.

        Returns the value the box confirms, or None when it confirms nothing.
        Raises FlexioValueError when the box rejects the price.
        """
        payload = await self._request(
            "POST", PATH_GENERIC_LOAD, json={FIELD_NEW_MAX_PRICE: price}
        )
        if isinstance(payload, dict):
            return parse_payload(payload).get(KEY_GENERIC_LOAD_MAX_PRICE)
        return None
