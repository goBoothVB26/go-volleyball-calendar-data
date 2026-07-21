from zoneinfo import ZoneInfo

from icalendar import Calendar, Event as ICalEvent

from .models import Event

EASTERN = ZoneInfo("America/New_York")


def _localize(dt):
    """All source sites post times in local Eastern time with no tzinfo;
    attach it explicitly so calendar apps don't assume UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=EASTERN)
    return dt


def build_calendar(events: list[Event], name: str | None = None) -> Calendar:
    cal = Calendar()
    cal.add("prodid", "-//Volleyball Schedule Scraper//")
    cal.add("version", "2.0")
    if name:
        # X-WR-CALNAME is the calendar's own display name. Google uses it
        # for URL-subscribed calendars in public embeds (otherwise the
        # embed's dropdown shows the raw subscription URL). NAME is the
        # RFC 7986 standard equivalent for other clients.
        cal.add("x-wr-calname", name)
        cal.add("name", name)

    for event in events:
        ical_event = ICalEvent()
        ical_event.add("uid", event.uid())
        ical_event.add("summary", f"[{event.club}] {event.title}")
        if event.all_day:
            ical_event.add("dtstart", event.start.date())
            if event.end:
                ical_event.add("dtend", event.end.date())
        else:
            ical_event.add("dtstart", _localize(event.start))
            if event.end:
                ical_event.add("dtend", _localize(event.end))
        if event.location:
            ical_event.add("location", event.location)

        description_parts = [event.description] if event.description else []
        if event.url:
            description_parts.append(f"More info: {event.url}")
        if description_parts:
            ical_event.add("description", "\n\n".join(description_parts))

        if event.url:
            ical_event.add("url", event.url)
        cal.add_component(ical_event)

    return cal


def write_ics(events: list[Event], path: str, name: str | None = None) -> None:
    cal = build_calendar(events, name=name)
    with open(path, "wb") as f:
        f.write(cal.to_ical())
