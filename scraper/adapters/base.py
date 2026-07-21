from abc import ABC, abstractmethod

from ..models import Event


class ClubAdapter(ABC):
    """One adapter per club site. Implement `scrape` to return its events."""

    club_name: str
    schedule_url: str
    category: str  # "youth" or "adult" -- which output calendar this belongs in

    @abstractmethod
    def scrape(self) -> list[Event]:
        ...
