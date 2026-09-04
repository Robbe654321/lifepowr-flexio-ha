"""Tests for the schema-tolerant payload parsing."""

from __future__ import annotations

import pytest

from custom_components.lifepowr import api


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        # Flat document, documented spelling.
        (
            {"stateOfChargeFiltered": 78, "totalPVPowerFiltered": 3.4},
            {"battery_soc": 78.0, "pv_power": 3.4},
        ),
        # The Dutch docs' alternative spellings.
        (
            {"totaalPVPowerFiltered": 3.4, "powetSetpoint": 1.5},
            {"pv_power": 3.4, "power_setpoint": 1.5},
        ),
        # Both electricity price spellings.
        ({"consumptionElectrictyPrice": 0.12}, {"electricity_price": 0.12}),
        ({"consumptionElectricityPrice": 0.12}, {"electricity_price": 0.12}),
        # snake_case or different casing from a future firmware.
        ({"state_of_charge_filtered": 55}, {"battery_soc": 55.0}),
        ({"STATEOFCHARGEFILTERED": 55}, {"battery_soc": 55.0}),
        # Value objects.
        (
            {"stateOfChargeFiltered": {"value": 42, "unit": "%"}},
            {"battery_soc": 42.0},
        ),
        # Numeric strings, including a comma decimal separator.
        ({"stateOfChargeFiltered": "42,5"}, {"battery_soc": 42.5}),
        # Nested envelope.
        ({"ems": {"LoadPowerFiltered": 1.1}}, {"load_power": 1.1}),
        # Unknown fields are ignored, booleans are not numbers.
        ({"somethingElse": 1, "stateOfChargeFiltered": True}, {}),
        # Non-mapping payloads yield nothing rather than raising.
        ([1, 2, 3], {}),
        (None, {}),
    ],
)
def test_parse_payload(payload, expected) -> None:
    """Every documented and plausible spelling maps onto stable keys."""
    assert api.parse_payload(payload) == expected


def test_every_key_has_aliases() -> None:
    """No internal key may be left without a raw field name."""
    for key, aliases in api.FIELD_ALIASES.items():
        assert aliases, f"{key} has no aliases"


def test_aliases_are_unambiguous() -> None:
    """Two internal keys must never normalise to the same raw field."""
    seen: dict[str, str] = {}
    for key, aliases in api.FIELD_ALIASES.items():
        for alias in aliases:
            normalised = api._normalise(alias)
            assert normalised not in seen, f"{alias} maps to {seen.get(normalised)}"
            seen[normalised] = key


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (1, 1.0),
        (1.5, 1.5),
        ("1.5", 1.5),
        ("1,5", 1.5),
        (" 2 ", 2.0),
        ({"value": 3}, 3.0),
        ({"val": 3}, 3.0),
        (True, None),
        ("abc", None),
        (None, None),
        ({}, None),
    ],
)
def test_coerce_value(raw, expected) -> None:
    """Values arrive in several shapes and all become floats or None."""
    assert api._coerce_value(raw) == expected


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("myio.local", "http://myio.local/api"),
        ("192.168.1.20", "http://192.168.1.20/api"),
        ("http://myio.local", "http://myio.local/api"),
        ("http://myio.local/", "http://myio.local/api"),
        ("https://myio.local", "https://myio.local/api"),
    ],
)
def test_base_url(host, expected) -> None:
    """Hosts are accepted with or without a scheme or trailing slash."""
    assert api.FlexioClient(None, host).base_url == expected
