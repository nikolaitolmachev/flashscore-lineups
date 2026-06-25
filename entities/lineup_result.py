"""Aggregated lineup result entity.

This module defines the object returned by the parser.
"""

from dataclasses import dataclass, field

from entities.match import Match
from entities.odds import Odds
from entities.team import Team


@dataclass
class LineupResult:
    """
    Complete lineup data for a match.

    This is the primary output of ``LineupParser.parse()``. It bundles
    the match metadata together with both teams and their full rosters.

    Attributes:
        match: Match metadata.
        home_team: Home team entity with its squad.
        away_team: Away team entity with its squad.
        odds: 1X2 odds from available bookmakers.
    """

    match: Match
    home_team: Team
    away_team: Team
    odds: list[Odds] = field(default_factory=list)
