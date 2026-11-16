"""Merged show calendar per screen (cinema server + MARS ticket numbers)."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import MarsConfigEntry, MarsCoordinator
from .entity import ScreenEntity
from .logic import MergedShow


async def async_setup_entry(
    hass: HomeAssistant, entry: MarsConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    c = entry.runtime_data
    async_add_entities(MergedCalendar(c, n) for n in range(1, c.screens + 1))


def _event(show: MergedShow) -> CalendarEvent:
    return CalendarEvent(
        start=show.start,
        end=max(show.end, show.start),
        summary=show.summary(),
        description=show.description() or None,
        uid=show.key,
    )


class MergedCalendar(ScreenEntity, CalendarEntity):
    _attr_name = None  # entity name = device name -> calendar.kinoN_spielplan

    def __init__(self, coordinator: MarsCoordinator, screen: int) -> None:
        super().__init__(coordinator, screen, "spielplan")

    @property
    def event(self) -> CalendarEvent | None:
        shows = self.coordinator.data.merged.get(self.screen, []) if self.coordinator.data else []
        now = dt_util.now()
        current = next((s for s in shows if s.start <= now < s.end), None)
        if current is None:
            current = next((s for s in shows if s.start > now), None)
        return _event(current) if current else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        shows = await self.coordinator.merged_between(self.screen, start_date, end_date)
        return [_event(s) for s in shows]
