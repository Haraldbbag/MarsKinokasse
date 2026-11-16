"""Pure logic: parse the MARS GetRoWo export and merge it with the cinema server schedule.

No Home Assistant imports here, so it can be tested on its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, tzinfo
import re
from typing import Any
import xml.etree.ElementTree as ET

MARS_ONLY_PREFIX = "** "
_PLANNED_RE = re.compile(r"Geplant:\s*(\d{1,2})\.(\d{1,2})\.(\d{4})\s+(\d{1,2}):(\d{2})")


class MarsParseError(Exception):
    """The answer is not a GetRoWo export."""


@dataclass
class MarsShow:
    """One show from the MARS export."""

    show_id: str
    screen: int
    screen_name: str
    start: datetime
    end: datetime
    title: str
    viewers: int | None
    available: int | None
    runtime: int | None = None
    preshow: int | None = None
    release: str = ""
    fsk: str = ""
    seen: datetime | None = None  # last time it was in an export

    @property
    def capacity(self) -> int | None:
        if self.viewers is None or self.available is None:
            return None
        return self.viewers + self.available

    def to_store(self) -> dict[str, Any]:
        return {
            "show_id": self.show_id,
            "screen": self.screen,
            "screen_name": self.screen_name,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "title": self.title,
            "viewers": self.viewers,
            "available": self.available,
            "runtime": self.runtime,
            "preshow": self.preshow,
            "release": self.release,
            "fsk": self.fsk,
            "seen": self.seen.isoformat() if self.seen else None,
        }

    @classmethod
    def from_store(cls, d: dict[str, Any]) -> MarsShow:
        return cls(
            show_id=str(d["show_id"]),
            screen=int(d["screen"]),
            screen_name=d.get("screen_name", ""),
            start=datetime.fromisoformat(d["start"]),
            end=datetime.fromisoformat(d["end"]),
            title=d.get("title", ""),
            viewers=d.get("viewers"),
            available=d.get("available"),
            runtime=d.get("runtime"),
            preshow=d.get("preshow"),
            release=d.get("release", ""),
            fsk=d.get("fsk", ""),
            seen=datetime.fromisoformat(d["seen"]) if d.get("seen") else None,
        )


def _int(text: str | None) -> int | None:
    try:
        return int(text) if text not in (None, "") else None
    except ValueError:
        return None


def _local(text: str, tz: tzinfo) -> datetime:
    """MARS times are local wall-clock times without zone ('2026-11-16 17:00')."""
    return datetime.strptime(text.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=tz)


def parse_export(data: bytes, tz: tzinfo) -> list[MarsShow]:
    """Parse the XML (the encoding comes from the XML declaration, ISO-8859-1)."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as err:
        raise MarsParseError(f"Kein gültiges XML: {err}") from err
    if root.tag != "ROWO_Export":
        raise MarsParseError(f"Unerwartete Antwort ({root.tag})")
    shows: list[MarsShow] = []
    for el in root.findall("Show"):
        g = lambda tag: (el.findtext(tag) or "").strip()  # noqa: E731
        screen = _int(g("ScreenNr"))
        if screen is None or not g("ShowTime"):
            continue
        start = _local(g("ShowTime"), tz)
        end_text = g("ShowEndTime")
        end = _local(end_text, tz) if end_text else start
        if end < start:  # ends after midnight
            end += timedelta(days=1)
        shows.append(
            MarsShow(
                show_id=g("ShowID") or f"{screen}_{start.isoformat()}",
                screen=screen,
                screen_name=g("ScreenName"),
                start=start,
                end=end,
                title=g("Title"),
                viewers=_int(g("Viewer")),
                available=_int(g("still_available")),
                runtime=_int(g("RunTime")),
                preshow=_int(g("PreliminaryRunTime")),
                release=g("release_text"),
                fsk=g("FSK"),
            )
        )
    return shows


def update_book(
    book: dict[str, MarsShow], fresh: list[MarsShow], now: datetime, keep_days: int
) -> dict[str, MarsShow]:
    """Merge a new export into the stored shows.

    - shows in the export replace the stored ones (new ticket numbers),
    - stored shows still in the future that are no longer exported were cancelled -> removed,
    - shows in the past are kept (MARS drops them), until older than keep_days.
    """
    result: dict[str, MarsShow] = {}
    fresh_ids = set()
    for show in fresh:
        show.seen = now
        result[show.show_id] = show
        fresh_ids.add(show.show_id)
    limit = now - timedelta(days=keep_days)
    for sid, show in book.items():
        if sid in fresh_ids:
            continue
        if show.end <= now and show.end >= limit:
            result[sid] = show
    return result


# ------------------------------------------------------------------ merge


@dataclass
class ServerEvent:
    """A show from the cinema server calendar (ha_dcp2000)."""

    start: datetime
    end: datetime
    summary: str
    description: str = ""
    uid: str | None = None

    @property
    def planned_start(self) -> datetime | None:
        m = _PLANNED_RE.search(self.description or "")
        if not m:
            return None
        d, mo, y, h, mi = (int(x) for x in m.groups())
        return datetime(y, mo, d, h, mi, tzinfo=self.start.tzinfo)

    @property
    def is_handstart(self) -> bool:
        return self.summary.startswith("Handstart")


@dataclass
class MergedShow:
    start: datetime
    end: datetime
    title: str
    source: str  # "beide" | "server" | "mars"
    server: ServerEvent | None = None
    mars: MarsShow | None = None
    attrs: dict[str, Any] = field(default_factory=dict)

    @property
    def viewers(self) -> int | None:
        return self.mars.viewers if self.mars else None

    @property
    def key(self) -> str:
        if self.mars:
            return f"m{self.mars.show_id}"
        if self.server and self.server.uid:
            return f"s{self.server.uid}"
        return f"t{self.start.isoformat()}"

    def summary(self) -> str:
        if self.source == "mars":
            text = MARS_ONLY_PREFIX + self.title
        else:
            text = self.title
        if self.viewers is not None:
            text += f" · {self.viewers} Zuschauer"
        return text

    def description(self) -> str:
        lines: list[str] = []
        if self.mars:
            m = self.mars
            lines.append(f"Kasse: {m.viewers if m.viewers is not None else '?'} Zuschauer, "
                         f"{m.available if m.available is not None else '?'} frei"
                         + (f", {m.capacity} Plätze" if m.capacity is not None else ""))
            lines.append(f"Kasse geplant: {m.start:%d.%m.%Y %H:%M} – {m.end:%H:%M}")
            if self.source == "mars":
                lines.append("Nur in der Kasse, nicht im Scheduler des Kinoservers")
        if self.server:
            lines.append(f"Kinoserver: {self.server.summary}")
            if self.server.description:
                lines.append(self.server.description)
        elif self.source == "mars":
            pass
        return "\n".join(lines)

    def info(self) -> dict[str, Any]:
        m = self.mars
        return {
            "titel": self.title,
            "beginn": self.start.isoformat(),
            "ende": self.end.isoformat(),
            "quelle": self.source,
            "zuschauer": m.viewers if m else None,
            "frei": m.available if m else None,
            "plaetze": m.capacity if m else None,
            "mars_show_id": m.show_id if m else None,
            "server_titel": self.server.summary if self.server else None,
        }


def merge(
    server: list[ServerEvent], mars: list[MarsShow], tolerance: timedelta
) -> list[MergedShow]:
    """One entry per show of one screen.

    A server event and a MARS show belong together when the planned start of the
    server event (or its start) is within ``tolerance`` of the MARS start. A hand
    start (no plan) also belongs to a MARS show if it starts within the pre-show
    + 45 minutes after the MARS start.
    """
    free_mars = sorted(mars, key=lambda m: m.start)
    used: set[str] = set()
    result: list[MergedShow] = []

    def best(ev: ServerEvent) -> MarsShow | None:
        ref = ev.planned_start or ev.start
        cands = [
            m for m in free_mars
            if m.show_id not in used and abs(m.start - ref) <= tolerance
        ]
        if not cands and ev.is_handstart:
            cands = [
                m for m in free_mars
                if m.show_id not in used
                and m.start - tolerance <= ev.start <= m.start + timedelta(minutes=45)
            ]
        if not cands:
            return None
        return min(cands, key=lambda m: abs(m.start - ref))

    for ev in sorted(server, key=lambda e: e.start):
        m = best(ev)
        if m is not None:
            used.add(m.show_id)
            result.append(MergedShow(ev.start, max(ev.end, ev.start), m.title, "beide", ev, m))
        else:
            result.append(MergedShow(ev.start, max(ev.end, ev.start), ev.summary, "server", ev, None))
    for m in free_mars:
        if m.show_id not in used:
            result.append(MergedShow(m.start, max(m.end, m.start), m.title, "mars", None, m))
    result.sort(key=lambda s: s.start)
    return result


# ------------------------------------------------------------------ day values


def day_bounds(now: datetime, day_start: time) -> tuple[datetime, datetime]:
    """Show day from day_start (e.g. 04:00) to day_start of the next day."""
    begin = now.replace(hour=day_start.hour, minute=day_start.minute, second=0, microsecond=0)
    if now < begin:
        begin -= timedelta(days=1)
    return begin, begin + timedelta(days=1)


@dataclass
class DayValues:
    first_start: datetime | None
    last_start: datetime | None
    last_end: datetime | None
    next_show: MergedShow | None
    running: MergedShow | None
    today: list[MergedShow]


def day_values(shows: list[MergedShow], now: datetime, day_start: time) -> DayValues:
    begin, end = day_bounds(now, day_start)
    today = [s for s in shows if begin <= s.start < end]
    running = next((s for s in shows if s.start <= now < s.end), None)
    upcoming = [s for s in shows if s.start > now]
    return DayValues(
        first_start=today[0].start if today else None,
        last_start=today[-1].start if today else None,
        last_end=max(s.end for s in today) if today else None,
        next_show=upcoming[0] if upcoming else None,
        running=running,
        today=today,
    )
