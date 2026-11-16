"""Connection state of the MARS export."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import MarsConfigEntry
from .entity import HubEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: MarsConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([MarsConnection(entry.runtime_data, "connection")])


class MarsConnection(HubEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data and self.coordinator.data.mars_ok)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data
        return {
            "fehler": d.mars_error if d else None,
            "gespeicherte_vorstellungen": len(self.coordinator.book),
            "kinoserver_kalender": {
                f"kino{n}": self.coordinator.calendars.get(n) for n in self.coordinator.calendars
            },
            "kinoserver_ok": {f"kino{n}": ok for n, ok in (d.server_ok.items() if d else [])},
        }
