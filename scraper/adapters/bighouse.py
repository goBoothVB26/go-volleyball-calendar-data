"""Adapter for Big House Open Gym (Tavares, FL).

The schedule isn't published as a calendar -- it's a Weebly storefront
"pick your date" registration product, where each available night is a
checkbox option (e.g. "June 2", value/data-price attributes for the
add-on fee). The page gives no year or time; the year is assumed to be
the current year, and the 8:15-10:15 PM EST time slot is fixed per the
club (Tuesdays/Thursdays), since it's only published in prose on a
different page.
"""

from datetime import datetime, time

from dateutil import parser as dateparser

from ..dateparse import coerce_upcoming_year
from ..fetch import fetch_static
from ..models import Event
from .base import ClubAdapter

START_TIME = time(20, 15)
END_TIME = time(22, 15)
LOCATION = "The Big House, Tavares, FL"


class BigHouseOpenGymAdapter(ClubAdapter):
    club_name = "Big House Open Gym"
    category = "adult"
    schedule_url = "https://www.bighouseusa.com/store/p228/Big_House_Volleyball_Open_Gym_-_Pick_Your_Date.html"

    def scrape(self) -> list[Event]:
        soup = fetch_static(self.schedule_url)
        events: list[Event] = []

        date_group = soup.select_one('div[data-modifier-name="Date"]')
        if not date_group:
            return events

        year = datetime.now().year
        for checkbox in date_group.select('input[type="checkbox"]'):
            date_text = checkbox.get("name")
            if not date_text:
                continue
            try:
                day = coerce_upcoming_year(dateparser.parse(f"{date_text} {year}")).date()
            except (ValueError, OverflowError):
                continue

            # Each date option carries its fee as a data-price attribute
            price = None
            if checkbox.get("data-price"):
                try:
                    price = float(checkbox["data-price"])
                except ValueError:
                    pass

            events.append(
                Event(
                    club=self.club_name,
                    title="Big House Open Gym",
                    start=datetime.combine(day, START_TIME),
                    end=datetime.combine(day, END_TIME),
                    location=LOCATION,
                    url=self.schedule_url,
                    price=price,
                )
            )

        return events
