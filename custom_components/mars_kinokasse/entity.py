"""Base entities."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MarsCoordinator


def hub_device(c: MarsCoordinator) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, c.config_entry.entry_id)},
        name=c.config_entry.title,
        manufacturer="MARS",
        model="Kinokasse (GetRoWo-Export)",
    )


def screen_device(c: MarsCoordinator, screen: int) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"{c.config_entry.entry_id}_screen{screen}")},
        name=f"Kino{screen}.Spielplan",
        manufacturer="MARS + Kinoserver",
        model="Gesamtspielplan",
        via_device=(DOMAIN, c.config_entry.entry_id),
    )


class HubEntity(CoordinatorEntity[MarsCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: MarsCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{key}"
        self._attr_device_info = hub_device(coordinator)
        self._attr_translation_key = key


class ScreenEntity(CoordinatorEntity[MarsCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: MarsCoordinator, screen: int, key: str) -> None:
        super().__init__(coordinator)
        self.screen = screen
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_screen{screen}_{key}"
        self._attr_device_info = screen_device(coordinator, screen)
