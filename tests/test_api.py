"""Tests for the schema-tolerant payload parsing and endpoint selection."""

from __future__ import annotations

import re

import pytest

from custom_components.lifepowr import api
from homeassistant.helpers.aiohttp_client import async_get_clientsession

#: The exact example document from the on-device OpenAPI spec.
OPENAPI_MEASUREMENTS = {
    "batteryVoltageInvFiltered": 51.2,
    "batteryCurrentInvFiltered": 16.6,
    "TotalInvPowerFiltered": 0.85,
    "LoadPowerFiltered": 1.15,
    "MeterPowerFiltered": -2.27,
    "totalPVPowerFiltered": 3.42,
    "stateOfChargeFiltered": 78,
    "stateOfHealthFiltered": 99,
    "consumptionElectricityPrice": 0.1234,
    "timestamp": 1757000000,
}

OPENAPI_GENERIC_LOAD = {
    "genericLoadMaximumElectricityPrice": 0.25,
    "powerSetpointGeneric": 2.0,
    "timestamp": 1757000001,
}


def test_parse_openapi_measurements() -> None:
    """Every field of the documented measurements document is recognised."""
    assert api.parse_payload(OPENAPI_MEASUREMENTS) == {
        "battery_voltage": 51.2,
        "battery_current": 16.6,
        "inverter_power": 0.85,
        "load_power": 1.15,
        "grid_power": -2.27,
        "pv_power": 3.42,
        "battery_soc": 78.0,
        "battery_soh": 99.0,
        "electricity_price": 0.1234,
        "timestamp": 1757000000.0,
    }


def test_parse_openapi_generic_load() -> None:
    """Every field of the documented generic load document is recognised."""
    assert api.parse_payload(OPENAPI_GENERIC_LOAD) == {
        "generic_load_max_price": 0.25,
        "generic_load_power": 2.0,
        "timestamp": 1757000001.0,
    }


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        # Website spellings that differ from the OpenAPI spec.
        (
            {"totaalPVPowerFiltered": 3.4, "powetSetpoint": 1.5},
            {"pv_power": 3.4, "power_setpoint": 1.5},
        ),
        ({"consumptionElectrictyPrice": 0.12}, {"electricity_price": 0.12}),
        # Casing and separators do not matter.
        ({"state_of_charge_filtered": 55}, {"battery_soc": 55.0}),
        ({"STATEOFCHARGEFILTERED": 55}, {"battery_soc": 55.0}),
        ({"totalinvpowerfiltered": 0.5}, {"inverter_power": 0.5}),
        # Value objects and numeric strings.
        ({"stateOfChargeFiltered": {"value": 42, "unit": "%"}}, {"battery_soc": 42.0}),
        ({"stateOfChargeFiltered": "42,5"}, {"battery_soc": 42.5}),
        # Nested envelope.
        ({"ems": {"LoadPowerFiltered": 1.1}}, {"load_power": 1.1}),
        # Unknown fields ignored; booleans are not numbers.
        ({"somethingElse": 1, "stateOfChargeFiltered": True}, {}),
        # Non-mapping payloads yield nothing rather than raising.
        ([1, 2, 3], {}),
        (None, {}),
    ],
)
def test_parse_payload(payload, expected) -> None:
    """Plausible spellings and shapes map onto stable keys."""
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
    ("raw", "expected"),
    [
        (0, None),
        (-1, None),
        (1757000000, 1757000000.0),
        (1757000000000, 1757000000.0),
    ],
)
def test_normalise_timestamp(raw, expected) -> None:
    """Seconds pass through, milliseconds are scaled, zero is discarded."""
    assert api.normalise_timestamp(raw) == expected


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


async def test_setup_prefers_measurements_endpoint(hass, aioclient_mock) -> None:
    """The documented endpoint wins and device info is collected."""
    base = "http://myio.local/api"
    aioclient_mock.get(f"{base}/ems/measurements", json=OPENAPI_MEASUREMENTS)
    aioclient_mock.get(f"{base}/ems/generic-load", json=OPENAPI_GENERIC_LOAD)
    aioclient_mock.get(
        f"{base}/info/version", json={"version": "1.148.3", "builtTime": 0}
    )
    aioclient_mock.get(f"{base}/info/converter", json={"converter": "SolarEdge"})

    client = api.FlexioClient(async_get_clientsession(hass), "myio.local")
    assert await client.async_setup() is api.Layout.MEASUREMENTS
    assert client.version == "1.148.3"
    assert client.converter == "SolarEdge"
    assert client.supports_write is True

    data = await client.async_get_data()
    assert data["pv_power"] == 3.42
    assert data["generic_load_max_price"] == 0.25
    # The generic load timestamp must not overwrite the measurement one.
    assert data["timestamp"] == 1757000000.0


async def test_setup_falls_back_to_legacy_ems(hass, aioclient_mock) -> None:
    """A firmware without /ems/measurements still works."""
    base = "http://myio.local/api"
    aioclient_mock.get(f"{base}/ems/measurements", status=404)
    aioclient_mock.get(f"{base}/ems", json=OPENAPI_MEASUREMENTS)
    aioclient_mock.get(f"{base}/ems/load_control", status=404)
    aioclient_mock.get(f"{base}/info/version", status=404)
    aioclient_mock.get(f"{base}/info/converter", status=404)

    client = api.FlexioClient(async_get_clientsession(hass), "myio.local")
    assert await client.async_setup() is api.Layout.LEGACY_EMS
    assert client.version is None
    # No write support: the POST endpoint only exists on the documented layout.
    assert client.supports_write is False
    assert (await client.async_get_data())["pv_power"] == 3.42


async def test_setup_rejects_a_foreign_host(hass, aioclient_mock) -> None:
    """A host that answers with nothing recognisable is refused."""
    aioclient_mock.get("http://myio.local/api/ems/measurements", json={"hello": 1})
    aioclient_mock.get("http://myio.local/api/ems", json={"hello": 1})
    aioclient_mock.get(re.compile(r".*"), status=404)

    client = api.FlexioClient(async_get_clientsession(hass), "myio.local")
    with pytest.raises(api.FlexioResponseError):
        await client.async_setup()


async def test_set_max_price_posts_expected_body(hass, aioclient_mock) -> None:
    """The write uses POST with the documented body field."""
    url = "http://myio.local/api/ems/generic-load"
    aioclient_mock.post(url, json={"genericLoadMaximumElectricityPrice": 0.3})

    client = api.FlexioClient(async_get_clientsession(hass), "myio.local")
    assert await client.async_set_generic_load_max_price(0.3) == 0.3
    assert aioclient_mock.mock_calls[-1][2] == {"newMaxPrice": 0.3}


async def test_set_max_price_rejected(hass, aioclient_mock) -> None:
    """A 400 becomes a value error rather than a connection error."""
    aioclient_mock.post("http://myio.local/api/ems/generic-load", status=400)

    client = api.FlexioClient(async_get_clientsession(hass), "myio.local")
    with pytest.raises(api.FlexioValueError):
        await client.async_set_generic_load_max_price(-1)
