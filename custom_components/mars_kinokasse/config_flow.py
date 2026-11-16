"""Config flow of the MARS Kinokasse."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CALENDAR,
    CONF_DAY_START,
    CONF_KEEP_DAYS,
    CONF_SCAN_MINUTES,
    CONF_SCREENS,
    CONF_TOLERANCE,
    CONF_USER,
    DEFAULT_CALENDAR,
    DEFAULT_DAY_START,
    DEFAULT_KEEP_DAYS,
    DEFAULT_PORT,
    DEFAULT_SCAN_MINUTES,
    DEFAULT_SCREENS,
    DEFAULT_TOLERANCE,
    DOMAIN,
)
from .coordinator import MarsError, fetch_export
from .logic import MarsParseError, parse_export


async def _validate(hass, data: dict[str, Any]) -> int:
    raw = await fetch_export(
        async_get_clientsession(hass), data[CONF_HOST], int(data[CONF_PORT]),
        data[CONF_USER], data[CONF_PASSWORD],
    )
    return len(parse_export(raw, dt_util.get_default_time_zone()))


class MarsConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}")
            self._abort_if_unique_id_configured()
            try:
                await _validate(self.hass, user_input)
            except MarsError:
                errors["base"] = "cannot_connect"
            except MarsParseError:
                errors["base"] = "invalid_answer"
            else:
                name = user_input.pop(CONF_NAME)
                return self.async_create_entry(title=name, data=user_input)
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default="Kasse MARS"): str,
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.Coerce(int),
                vol.Required(CONF_USER): str,
                vol.Required(CONF_PASSWORD): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return MarsOptionsFlow()


class MarsOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        o = self.config_entry.options
        screens = int(o.get(CONF_SCREENS, DEFAULT_SCREENS))
        fields: dict[Any, Any] = {
            vol.Required(CONF_SCREENS, default=screens): vol.All(vol.Coerce(int), vol.Range(1, 9)),
            vol.Required(
                CONF_SCAN_MINUTES, default=o.get(CONF_SCAN_MINUTES, DEFAULT_SCAN_MINUTES)
            ): vol.All(vol.Coerce(int), vol.Range(1, 120)),
            vol.Required(
                CONF_TOLERANCE, default=o.get(CONF_TOLERANCE, DEFAULT_TOLERANCE)
            ): vol.All(vol.Coerce(int), vol.Range(0, 60)),
            vol.Required(
                CONF_DAY_START, default=o.get(CONF_DAY_START, DEFAULT_DAY_START)
            ): selector.TimeSelector(),
            vol.Required(
                CONF_KEEP_DAYS, default=o.get(CONF_KEEP_DAYS, DEFAULT_KEEP_DAYS)
            ): vol.All(vol.Coerce(int), vol.Range(1, 730)),
        }
        for n in range(1, screens + 1):
            key = CONF_CALENDAR.format(n)
            default = o.get(key, DEFAULT_CALENDAR.format(n))
            if default and self.hass.states.get(default) is None and key not in o:
                default = None
            marker = vol.Optional(key, description={"suggested_value": default}) if default else vol.Optional(key)
            fields[marker] = selector.EntitySelector(selector.EntitySelectorConfig(domain="calendar"))
        return self.async_show_form(step_id="init", data_schema=vol.Schema(fields))
