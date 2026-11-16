"""Coordinator: reads the MARS export and merges it with the cinema server calendars."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
import logging
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
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
    DEFAULT_SCAN_MINUTES,
    DEFAULT_SCREENS,
    DEFAULT_TOLERANCE,
    DOMAIN,
    REQUEST_TIMEOUT,
    SERVER_LOOKAHEAD_DAYS,
    STORE_VERSION,
    TICK_SECONDS,
)
from .logic import (
    DayValues,
    MarsParseError,
    MarsShow,
    MergedShow,
    ServerEvent,
    day_values,
    merge,
    parse_export,
    update_book,
)

_LOGGER = logging.getLogger(__name__)

type MarsConfigEntry = ConfigEntry[MarsCoordinator]


class MarsError(Exception):
    """MARS not reachable or wrong answer."""


async def fetch_export(
    session: aiohttp.ClientSession, host: str, port: int, user: str, password: str
) -> bytes:
    url = f"http://{host}:{port}/GetRoWo"
    try:
        async with asyncio.timeout(REQUEST_TIMEOUT):
            async with session.get(
                url, params={"GetRoWoID": user, "GetRoWoPass": password}
            ) as resp:
                if resp.status != 200:
                    raise MarsError(f"HTTP {resp.status}")
                return await resp.read()
    except (aiohttp.ClientError, TimeoutError) as err:
        raise MarsError(str(err) or type(err).__name__) from err


@dataclass
class MarsData:
    mars_ok: bool = False
    mars_error: str | None = None
    mars_updated: datetime | None = None
    server_ok: dict[int, bool] = field(default_factory=dict)
    merged: dict[int, list[MergedShow]] = field(default_factory=dict)
    day: dict[int, DayValues] = field(default_factory=dict)


def _opt(entry: ConfigEntry, key: str, default: Any) -> Any:
    return entry.options.get(key, entry.data.get(key, default))


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return dt_util.as_local(value)
    if not isinstance(value, str) or "T" not in value:
        return None  # all-day events are no shows
    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        return None
    return dt_util.as_local(parsed)


class MarsCoordinator(DataUpdateCoordinator[MarsData]):
    config_entry: MarsConfigEntry

    def __init__(self, hass: HomeAssistant, entry: MarsConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=timedelta(seconds=TICK_SECONDS),
        )
        self.screens: int = int(_opt(entry, CONF_SCREENS, DEFAULT_SCREENS))
        self.scan = timedelta(minutes=int(_opt(entry, CONF_SCAN_MINUTES, DEFAULT_SCAN_MINUTES)))
        self.tolerance = timedelta(minutes=int(_opt(entry, CONF_TOLERANCE, DEFAULT_TOLERANCE)))
        self.keep_days = int(_opt(entry, CONF_KEEP_DAYS, DEFAULT_KEEP_DAYS))
        self.day_start: time = dt_util.parse_time(
            str(_opt(entry, CONF_DAY_START, DEFAULT_DAY_START))
        ) or time(4, 0)
        self.calendars: dict[int, str | None] = {
            n: (_opt(entry, CONF_CALENDAR.format(n), DEFAULT_CALENDAR.format(n)) or None)
            for n in range(1, self.screens + 1)
        }
        self._session = async_get_clientsession(hass)
        self._store: Store[dict[str, Any]] = Store(
            hass, STORE_VERSION, f"{DOMAIN}_{entry.entry_id}"
        )
        self.book: dict[str, MarsShow] = {}
        self._last_try: datetime | None = None
        self._state = MarsData()

    # ------------------------------------------------------------ setup / store

    async def async_load(self) -> None:
        stored = await self._store.async_load() or {}
        for raw in stored.get("shows", []):
            try:
                show = MarsShow.from_store(raw)
            except (KeyError, ValueError, TypeError):
                continue
            self.book[show.show_id] = show
        if stored.get("updated"):
            self._state.mars_updated = dt_util.parse_datetime(stored["updated"])

    def _save(self) -> None:
        self._store.async_delay_save(
            lambda: {
                "updated": self._state.mars_updated.isoformat() if self._state.mars_updated else None,
                "shows": [s.to_store() for s in self.book.values()],
            },
            10,
        )

    # ------------------------------------------------------------ update

    async def _fetch_mars(self, now: datetime) -> None:
        d = self.config_entry.data
        try:
            raw = await fetch_export(
                self._session, d[CONF_HOST], int(d[CONF_PORT]), d[CONF_USER], d[CONF_PASSWORD]
            )
            fresh = parse_export(raw, dt_util.get_default_time_zone())
        except (MarsError, MarsParseError) as err:
            if self._state.mars_ok or self._state.mars_error is None:
                _LOGGER.warning("MARS-Kasse nicht lesbar: %s (letzter Stand bleibt)", err)
            self._state.mars_ok = False
            self._state.mars_error = str(err)
            return
        self.book = update_book(self.book, fresh, now, self.keep_days)
        if not self._state.mars_ok and self._state.mars_error:
            _LOGGER.info("MARS-Kasse wieder erreichbar")
        self._state.mars_ok = True
        self._state.mars_error = None
        self._state.mars_updated = now
        self._save()

    async def server_events(
        self, screen: int, start: datetime, end: datetime
    ) -> list[ServerEvent] | None:
        """Events of the cinema server calendar; None if it is not available."""
        entity_id = self.calendars.get(screen)
        if not entity_id or self.hass.states.get(entity_id) is None:
            return None
        try:
            resp = await self.hass.services.async_call(
                "calendar",
                "get_events",
                {"entity_id": entity_id, "start_date_time": start, "end_date_time": end},
                blocking=True,
                return_response=True,
            )
        except Exception as err:  # noqa: BLE001 - the server calendar is optional
            _LOGGER.debug("Kalender %s nicht lesbar: %s", entity_id, err)
            return None
        events = (resp or {}).get(entity_id, {}).get("events", [])
        result: list[ServerEvent] = []
        for ev in events:
            s = _parse_dt(ev.get("start"))
            e = _parse_dt(ev.get("end"))
            if s is None or e is None:
                continue
            result.append(
                ServerEvent(
                    start=s,
                    end=e,
                    summary=ev.get("summary") or "",
                    description=ev.get("description") or "",
                )
            )
        return result

    def mars_between(self, screen: int, start: datetime, end: datetime) -> list[MarsShow]:
        return [
            s for s in self.book.values()
            if s.screen == screen and s.end >= start and s.start < end
        ]

    async def merged_between(self, screen: int, start: datetime, end: datetime) -> list[MergedShow]:
        server = await self.server_events(screen, start, end) or []
        return merge(server, self.mars_between(screen, start, end), self.tolerance)

    async def _async_update_data(self) -> MarsData:
        now = dt_util.now()
        if self._last_try is None or now - self._last_try >= self.scan:
            self._last_try = now
            await self._fetch_mars(now)
        start = now - timedelta(days=1)
        end = now + timedelta(days=SERVER_LOOKAHEAD_DAYS)
        st = self._state
        for n in range(1, self.screens + 1):
            server = await self.server_events(n, start, end)
            st.server_ok[n] = server is not None
            shows = merge(server or [], self.mars_between(n, start, end), self.tolerance)
            st.merged[n] = shows
            st.day[n] = day_values(shows, now, self.day_start)
        return st

    async def async_refresh_mars(self) -> None:
        """Read MARS now (service / button)."""
        self._last_try = None
        await self.async_request_refresh()
