"""Sensors per screen: viewers of the next/running show and the day values."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import MarsConfigEntry, MarsCoordinator
from .entity import HubEntity, ScreenEntity
from .logic import DayValues, MergedShow


@dataclass(frozen=True, kw_only=True)
class ScreenSensorDescription(SensorEntityDescription):
    value_fn: Callable[[DayValues], Any]
    show_fn: Callable[[DayValues], MergedShow | None] | None = None


def _viewers(show: MergedShow | None) -> int | None:
    return show.viewers if show else None


SENSORS: tuple[ScreenSensorDescription, ...] = (
    ScreenSensorDescription(
        key="next_viewers",
        translation_key="next_viewers",
        icon="mdi:account",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _viewers(d.next_show),
        show_fn=lambda d: d.next_show,
    ),
    ScreenSensorDescription(
        key="running_viewers",
        translation_key="running_viewers",
        icon="mdi:account-group",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _viewers(d.running),
        show_fn=lambda d: d.running,
    ),
    ScreenSensorDescription(
        key="next_start",
        translation_key="next_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: d.next_show.start if d.next_show else None,
        show_fn=lambda d: d.next_show,
    ),
    ScreenSensorDescription(
        key="first_start",
        translation_key="first_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: d.first_start,
        show_fn=lambda d: d.today[0] if d.today else None,
    ),
    ScreenSensorDescription(
        key="last_start",
        translation_key="last_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: d.last_start,
        show_fn=lambda d: d.today[-1] if d.today else None,
    ),
    ScreenSensorDescription(
        key="last_end",
        translation_key="last_end",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: d.last_end,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: MarsConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    c = entry.runtime_data
    entities: list[SensorEntity] = [MarsUpdated(c, "last_update")]
    for n in range(1, c.screens + 1):
        entities.extend(ScreenSensor(c, n, desc) for desc in SENSORS)
        entities.append(ShowsToday(c, n))
    async_add_entities(entities)


class ScreenSensor(ScreenEntity, SensorEntity):
    entity_description: ScreenSensorDescription

    def __init__(
        self, coordinator: MarsCoordinator, screen: int, description: ScreenSensorDescription
    ) -> None:
        super().__init__(coordinator, screen, description.key)
        self.entity_description = description

    def _day(self) -> DayValues | None:
        d = self.coordinator.data
        return d.day.get(self.screen) if d else None

    @property
    def native_value(self) -> Any:
        day = self._day()
        return self.entity_description.value_fn(day) if day else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        day = self._day()
        if day is None or self.entity_description.show_fn is None:
            return None
        show = self.entity_description.show_fn(day)
        return show.info() if show else None


class ShowsToday(ScreenEntity, SensorEntity):
    _attr_translation_key = "shows_today"
    _attr_icon = "mdi:filmstrip-box-multiple"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: MarsCoordinator, screen: int) -> None:
        super().__init__(coordinator, screen, "shows_today")

    def _day(self) -> DayValues | None:
        d = self.coordinator.data
        return d.day.get(self.screen) if d else None

    @property
    def native_value(self) -> int | None:
        day = self._day()
        return len(day.today) if day else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        day = self._day()
        if day is None:
            return None
        return {
            "liste": [
                {
                    "beginn": s.start.strftime("%H:%M"),
                    "ende": s.end.strftime("%H:%M"),
                    "titel": s.title,
                    "quelle": s.source,
                    "zuschauer": s.viewers,
                }
                for s in day.today
            ],
            "zuschauer_gesamt": sum(s.viewers or 0 for s in day.today),
        }


class MarsUpdated(HubEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> datetime | None:
        d = self.coordinator.data
        return d.mars_updated if d else None
