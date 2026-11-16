"""Home Assistant test: setup, entities, calendar merge (needs pytest-homeassistant-custom-component)."""

from datetime import datetime
import pathlib
from unittest.mock import patch
from zoneinfo import ZoneInfo

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant

DOMAIN = "mars_kinokasse"
SAMPLE = (pathlib.Path(__file__).parent / "sample_export.xml").read_bytes()
TZ = ZoneInfo("Europe/Berlin")


@pytest.fixture
async def berlin(hass: HomeAssistant):
    await hass.config.async_set_time_zone("Europe/Berlin")


async def test_setup(hass: HomeAssistant, berlin, freezer: FrozenDateTimeFactory, aioclient_mock) -> None:
    freezer.move_to(datetime(2026, 11, 16, 18, 0, tzinfo=TZ))
    aioclient_mock.get("http://10.0.0.1:3080/GetRoWo", content=SAMPLE)
    from custom_components.mars_kinokasse.logic import ServerEvent

    async def fake_server(self, screen, start, end):
        if screen != 1:
            return None
        return [
            ServerEvent(datetime(2026, 11, 16, 17, 0, 13, tzinfo=TZ), datetime(2026, 11, 16, 19, 11, tzinfo=TZ),
                        "KW46_Testfilm S1", "Geplant: 16.11.2026 17:00 – 19:11"),
            ServerEvent(datetime(2026, 11, 18, 9, 0, tzinfo=TZ), datetime(2026, 11, 18, 10, 40, tzinfo=TZ),
                        "Schulvorstellung"),
        ]

    entry = MockConfigEntry(
        domain=DOMAIN, title="Kasse MARS",
        data={"host": "10.0.0.1", "port": 3080, "user_id": "u", "password": "p"},
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.mars_kinokasse.coordinator.MarsCoordinator.server_events", fake_server
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        ids = sorted(hass.states.async_entity_ids())
        print(ids)
        assert "calendar.kino1_spielplan" in ids
        nxt = hass.states.get("sensor.kino1_spielplan_zuschauer_nachste_vorstellung")
        assert nxt.state == "31", nxt
        assert nxt.attributes["titel"] == "Testfilm (OmdU)"
        assert hass.states.get("sensor.kino1_spielplan_zuschauer_laufende_vorstellung").state == "7"
        assert hass.states.get("binary_sensor.kasse_mars_kasse_erreichbar").state == "on"
        assert hass.states.get("sensor.kino3_spielplan_zuschauer_nachste_vorstellung").state == "12"

        resp = await hass.services.async_call(
            "calendar", "get_events",
            {"entity_id": "calendar.kino1_spielplan",
             "start_date_time": "2026-11-16T00:00:00+01:00", "end_date_time": "2026-11-19T00:00:00+01:00"},
            blocking=True, return_response=True,
        )
        titles = [e["summary"] for e in resp["calendar.kino1_spielplan"]["events"]]
        assert titles == [
            "Testfilm · 7 Zuschauer",
            "** Testfilm (OmdU) · 31 Zuschauer",  # not in the fake server calendar
            "** _LEV_Lesung mit Gespräch · 223 Zuschauer",
            "Schulvorstellung",
        ], titles


async def test_mars_down(hass: HomeAssistant, berlin, freezer, aioclient_mock) -> None:
    freezer.move_to(datetime(2026, 11, 16, 18, 0, tzinfo=TZ))
    aioclient_mock.get("http://10.0.0.1:3080/GetRoWo", status=500)
    entry = MockConfigEntry(domain=DOMAIN, title="Kasse MARS",
                            data={"host": "10.0.0.1", "port": 3080, "user_id": "u", "password": "p"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.kasse_mars_kasse_erreichbar").state == "off"
    assert hass.states.get("calendar.kino1_spielplan") is not None


async def test_real_server_calendar(hass: HomeAssistant, berlin, freezer, aioclient_mock) -> None:
    """Server events come through the normal calendar.get_events action."""
    from homeassistant.components.calendar import CalendarEntity, CalendarEvent
    from homeassistant.components.calendar.const import DATA_COMPONENT
    from homeassistant.setup import async_setup_component

    freezer.move_to(datetime(2026, 11, 16, 18, 0, tzinfo=TZ))
    aioclient_mock.get("http://10.0.0.1:3080/GetRoWo", content=SAMPLE)
    assert await async_setup_component(hass, "calendar", {})

    class FakeDoremi(CalendarEntity):
        _attr_name = "Kino1 DCP2000 Spielplan"
        entity_id = "calendar.kino1_dcp2000_spielplan"

        @property
        def event(self):
            return None

        async def async_get_events(self, hass, start, end):
            return [
                CalendarEvent(start=datetime(2026, 11, 16, 19, 45, 5, tzinfo=TZ),
                              end=datetime(2026, 11, 16, 22, 7, tzinfo=TZ),
                              summary="KW46_Testfilm_OmdU S1",
                              description="Geplant: 16.11.2026 19:45 – 22:07"),
            ]

    await hass.data[DATA_COMPONENT].async_add_entities([FakeDoremi()])
    entry = MockConfigEntry(domain=DOMAIN, title="Kasse MARS",
                            data={"host": "10.0.0.1", "port": 3080, "user_id": "u", "password": "p"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    resp = await hass.services.async_call(
        "calendar", "get_events",
        {"entity_id": "calendar.kino1_spielplan",
         "start_date_time": "2026-11-16T19:30:00+01:00", "end_date_time": "2026-11-16T23:00:00+01:00"},
        blocking=True, return_response=True,
    )
    ev = resp["calendar.kino1_spielplan"]["events"]
    assert [e["summary"] for e in ev] == ["Testfilm (OmdU) · 31 Zuschauer"], ev
    assert ev[0]["start"].startswith("2026-11-16T19:45:05")
    nxt = hass.states.get("sensor.kino1_spielplan_zuschauer_nachste_vorstellung")
    assert nxt.state == "31" and nxt.attributes["quelle"] == "beide"


async def test_config_flow(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get("http://10.0.0.1:3080/GetRoWo", content=SAMPLE)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == "form"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Kasse MARS", "host": "10.0.0.1", "port": 3080, "user_id": "u", "password": "p"},
    )
    assert result["type"] == "create_entry" and result["title"] == "Kasse MARS"
    assert "name" not in result["data"]
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"screens": 3, "scan_minutes": 5, "tolerance_minutes": 10, "day_start": "04:00:00", "keep_days": 183},
    )
    assert result["type"] == "create_entry"
