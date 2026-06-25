"""Match domain entities.

This module defines the match model and the supported sport enum.
"""

from dataclasses import dataclass
from enum import Enum


class Sport(Enum):
    """Supported sports."""

    FOOTBALL = "football"
    HOCKEY = "hockey"


@dataclass(frozen=True)
class Match:
    """
    A match between two teams.

    Attributes:
        url: Full Flashscore match URL.
        sport: Match sport.
        tournament: Tournament or league name, or ``None`` if unavailable.
        home_team_id: Flashscore participant ID of the home team.
        away_team_id: Flashscore participant ID of the away team.
        home_team_name: Home team display name.
        away_team_name: Away team display name.
    """

    url: str
    sport: Sport
    tournament: str | None
    home_team_id: str
    away_team_id: str
    home_team_name: str
    away_team_name: str
