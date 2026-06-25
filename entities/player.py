"""Player domain entities.

This module defines the player-related types used by the lineup parser:
- `Position`: field or ice position.
- `SquadStatus`: lineup status for a specific match.
- `Player`: a squad member.
- `IHGoalkeeper`: a hockey goalkeeper with additional statistics.
"""

from dataclasses import dataclass, field
from enum import Enum

from services.config import HISTORY_DEPTH


class Position(Enum):
    """Player position on the field or ice."""

    GOALKEEPER = "G"
    DEFENDER = "D"
    MIDFIELDER = "M"
    FORWARD = "A"
    UNKNOWN = "?"


class SquadStatus(Enum):
    """Player lineup status for a specific match."""

    IN_XI = 2
    ON_BENCH = 1
    ABSENT = 0
    UNKNOWN = -1


@dataclass
class Player:
    """
    A player in a team roster.

    `participant_id` is the stable Flashscore identifier shared across API responses.

    Attributes:
        participant_id: Flashscore participant identifier.
        name: Display name.
        url: Full Flashscore profile URL.
        shirt_number: Squad number.
        flag_url: CDN URL for the player's flag or emblem.
        age: Player age.
        position: Player position on the field or ice.
        matches_played: Total appearances for the team.
        minutes_played: Total minutes played for the team, if available.
        goals_scored: Total goals scored.
        squad_status: Current match lineup status.
        last_match_statuses: Status history for the last ``HISTORY_DEPTH`` matches, newest first.
    """

    participant_id: str
    name: str
    url: str
    shirt_number: int | None = None
    flag_url: str | None = None
    age: int | None = None
    position: Position = Position.UNKNOWN
    matches_played: int = 0
    minutes_played: int | None = None
    goals_scored: int = 0
    squad_status: SquadStatus = SquadStatus.UNKNOWN
    # Keep this list aligned with HISTORY_DEPTH from services.config.
    # The UI table uses the same constant for its history columns.
    last_match_statuses: list[SquadStatus] = field(
        default_factory=lambda: [SquadStatus.UNKNOWN] * HISTORY_DEPTH
    )

    def __hash__(self) -> int:
        return hash(self.participant_id)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Player):
            return self.participant_id == other.participant_id
        return NotImplemented

    def __ne__(self, other):
        return not self == other


@dataclass
class IHGoalkeeper(Player):
    """
    Ice hockey goalkeeper with additional statistics.

    Extends `Player` with hockey-specific metrics: save percentage,
    goals-against average, and shutouts.

    Attributes:
        sv: Save percentage.
        gaa: Goals-against average.
        so: Total number of shutouts.
    """

    sv: float = 0.0
    gaa: float = 0.0
    so: int = 0

    def __post_init__(self) -> None:
        self.position = Position.GOALKEEPER
