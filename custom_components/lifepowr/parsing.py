"""Field mapping for the LIFEPOWR FlexiO API.

This module deliberately has no dependencies beyond the standard library, so
the mapping can be exercised without Home Assistant or aiohttp installed --
see ``scripts/check_box.py``.

Endpoint and field names follow the on-device OpenAPI document (``FlexiO
Device API``, firmware 1.148.3). LIFEPOWR's website documentation disagrees
with that spec on endpoint paths, the write method, and the spelling of
several fields, so alternative spellings are listed here as aliases.
"""

from __future__ import annotations

from typing import Any, Final

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
KEY_TIMESTAMP: Final = "timestamp"

#: Derived, not reported by the box. ``TotalInvPowerFiltered`` is the inverter's
#: total AC power, which already contains the solar production; the battery's
#: own flow is what remains after subtracting PV. Confirmed against the vendor
#: app, which shows exactly this as "Batterij".
KEY_BATTERY_POWER: Final = "battery_power"

#: Raw field names per internal key. Matching is done on a normalised
#: (lowercase, alphanumeric-only) form, so casing and separators do not matter
#: and only genuinely different spellings need to be listed.
FIELD_ALIASES: Final[dict[str, tuple[str, ...]]] = {
    KEY_BATTERY_CURRENT: ("batteryCurrentInvFiltered",),
    KEY_BATTERY_VOLTAGE: ("batteryVoltageInvFiltered",),
    KEY_INVERTER_POWER: ("TotalInvPowerFiltered",),
    KEY_LOAD_POWER: ("LoadPowerFiltered",),
    KEY_GRID_POWER: ("MeterPowerFiltered",),
    KEY_PV_POWER: ("totalPVPowerFiltered", "totaalPVPowerFiltered"),
    KEY_BATTERY_SOC: ("stateOfChargeFiltered",),
    KEY_BATTERY_SOH: ("stateOfHealthFiltered",),
    # Not in the OpenAPI spec, but documented on the website; harmless to look
    # for and picked up automatically if a firmware exposes it.
    KEY_POWER_SETPOINT: ("powerSetpoint", "powetSetpoint"),
    KEY_ELECTRICITY_PRICE: (
        "consumptionElectricityPrice",
        "consumptionElectrictyPrice",
    ),
    KEY_GENERIC_LOAD_POWER: ("powerSetpointGeneric",),
    KEY_GENERIC_LOAD_MAX_PRICE: ("genericLoadMaximumElectricityPrice",),
    KEY_TIMESTAMP: ("timestamp",),
}

PATH_VERSION: Final = "info/version"
PATH_CONVERTER: Final = "info/converter"
PATH_MEASUREMENTS: Final = "ems/measurements"
PATH_GENERIC_LOAD: Final = "ems/generic-load"
#: Layouts described by the public web docs, tried only as a fallback.
PATH_LEGACY_EMS: Final = "ems"
PATH_LEGACY_LOAD_CONTROL: Final = "ems/load_control"

#: Body field the box expects when setting the generic load price cap.
FIELD_NEW_MAX_PRICE: Final = "newMaxPrice"

#: Epoch values above this are milliseconds rather than seconds.
_MS_THRESHOLD: Final = 1e11


def normalise_name(name: str) -> str:
    """Reduce a field name to a comparable form."""
    return "".join(char for char in name if char.isalnum()).lower()


ALIAS_LOOKUP: Final[dict[str, str]] = {
    normalise_name(alias): key
    for key, aliases in FIELD_ALIASES.items()
    for alias in aliases
}


def coerce_value(raw: Any) -> float | None:
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
                return coerce_value(raw[candidate])
    return None


def normalise_timestamp(raw: float) -> float | None:
    """Return a POSIX timestamp in seconds, or None when unusable.

    The box reports an epoch whose unit is not stated in the spec; values that
    are implausibly large are treated as milliseconds. A zero timestamp means
    "never set" and is discarded.
    """
    if raw <= 0:
        return None
    return raw / 1000 if raw > _MS_THRESHOLD else raw


def apply_derived(data: dict[str, float]) -> dict[str, float]:
    """Add values the box does not report but that follow from the ones it does.

    ``TotalInvPowerFiltered`` is the whole inverter, solar included. Treating it
    as the battery makes every sunny hour look like a discharge, so the battery
    flow is derived here instead:

        battery = inverter - PV

    Same sign convention as the inverter: positive discharging, negative
    charging. Skipped when either input is missing.
    """
    if KEY_INVERTER_POWER in data and KEY_PV_POWER in data:
        data[KEY_BATTERY_POWER] = data[KEY_INVERTER_POWER] - data[KEY_PV_POWER]
    return data


def parse_payload(payload: Any) -> dict[str, float]:
    """Map an arbitrary API document onto the internal keys.

    Unknown fields are ignored; nested objects are walked a few levels deep so
    a ``{"ems": {...}}`` style envelope is handled too.
    """
    result: dict[str, float] = {}

    def _walk(node: Any, depth: int) -> None:
        if depth > 3 or not isinstance(node, dict):
            return
        for raw_name, raw_value in node.items():
            key = ALIAS_LOOKUP.get(normalise_name(str(raw_name)))
            if key is not None:
                value = coerce_value(raw_value)
                if value is not None:
                    result[key] = value
                continue
            if isinstance(raw_value, dict):
                _walk(raw_value, depth + 1)

    _walk(payload, 0)
    return result
