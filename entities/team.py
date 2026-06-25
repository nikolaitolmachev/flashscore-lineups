"""Team domain entity.

This module defines the team model used by the lineup parser.
"""

from dataclasses import dataclass, field

from entities.player import Player


@dataclass
class Team:
    """
    A sports team and its roster.

    Attributes:
        participant_id: Flashscore participant identifier.
        name: Team display name.
        url: Full Flashscore team page URL.
        logo_url: CDN URL of the team logo or emblem.
        players: Squad roster.
        uses_minutes: ``True`` if the squad statistics include minutes played.
    """

    participant_id: str
    name: str
    url: str
    logo_url: str | None = None
    players: list[Player] = field(default_factory=list)
    uses_minutes: bool = False
