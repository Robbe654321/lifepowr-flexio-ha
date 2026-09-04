"""Config flow for the LIFEPOWR FlexiO integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import FlexioClient, FlexioConnectionError, FlexioError
from .const import DEFAULT_HOST, DEFAULT_NAME, DOMAIN, LOGGER

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, default=DEFAULT_HOST): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT, autocomplete="off")
        )
    }
)


class FlexioConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for LIFEPOWR FlexiO."""

    VERSION = 1

    async def _async_validate(self, host: str) -> str | None:
        """Return an error key, or None when the host is a working FlexiObox."""
        client = FlexioClient(async_get_clientsession(self.hass), host)
        try:
            await client.async_detect_layout()
        except FlexioConnectionError:
            return "cannot_connect"
        except FlexioError:
            return "invalid_response"
        except Exception:  # noqa: BLE001
            LOGGER.exception("Unexpected error validating %s", host)
            return "unknown"
        return None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            self._async_abort_entries_match({CONF_HOST: host})

            if (error := await self._async_validate(host)) is None:
                return self.async_create_entry(
                    title=DEFAULT_NAME, data={CONF_HOST: host}
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, user_input
            ),
            errors=errors,
            description_placeholders={"default_host": DEFAULT_HOST},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of an existing entry."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            if host != entry.data[CONF_HOST]:
                self._async_abort_entries_match({CONF_HOST: host})

            if (error := await self._async_validate(host)) is None:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_HOST: host}
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, user_input or dict(entry.data)
            ),
            errors=errors,
            description_placeholders={"default_host": DEFAULT_HOST},
        )
