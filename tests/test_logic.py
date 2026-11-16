"""Tests of the pure logic (no Home Assistant needed).

Run:  python3 tests/test_logic.py
"""

from datetime import datetime, time, timedelta
import pathlib
import sys
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parents[1]
import importlib.util  # noqa: E402

# load logic.py alone (the package folder would shadow the stdlib "calendar")
_spec = importlib.util.spec_from_file_location("mars_logic", ROOT / "custom_components" / "mars_kinokasse" / "logic.py")
L = importlib.util.module_from_spec(_spec)
sys.modules["mars_logic"] = L
_spec.loader.exec_module(L)

TZ = ZoneInfo("Europe/Berlin")
TOL = timedelta(minutes=10)


def t(day, hh, mm=0, ss=0):
    return datetime(2026, 11, day, hh, mm, ss, tzinfo=TZ)


def test_parse():
    shows = L.parse_export((pathlib.Path(__file__).parent / "sample_export.xml").read_bytes(), TZ)
    assert len(shows) == 4
    s = shows[0]
    assert (s.show_id, s.screen, s.title, s.viewers, s.available, s.capacity) == ("100", 1, "Testfilm", 7, 374, 381)
    assert s.start == t(16, 17) and s.end == t(16, 19, 12)
    assert shows[2].title == "_LEV_Lesung mit Gespräch"  # ISO-8859-1 entity
    assert shows[3].end == t(17, 1, 5)  # after midnight


def test_parse_errors():
    for bad in (b"<html>nope</html>", b"kein xml"):
        try:
            L.parse_export(bad, TZ)
        except L.MarsParseError:
            pass
        else:
            raise AssertionError("expected MarsParseError")


def _ev(start, end, summary, planned=None):
    desc = f"Geplant: {planned:%d.%m.%Y %H:%M} – {end:%H:%M}\nServer-Status: Pending" if planned else ""
    return L.ServerEvent(start, end, summary, desc)


def test_merge():
    mars = [m for m in L.parse_export((pathlib.Path(__file__).parent / "sample_export.xml").read_bytes(), TZ) if m.screen == 1]
    server = [
        _ev(t(16, 17, 0, 13), t(16, 19, 11, 11), "KW46_Testfilm S1", planned=t(16, 17)),  # started 13 s late
        _ev(t(16, 19, 45), t(16, 22, 7), "KW46_Testfilm_OmdU S1", planned=t(16, 19, 45)),
        _ev(t(18, 9), t(18, 10, 40), "Schulvorstellung"),  # only server
    ]
    merged = L.merge(server, mars, TOL)
    assert [m.source for m in merged] == ["beide", "beide", "mars", "server"], [m.source for m in merged]
    a = merged[0]
    assert a.title == "Testfilm" and a.start == t(16, 17, 0, 13) and a.end == t(16, 19, 11, 11)
    assert a.summary() == "Testfilm · 7 Zuschauer"
    assert merged[2].summary() == "** _LEV_Lesung mit Gespräch · 223 Zuschauer"
    assert merged[3].summary() == "Schulvorstellung" and merged[3].viewers is None
    assert "Kasse: 7 Zuschauer, 374 frei, 381 Plätze" in a.description()


def test_merge_handstart_and_planned_start():
    mars = [L.MarsShow("1", 1, "", t(16, 20), t(16, 22), "Film", 10, 5)]
    # hand start 25 min late: matched to the MARS show, no duplicate
    merged = L.merge([_ev(t(16, 20, 25), t(16, 22, 30), "Handstart: Film")], mars, TOL)
    assert [m.source for m in merged] == ["beide"]
    # server started 20 min late but knows the planned time: matched via plan
    merged = L.merge([_ev(t(16, 20, 20), t(16, 22, 20), "KW_Film", planned=t(16, 20))], mars, TOL)
    assert [m.source for m in merged] == ["beide"]
    # unrelated server show far away: two entries
    merged = L.merge([_ev(t(16, 14), t(16, 16), "Anderer")], mars, TOL)
    assert [m.source for m in merged] == ["server", "mars"]


def test_book():
    now = t(16, 18)
    old = L.MarsShow("old", 1, "", t(16, 14), t(16, 16), "gelaufen", 5, 1)
    cancelled = L.MarsShow("gone", 1, "", t(17, 20), t(17, 22), "abgesagt", 0, 1)
    ancient = L.MarsShow("anc", 1, "", t(1, 14), t(1, 16), "alt", 5, 1)
    fresh = [L.MarsShow("new", 1, "", t(16, 20), t(16, 22), "neu", 3, 1)]
    book = L.update_book({"old": old, "gone": cancelled, "anc": ancient}, fresh, now, keep_days=10)
    assert set(book) == {"old", "new"}
    restored = L.MarsShow.from_store(book["new"].to_store())
    assert restored == book["new"]


def test_day_values():
    shows = L.merge(
        [],
        [
            L.MarsShow("1", 1, "", t(16, 17), t(16, 19), "A", 7, 1),
            L.MarsShow("2", 1, "", t(16, 19, 45), t(16, 22), "B", 31, 1),
            L.MarsShow("3", 1, "", t(17, 1), t(17, 3), "Nacht", 2, 1),  # still show day 16
            L.MarsShow("4", 1, "", t(17, 17), t(17, 19), "Morgen", 9, 1),
        ],
        TOL,
    )
    d = L.day_values(shows, t(16, 18), time(4, 0))
    assert d.first_start == t(16, 17) and d.last_start == t(17, 1) and d.last_end == t(17, 3)
    assert d.running.title == "A" and d.next_show.title == "B" and d.next_show.viewers == 31
    d = L.day_values(shows, t(17, 2), time(4, 0))  # 2:00 belongs to the 16th
    assert d.first_start == t(16, 17) and d.next_show.title == "Morgen"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    print("alle Tests ok")
